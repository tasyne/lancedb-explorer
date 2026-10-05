from __future__ import annotations

import base64
import keyword
import re
from dataclasses import dataclass
from typing import Any

import pyarrow as pa


@dataclass(frozen=True, slots=True)
class LanceModelExport:
    """Standalone LanceModel source generated from an Arrow schema."""

    model_name: str
    source: str
    notes: tuple[str, ...]


@dataclass(slots=True)
class _ClassSpec:
    name: str
    fields: list[str]
    uses_aliases: bool = False


def _pascal_case(value: str, *, fallback: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", value)
    name = "".join(word[:1].upper() + word[1:] for word in words) or fallback
    if name[0].isdigit():
        name = f"Table{name}"
    return name


def _model_name(table_name: str) -> str:
    base = _pascal_case(table_name.removesuffix(".lance"), fallback="Table")
    return base if base.endswith("Model") else f"{base}Model"


def _attribute_name(name: str, used: set[str]) -> str:
    candidate = re.sub(r"\W", "_", name)
    if not candidate or candidate[0].isdigit():
        candidate = f"field_{candidate}"
    if candidate.startswith("_"):
        candidate = f"field{candidate}"
    if keyword.iskeyword(candidate):
        candidate = f"{candidate}_"
    base = candidate
    suffix = 2
    while candidate in used:
        candidate = f"{base}_{suffix}"
        suffix += 1
    used.add(candidate)
    return candidate


class _ModelSourceBuilder:
    def __init__(self, schema: pa.Schema, table_name: str, version: object) -> None:
        self.schema = schema
        self.table_name = table_name
        self.version = version
        self.root_name = _model_name(table_name)
        self.class_names = {self.root_name}
        self.classes: list[_ClassSpec] = []
        self.datetime_imports: set[str] = set()
        self.lancedb_imports = {"LanceModel"}
        self.pydantic_imports: set[str] = set()
        self.needs_blob_field = False
        self.needs_base64 = False
        self.notes: set[str] = set()

    def build(self) -> LanceModelExport:
        root = self._build_class(self.root_name, list(self.schema), self.root_name)
        arrow_fields = [self._arrow_field_expression(field) for field in self.schema]
        root.fields.extend(self._schema_method_lines(arrow_fields))

        imports = self._import_lines()
        class_blocks = [self._render_class(spec) for spec in self.classes]
        source = "\n".join(
            [
                self._header_comment(),
                *imports,
                "",
                *self._ipc_helper_lines(),
                *class_blocks,
            ]
        ).rstrip()
        return LanceModelExport(
            model_name=self.root_name,
            source=f"{source}\n",
            notes=tuple(sorted(self.notes)),
        )

    def _header_comment(self) -> str:
        source = repr(self.table_name)
        if self.version is None:
            return f"# Generated from the current schema of {source}."
        return f"# Generated from {source}, table version {self.version}."

    def _new_nested_class_name(self, parent: str, field_name: str) -> str:
        parent_base = parent.removesuffix("Model")
        field_base = _pascal_case(field_name, fallback="Field")
        base = f"{parent_base}{field_base}Model"
        candidate = base
        suffix = 2
        while candidate in self.class_names:
            candidate = f"{base}{suffix}"
            suffix += 1
        self.class_names.add(candidate)
        return candidate

    def _build_class(
        self,
        name: str,
        fields: list[pa.Field],
        path_seed: str,
    ) -> _ClassSpec:
        spec = _ClassSpec(name=name, fields=[])
        used_attributes: set[str] = set()
        for field in fields:
            attribute = _attribute_name(field.name, used_attributes)
            alias = field.name if attribute != field.name else None
            if alias is not None:
                spec.uses_aliases = True
                self.pydantic_imports.add("Field")

            annotation, field_options = self._field_annotation(
                field,
                parent_name=name,
                path_seed=f"{path_seed}.{field.name}",
            )
            options = list(field_options)
            if alias is not None:
                options.insert(0, f"alias={alias!r}")

            if options:
                self.pydantic_imports.add("Field")
                default = "default=None, " if field.nullable else ""
                assignment = f" = Field({default}{', '.join(options)})"
            elif field.nullable:
                assignment = " = None"
            else:
                assignment = ""
            spec.fields.append(f"    {attribute}: {annotation}{assignment}")

        if spec.uses_aliases:
            self.pydantic_imports.add("ConfigDict")
            spec.fields.insert(
                0,
                "    model_config = ConfigDict("
                "validate_by_alias=True, validate_by_name=True, serialize_by_alias=True)\n",
            )
        self.classes.append(spec)
        return spec

    def _field_annotation(
        self,
        field: pa.Field,
        *,
        parent_name: str,
        path_seed: str,
    ) -> tuple[str, list[str]]:
        annotation, options = self._type_annotation(
            field.type,
            field=field,
            parent_name=parent_name,
            path_seed=path_seed,
        )
        if field.nullable and annotation != "None":
            annotation = f"{annotation} | None"
        return annotation, options

    def _type_annotation(
        self,
        data_type: pa.DataType,
        *,
        field: pa.Field,
        parent_name: str,
        path_seed: str,
    ) -> tuple[str, list[str]]:
        if isinstance(data_type, pa.ExtensionType):
            if data_type.extension_name == "lance.blob.v2":
                return "bytes", []
            self.notes.add(
                f"{path_seed} uses extension type {data_type.extension_name!r}; "
                "the annotation validates its Arrow storage value."
            )
            return self._type_annotation(
                data_type.storage_type,
                field=field,
                parent_name=parent_name,
                path_seed=path_seed,
            )
        if pa.types.is_null(data_type):
            return "None", []
        if pa.types.is_boolean(data_type):
            return "bool", []
        if pa.types.is_integer(data_type):
            return "int", []
        if pa.types.is_floating(data_type):
            return "float", []
        if pa.types.is_decimal(data_type):
            return "Decimal", []
        if pa.types.is_string(data_type) or pa.types.is_large_string(data_type):
            return "str", []
        if pa.types.is_string_view(data_type):
            return "str", []
        if (
            pa.types.is_binary(data_type)
            or pa.types.is_large_binary(data_type)
            or pa.types.is_fixed_size_binary(data_type)
            or pa.types.is_binary_view(data_type)
        ):
            return "bytes", []
        if pa.types.is_date(data_type):
            self.datetime_imports.add("date")
            return "date", []
        if pa.types.is_timestamp(data_type):
            self.datetime_imports.add("datetime")
            return "datetime", []
        if pa.types.is_time(data_type):
            self.datetime_imports.add("time")
            return "time", []
        if pa.types.is_duration(data_type):
            self.datetime_imports.add("timedelta")
            return "timedelta", []
        if pa.types.is_struct(data_type):
            nested_name = self._new_nested_class_name(parent_name, field.name)
            self._build_class(nested_name, list(data_type), path_seed)
            return nested_name, []
        if pa.types.is_fixed_size_list(data_type):
            value_type = data_type.value_type
            if pa.types.is_floating(value_type):
                self.lancedb_imports.add("Vector")
                value_option = self._vector_value_option(value_type)
                args = [str(data_type.list_size)]
                if value_option:
                    args.append(value_option)
                args.append(f"nullable={field.nullable!r}")
                return f"Vector({', '.join(args)})", []
            child, _ = self._field_annotation(
                data_type.value_field,
                parent_name=parent_name,
                path_seed=f"{path_seed}[]",
            )
            return f"list[{child}]", [
                f"min_length={data_type.list_size}",
                f"max_length={data_type.list_size}",
            ]
        if self._is_multi_vector(data_type):
            vector_type = data_type.value_type
            self.lancedb_imports.add("MultiVector")
            value_option = self._vector_value_option(vector_type.value_type)
            args = [str(vector_type.list_size)]
            if value_option:
                args.append(value_option)
            args.append(f"nullable={field.nullable!r}")
            return f"MultiVector({', '.join(args)})", []
        if (
            pa.types.is_list(data_type)
            or pa.types.is_large_list(data_type)
            or pa.types.is_list_view(data_type)
            or pa.types.is_large_list_view(data_type)
        ):
            child, _ = self._field_annotation(
                data_type.value_field,
                parent_name=parent_name,
                path_seed=f"{path_seed}[]",
            )
            return f"list[{child}]", []
        if pa.types.is_map(data_type):
            key, _ = self._field_annotation(
                data_type.key_field,
                parent_name=parent_name,
                path_seed=f"{path_seed}.key",
            )
            item, _ = self._field_annotation(
                data_type.item_field,
                parent_name=parent_name,
                path_seed=f"{path_seed}.value",
            )
            return f"dict[{key}, {item}]", []
        if pa.types.is_dictionary(data_type):
            return self._type_annotation(
                data_type.value_type,
                field=field,
                parent_name=parent_name,
                path_seed=path_seed,
            )
        if pa.types.is_union(data_type):
            self.notes.add(
                f"{path_seed} is an Arrow union and is exposed as object for Pydantic validation."
            )
            return "object", []
        if pa.types.is_run_end_encoded(data_type):
            value_field = pa.field("item", data_type.value_type)
            child, _ = self._field_annotation(
                value_field,
                parent_name=parent_name,
                path_seed=f"{path_seed}[]",
            )
            return f"list[{child}]", []

        self.notes.add(
            f"{path_seed} has unsupported annotation type {data_type}; "
            "the exact Arrow field is still retained by to_arrow_schema()."
        )
        return "object", []

    @staticmethod
    def _is_multi_vector(data_type: pa.DataType) -> bool:
        return (
            pa.types.is_list(data_type)
            and pa.types.is_fixed_size_list(data_type.value_type)
            and pa.types.is_floating(data_type.value_type.value_type)
        )

    @staticmethod
    def _vector_value_option(data_type: pa.DataType) -> str:
        if pa.types.is_float32(data_type):
            return ""
        if pa.types.is_float16(data_type):
            return "value_type=pa.float16()"
        if pa.types.is_float64(data_type):
            return "value_type=pa.float64()"
        return f"value_type={_ModelSourceBuilder._primitive_arrow_type(data_type)}"

    def _schema_method_lines(self, fields: list[str]) -> list[str]:
        lines = [
            "",
            "    @classmethod",
            "    def to_arrow_schema(cls) -> pa.Schema:",
            "        # Preserve Arrow details that plain Python annotations cannot express.",
            "        return pa.schema(",
            "            [",
        ]
        lines.extend(f"                {field}," for field in fields)
        lines.append("            ],")
        if self.schema.metadata:
            lines.append(f"            metadata={dict(self.schema.metadata)!r},")
        lines.extend(["        )"])
        return lines

    def _arrow_field_expression(self, field: pa.Field) -> str:
        if (
            isinstance(field.type, pa.ExtensionType)
            and field.type.extension_name == "lance.blob.v2"
        ):
            self.needs_blob_field = True
            expression = f"blob_field({field.name!r}, nullable={field.nullable!r})"
            if field.metadata:
                expression += f".with_metadata({dict(field.metadata)!r})"
            return expression
        try:
            data_type = self._arrow_type_expression(field.type)
        except (NotImplementedError, TypeError, ValueError):
            self.needs_base64 = True
            encoded = base64.b64encode(pa.schema([field]).serialize().to_pybytes()).decode(
                "ascii"
            )
            self.notes.add(
                f"{field.name} uses a serialized Arrow field fallback; import the package that "
                "registers its extension type before evaluating the model."
            )
            return f"_field_from_ipc({encoded!r})"

        arguments = [repr(field.name), data_type, f"nullable={field.nullable!r}"]
        if field.metadata:
            arguments.append(f"metadata={dict(field.metadata)!r}")
        return f"pa.field({', '.join(arguments)})"

    def _arrow_type_expression(self, data_type: pa.DataType) -> str:
        if isinstance(data_type, pa.ExtensionType):
            raise NotImplementedError(data_type.extension_name)
        primitive = self._primitive_arrow_type(data_type)
        if primitive:
            return primitive
        if pa.types.is_decimal(data_type):
            if pa.types.is_decimal32(data_type):
                constructor = "decimal32"
            elif pa.types.is_decimal64(data_type):
                constructor = "decimal64"
            elif pa.types.is_decimal128(data_type):
                constructor = "decimal128"
            else:
                constructor = "decimal256"
            return f"pa.{constructor}({data_type.precision}, {data_type.scale})"
        if pa.types.is_fixed_size_binary(data_type):
            return f"pa.binary({data_type.byte_width})"
        if pa.types.is_timestamp(data_type):
            if data_type.tz is None:
                return f"pa.timestamp({data_type.unit!r})"
            return f"pa.timestamp({data_type.unit!r}, tz={data_type.tz!r})"
        if pa.types.is_time32(data_type):
            return f"pa.time32({data_type.unit!r})"
        if pa.types.is_time64(data_type):
            return f"pa.time64({data_type.unit!r})"
        if pa.types.is_duration(data_type):
            return f"pa.duration({data_type.unit!r})"
        if pa.types.is_fixed_size_list(data_type):
            value = self._arrow_field_expression(data_type.value_field)
            return f"pa.list_({value}, list_size={data_type.list_size})"
        if pa.types.is_list(data_type):
            return f"pa.list_({self._arrow_field_expression(data_type.value_field)})"
        if pa.types.is_large_list(data_type):
            return f"pa.large_list({self._arrow_field_expression(data_type.value_field)})"
        if pa.types.is_list_view(data_type):
            return f"pa.list_view({self._arrow_field_expression(data_type.value_field)})"
        if pa.types.is_large_list_view(data_type):
            return f"pa.large_list_view({self._arrow_field_expression(data_type.value_field)})"
        if pa.types.is_struct(data_type):
            fields = ", ".join(self._arrow_field_expression(child) for child in data_type)
            return f"pa.struct([{fields}])"
        if pa.types.is_map(data_type):
            key = self._arrow_field_expression(data_type.key_field)
            item = self._arrow_field_expression(data_type.item_field)
            return f"pa.map_({key}, {item}, keys_sorted={data_type.keys_sorted!r})"
        if pa.types.is_dictionary(data_type):
            index = self._arrow_type_expression(data_type.index_type)
            value = self._arrow_type_expression(data_type.value_type)
            return f"pa.dictionary({index}, {value}, ordered={data_type.ordered!r})"
        if pa.types.is_union(data_type):
            fields = ", ".join(self._arrow_field_expression(child) for child in data_type)
            codes = list(data_type.type_codes)
            return f"pa.union([{fields}], mode={data_type.mode!r}, type_codes={codes!r})"
        if pa.types.is_run_end_encoded(data_type):
            run_ends = self._arrow_type_expression(data_type.run_end_type)
            values = self._arrow_type_expression(data_type.value_type)
            return f"pa.run_end_encoded({run_ends}, {values})"
        if str(data_type) == "month_day_nano_interval":
            return "pa.month_day_nano_interval()"
        raise NotImplementedError(str(data_type))

    @staticmethod
    def _primitive_arrow_type(data_type: pa.DataType) -> str:
        checks: tuple[tuple[Any, str], ...] = (
            (pa.types.is_null, "pa.null()"),
            (pa.types.is_boolean, "pa.bool_()"),
            (pa.types.is_int8, "pa.int8()"),
            (pa.types.is_int16, "pa.int16()"),
            (pa.types.is_int32, "pa.int32()"),
            (pa.types.is_int64, "pa.int64()"),
            (pa.types.is_uint8, "pa.uint8()"),
            (pa.types.is_uint16, "pa.uint16()"),
            (pa.types.is_uint32, "pa.uint32()"),
            (pa.types.is_uint64, "pa.uint64()"),
            (pa.types.is_float16, "pa.float16()"),
            (pa.types.is_float32, "pa.float32()"),
            (pa.types.is_float64, "pa.float64()"),
            (pa.types.is_date32, "pa.date32()"),
            (pa.types.is_date64, "pa.date64()"),
            (pa.types.is_string, "pa.string()"),
            (pa.types.is_large_string, "pa.large_string()"),
            (pa.types.is_string_view, "pa.string_view()"),
            (pa.types.is_binary, "pa.binary()"),
            (pa.types.is_large_binary, "pa.large_binary()"),
            (pa.types.is_binary_view, "pa.binary_view()"),
        )
        for predicate, expression in checks:
            if predicate(data_type):
                return expression
        return ""

    def _import_lines(self) -> list[str]:
        lines: list[str] = []
        if self.needs_base64:
            lines.append("import base64")
        if self.datetime_imports:
            lines.append(f"from datetime import {', '.join(sorted(self.datetime_imports))}")
        if any("Decimal" in line for spec in self.classes for line in spec.fields):
            lines.append("from decimal import Decimal")
        lines.append("import pyarrow as pa")
        if self.needs_blob_field:
            lines.append("from lance import blob_field")
        lines.append(
            "from lancedb.pydantic import " + ", ".join(sorted(self.lancedb_imports))
        )
        if self.pydantic_imports:
            lines.append("from pydantic import " + ", ".join(sorted(self.pydantic_imports)))
        return lines

    def _ipc_helper_lines(self) -> list[str]:
        if not self.needs_base64:
            return []
        return [
            "def _field_from_ipc(encoded: str) -> pa.Field:",
            "    data = base64.b64decode(encoded)",
            "    return pa.ipc.read_schema(pa.BufferReader(data)).field(0)",
            "",
            "",
        ]

    @staticmethod
    def _render_class(spec: _ClassSpec) -> str:
        fields = spec.fields or ["    pass"]
        return f"class {spec.name}(LanceModel):\n" + "\n".join(fields) + "\n"


def generate_lance_model(
    schema: pa.Schema,
    table_name: str,
    *,
    version: object = None,
) -> LanceModelExport:
    """Generate a standalone LanceModel that retains the table's exact Arrow schema."""

    return _ModelSourceBuilder(schema, table_name, version).build()

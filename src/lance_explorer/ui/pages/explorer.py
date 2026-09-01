from __future__ import annotations

import json

import streamlit as st

from lance_explorer.config import AppConfig
from lance_explorer.paths import is_lance_table_path, make_upath, normalize_uri
from lance_explorer.repository import LanceRepository
from lance_explorer.table_refs import (
    format_namespace_path,
    format_namespace_table_ref,
    namespace_path_from_text,
    resolve_table_location,
    table_parent_resource,
)
from lance_explorer.ui.cache import cached_namespace_tree, children_for_uri
from lance_explorer.ui.components.code_export import show_code_export
from lance_explorer.ui.components.common import display_result, template_directory
from lance_explorer.ui.help_text import help_text
from lance_explorer.ui.state import (
    bump_generation,
    generation_for,
    navigate,
    navigate_back,
    navigate_forward,
    navigate_up,
    select_table,
)


def _icon_button(container: st.delta_generator.DeltaGenerator, label: str, icon: str) -> bool:
    return container.button(
        "",
        key=f"explorer-{label.lower().replace(' ', '-')}",
        help=label,
        icon=icon,
        width="stretch",
    )


def _entry_type(is_dir: bool, is_table: bool) -> str:
    if is_table:
        return "table"
    if is_dir:
        return "directory"
    return "file"


def _entry_icon(entry_type: str, *, selected: bool = False) -> str:
    if selected:
        return "\u2b50"
    return {
        "directory": "\U0001f4c1",
        "table": "\u2733\ufe0f",
        "file": ":material/draft:",
    }[entry_type]


def _entry_label(name: str, entry_type: str) -> str:
    if entry_type == "directory":
        return f"{name}/"
    return name


def _selected_entry_label(name: str, entry_type: str, *, selected: bool) -> str:
    label = _entry_label(name, entry_type)
    if selected:
        return f"-> {label}"
    return label


def _entry_sort_key(entry) -> tuple[int, str]:
    entry_type = _entry_type(entry.is_dir, entry.is_table)
    rank = {"table": 0, "directory": 1, "file": 2}[entry_type]
    return rank, entry.name.lower()


def _namespace_entry_icon(entry_type: str, *, selected: bool = False) -> str:
    if selected:
        return "\u2b50"
    return {
        "namespace": ":material/account_tree:",
        "table": ":material/database:",
    }[entry_type]


def _breadcrumb_items(uri: str) -> list[tuple[str, str]]:
    path = make_upath(uri)
    items: list[tuple[str, str]] = []
    seen: set[str] = set()
    while True:
        path_uri = str(path)
        if path_uri in seen:
            break
        seen.add(path_uri)
        items.append((path.name or path_uri, path_uri))
        parent = path.parent
        if str(parent) == path_uri:
            break
        path = parent
    return list(reversed(items))


def _render_breadcrumbs(current_uri: str) -> None:
    with st.container(key="explorer-breadcrumbs", horizontal=True, gap="small"):
        for index, (label, uri) in enumerate(_breadcrumb_items(current_uri)):
            if index:
                st.markdown("/")
            if st.button(label, key=f"breadcrumb-{index}-{uri}", help=uri, type="tertiary"):
                navigate(uri)
                st.rerun()


def _inject_explorer_styles() -> None:
    st.markdown(
        """
        <style>
        .st-key-directory-listing div[data-testid="stButton"] {
            margin-bottom: 0;
            min-height: 1.75rem;
        }
        .st-key-namespace-listing div[data-testid="stButton"] {
            margin-bottom: 0;
            min-height: 1.75rem;
        }
        .st-key-namespace-tree-list div[data-testid="stButton"] {
            margin-bottom: 0;
            min-height: 1.6rem;
        }
        .st-key-namespace-tree-list div[data-testid="stButton"] button[kind="tertiary"] {
            justify-content: flex-start !important;
            min-height: 1.6rem;
            padding: 0 0.1rem;
            text-align: left !important;
            width: 100% !important;
        }
        .st-key-namespace-tree-list [class*="st-key-namespace-tree-"][class*="-name"]
        div[data-testid="stButton"],
        .st-key-namespace-tree-list [class*="st-key-namespace-tree-"][class*="-table_"]
        div[data-testid="stButton"] {
            width: 100%;
        }
        .st-key-namespace-tree-list [class*="st-key-namespace-tree-"][class*="-name"]
        div[data-testid="stButton"] button[kind="tertiary"],
        .st-key-namespace-tree-list [class*="st-key-namespace-tree-"][class*="-table_"]
        div[data-testid="stButton"] button[kind="tertiary"] {
            align-items: center !important;
            display: flex !important;
            justify-content: flex-start !important;
            text-align: left !important;
            width: 100% !important;
        }
        .st-key-namespace-tree-list [class*="st-key-namespace-tree-"][class*="-name"]
        div[data-testid="stButton"] button[kind="tertiary"] *,
        .st-key-namespace-tree-list [class*="st-key-namespace-tree-"][class*="-table_"]
        div[data-testid="stButton"] button[kind="tertiary"] * {
            justify-content: flex-start !important;
            text-align: left !important;
        }
        .st-key-namespace-tree-list [class*="st-key-namespace-tree-"][class*="-name"]
        div[data-testid="stButton"] button[kind="tertiary"] p,
        .st-key-namespace-tree-list [class*="st-key-namespace-tree-"][class*="-table_"]
        div[data-testid="stButton"] button[kind="tertiary"] p {
            flex: 0 1 auto;
            margin-left: 0;
            text-align: left !important;
        }
        .st-key-directory-listing div[data-testid="stButton"] button[kind="tertiary"] {
            justify-content: flex-start;
            min-height: 1.75rem;
            padding: 0 0.1rem;
            text-align: left;
        }
        .st-key-namespace-listing div[data-testid="stButton"] button[kind="tertiary"] {
            justify-content: flex-start;
            min-height: 1.75rem;
            padding: 0 0.1rem;
            text-align: left;
        }
        .st-key-namespace-tree-list [class*="st-key-namespace-tree-"][class*="-row"] {
            border-radius: 4px;
            padding: 0 0.1rem;
        }
        .st-key-namespace-tree-list [class*="st-key-namespace-tree-"][class*="-row"]:hover {
            background: rgba(128, 128, 128, 0.08);
        }
        .st-key-namespace-tree-list [class*="st-key-namespace-tree-"][class*="-row"]
        div[data-testid="stPopover"] button,
        .st-key-namespace-tree-list [class*="st-key-namespace-tree-"][class*="-row"]
        div[data-testid="stButton"] button[kind="secondary"] {
            opacity: 0.12;
            transition: opacity 120ms ease-in-out;
        }
        .st-key-namespace-tree-list [class*="st-key-namespace-tree-"][class*="-row"]:hover
        div[data-testid="stPopover"] button,
        .st-key-namespace-tree-list [class*="st-key-namespace-tree-"][class*="-row"]:hover
        div[data-testid="stButton"] button[kind="secondary"] {
            opacity: 1;
        }
        .st-key-directory-listing div[data-testid="stButton"] button[kind="tertiary"] p,
        .st-key-namespace-listing div[data-testid="stButton"] button[kind="tertiary"] p,
        .st-key-namespace-tree-list div[data-testid="stButton"] button[kind="tertiary"] p,
        .st-key-explorer-breadcrumbs div[data-testid="stButton"] button[kind="tertiary"] p {
            color: #1f6feb;
            font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
            font-size: 0.86rem;
            line-height: 2;
            overflow: hidden;
            text-decoration: underline;
            text-overflow: ellipsis;
            text-underline-offset: 0.15rem;
            white-space: nowrap;
        }
        .st-key-explorer-breadcrumbs {
            align-items: center;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _namespace_breadcrumb_items(
    namespace_path: tuple[str, ...],
) -> list[tuple[str, tuple[str, ...]]]:
    items: list[tuple[str, tuple[str, ...]]] = [("(root)", ())]
    for index, item in enumerate(namespace_path, start=1):
        items.append((item, namespace_path[:index]))
    return items


def _render_namespace_breadcrumbs(namespace_path: tuple[str, ...]) -> None:
    with st.container(key="namespace-breadcrumbs", horizontal=True, gap="small"):
        for index, (label, path) in enumerate(_namespace_breadcrumb_items(namespace_path)):
            if index:
                st.markdown("/")
            if st.button(
                label,
                key=f"namespace-breadcrumb-{index}-{'/'.join(path)}",
                help=f"Open namespace {format_namespace_path(path)}",
                type="tertiary",
            ):
                st.session_state.namespace_path = list(path)
                st.rerun()


def _parse_properties(value: str) -> dict[str, str]:
    if not value.strip():
        return {}
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError("Namespace properties must be a JSON object")
    return {str(key): str(item) for key, item in parsed.items()}


def _selected_table_name() -> str:
    selected = str(st.session_state.get("selected_table_uri") or "")
    if not selected:
        return ""
    try:
        resolved = resolve_table_location(selected)
    except Exception:
        return ""
    if resolved.namespace:
        return resolved.namespace.table_name
    if resolved.direct:
        return resolved.direct.table_name
    return ""


def _current_namespace_path() -> tuple[str, ...]:
    raw = st.session_state.get("namespace_path", [])
    if isinstance(raw, list):
        return tuple(str(item) for item in raw if str(item).strip())
    return namespace_path_from_text(str(raw or ""))


def _suggest_namespace_root(config: AppConfig) -> str:
    """Suggest a catalog root without implicitly opening it."""

    for value in (
        st.session_state.get("selected_table_uri", ""),
        st.session_state.get("current_uri", ""),
        config.home_uri,
    ):
        if not str(value or "").strip():
            continue
        try:
            return table_parent_resource(str(value))
        except Exception:
            try:
                return normalize_uri(str(value))
            except ValueError:
                continue
    return ""


def _render_namespace_import(
    repository: LanceRepository,
    root: str,
    namespace_path: tuple[str, ...],
    implementation: str,
    *,
    key_prefix: str = "namespace-import",
) -> None:
    with st.popover("Import", icon=":material/input:"):
        selected_table = str(st.session_state.get("selected_table_uri") or "")
        if not selected_table:
            st.caption("Select a table first, then return here to import it into this namespace.")
            return

        target_key = f"{key_prefix}-target"
        source_key = f"{key_prefix}-source-table"
        default_target_name = _selected_table_name()
        if st.session_state.get(source_key) != selected_table:
            st.session_state[source_key] = selected_table
            st.session_state[target_key] = default_target_name
            st.session_state.pop(f"{key_prefix}-overwrite-confirm", None)

        st.caption(f"Source table: `{selected_table}`")
        st.caption(
            "If the selected direct table is already under this catalog root, Lance Explorer "
            "will first try namespace metadata registration, which avoids copying table data. "
            "Otherwise it creates a new namespace table from Arrow batches. Batch copy can move "
            "a lot of data and copies current rows only; version history, tags, and indexes are "
            "not preserved."
        )
        with st.form(f"{key_prefix}-form"):
            target_name = st.text_input(
                "Target table name",
                value=default_target_name,
                placeholder="movie_stars",
                key=target_key,
            )
            mode = st.selectbox("Target mode", ["create", "overwrite"], key=f"{key_prefix}-mode")
            prefer_registration = st.checkbox(
                "Prefer metadata registration when possible",
                value=True,
                key=f"{key_prefix}-prefer-registration",
                help=(
                    "Uses the namespace catalog to point at an existing table location when "
                    "the source table is under the opened catalog root."
                ),
            )
            acknowledgement = st.checkbox(
                "I understand this may overwrite the target or move a large amount of data.",
                key=f"{key_prefix}-ack",
            )
            if mode == "overwrite":
                st.caption("Type the exact target table name to confirm overwrite.")
                st.code(target_name or "", language="text")
                overwrite_confirmation = st.text_input(
                    "Target table name confirmation",
                    key=f"{key_prefix}-overwrite-confirm",
                )
            else:
                overwrite_confirmation = target_name
            submitted = st.form_submit_button("Import table")

        if submitted:
            if not acknowledgement:
                st.error("Confirm the import risk before continuing.")
                return
            if mode == "overwrite" and overwrite_confirmation != target_name:
                st.error("The target table name does not match.")
                return
            try:
                result = repository.import_table_to_namespace(
                    selected_table,
                    root,
                    namespace_path,
                    target_name,
                    implementation=implementation,
                    mode=mode,
                    prefer_registration=prefer_registration,
                )
                st.session_state.operation_results["import_namespace_table"] = result
                bump_generation(root)
                if target := result.get("target"):
                    select_table(str(target))
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
        display_result(st.session_state.operation_results.get("import_namespace_table"))


def _render_create_child_namespace(
    repository: LanceRepository,
    root: str,
    parent_path: tuple[str, ...],
    implementation: str,
    *,
    key_prefix: str,
) -> None:
    with st.popover("", icon=":material/add:"):
        st.caption(f"Parent namespace: `{format_namespace_path(parent_path)}`")
        with st.form(f"{key_prefix}-create-child-form"):
            child_name = st.text_input(
                "Child namespace name",
                placeholder="docs",
                key=f"{key_prefix}-child-name",
            )
            properties_text = st.text_area(
                "Properties as JSON",
                value="{}",
                height=80,
                key=f"{key_prefix}-child-properties",
                help='Example: {"owner": "docs-team"}',
            )
            create = st.form_submit_button("Create child namespace")
        if create:
            try:
                child_path = (*parent_path, *namespace_path_from_text(child_name))
                if child_path == parent_path:
                    st.error("Enter a child namespace name.")
                    return
                st.session_state.operation_results["create_namespace"] = (
                    repository.create_namespace(
                        root,
                        child_path,
                        implementation=implementation,
                        mode="create",
                        properties=_parse_properties(properties_text),
                        create_parents=False,
                    )
                )
                bump_generation(root)
                st.session_state.namespace_path = list(child_path)
                st.rerun()
            except Exception as exc:
                st.error(str(exc))


def _render_drop_namespace_action(
    repository: LanceRepository,
    root: str,
    namespace_path: tuple[str, ...],
    implementation: str,
    *,
    key_prefix: str,
) -> None:
    if not namespace_path:
        return
    with st.popover("", icon=":material/delete:"):
        label = format_namespace_path(namespace_path)
        st.caption(
            "RESTRICT refuses to drop non-empty namespaces. CASCADE asks LanceDB to drop child "
            "namespaces and tables too."
        )
        with st.form(f"{key_prefix}-drop-form"):
            behavior = st.selectbox(
                "Drop behavior",
                ["RESTRICT", "CASCADE"],
                key=f"{key_prefix}-behavior",
            )
            st.caption("Type the exact namespace path to confirm deletion.")
            st.code(label, language="text")
            confirmation = st.text_input("Namespace path confirmation", key=f"{key_prefix}-confirm")
            drop = st.form_submit_button("Drop namespace")
        if drop:
            if confirmation != label:
                st.error("The namespace path does not match.")
                return
            try:
                st.session_state.operation_results["drop_namespace"] = repository.drop_namespace(
                    root,
                    namespace_path,
                    implementation=implementation,
                    behavior=behavior,
                )
                bump_generation(root)
                st.session_state.namespace_path = list(namespace_path[:-1])
                st.rerun()
            except Exception as exc:
                st.error(str(exc))


def _tree_key(namespace_path: tuple[str, ...], suffix: str) -> str:
    safe_parts = [
        "".join(character if character.isalnum() else "_" for character in part)
        for part in namespace_path
    ]
    safe_suffix = "".join(character if character.isalnum() else "_" for character in suffix)
    path_label = "__root__" if not safe_parts else "__".join(safe_parts)
    return f"namespace-tree-{path_label}-{safe_suffix}"


def _namespace_row_label(name: str, *, is_namespace: bool) -> str:
    suffix = "/" if is_namespace else ""
    return f"{name}{suffix}"


def _namespace_row_columns(depth: int):
    indent = min(depth * 0.045, 0.3)
    label = max(0.68 - indent, 0.38)
    return st.columns(
        [max(indent, 0.01), label, 0.06, 0.11, 0.06, 0.09],
        vertical_alignment="center",
    )


def _render_namespace_row(
    node: dict[str, object],
    *,
    repository: LanceRepository,
    root: str,
    implementation: str,
    depth: int,
) -> None:
    namespace_path = tuple(str(item) for item in node.get("path", ()))
    name = str(node.get("name") or "(root)")
    child_namespaces = [
        child for child in node.get("namespaces", []) if isinstance(child, dict)
    ]
    tables = [str(item) for item in node.get("tables", [])]

    with st.container(key=_tree_key(namespace_path, "row"), gap=None):
        row_cols = _namespace_row_columns(depth)
        detail = f"{len(child_namespaces)} child namespaces, {len(tables)} tables"
        if row_cols[1].button(
            _namespace_row_label(name, is_namespace=True),
            key=_tree_key(namespace_path, "name"),
            help=f"{format_namespace_path(namespace_path)}: {detail}",
            icon=_namespace_entry_icon("namespace"),
            type="tertiary",
            width="stretch",
        ):
            st.session_state.namespace_path = list(namespace_path)
            st.rerun()
        with row_cols[2]:
            _render_create_child_namespace(
                repository,
                root,
                namespace_path,
                implementation,
                key_prefix=_tree_key(namespace_path, "create"),
            )
        with row_cols[3]:
            _render_namespace_import(
                repository,
                root,
                namespace_path,
                implementation,
                key_prefix=_tree_key(namespace_path, "import"),
            )
        with row_cols[4]:
            _render_drop_namespace_action(
                repository,
                root,
                namespace_path,
                implementation,
                key_prefix=_tree_key(namespace_path, "drop"),
            )
        with row_cols[5]:
            try:
                metadata = (
                    {}
                    if not namespace_path
                    else repository.describe_namespace(
                        root, namespace_path, implementation=implementation
                    )
                )
            except Exception as exc:
                metadata = {"error": str(exc)}
            if metadata:
                with st.popover("", icon=":material/info:"):
                    st.json(metadata)


def _render_namespace_table_row(
    table_name: str,
    *,
    root: str,
    namespace_path: tuple[str, ...],
    implementation: str,
    depth: int,
) -> None:
    table_ref = format_namespace_table_ref(
        root, namespace_path, table_name, implementation=implementation
    )
    selected = table_ref == st.session_state.get("selected_table_uri", "")
    label = _namespace_row_label(
        f"-> {table_name}" if selected else table_name,
        is_namespace=False,
    )
    with st.container(key=_tree_key(namespace_path, f"table-row-{table_name}"), gap=None):
        row_cols = _namespace_row_columns(depth)
        if row_cols[1].button(
            label,
            key=_tree_key(namespace_path, f"table-{table_name}"),
            help=f"Select namespace table: {table_ref}",
            icon=_namespace_entry_icon("table", selected=selected),
            type="tertiary",
            width="stretch",
        ):
            select_table(table_ref)
            st.session_state.namespace_path = list(namespace_path)
            st.rerun()


def _render_namespace_tree_rows(
    node: dict[str, object],
    *,
    repository: LanceRepository,
    root: str,
    implementation: str,
    depth: int = 0,
) -> None:
    namespace_path = tuple(str(item) for item in node.get("path", ()))
    _render_namespace_row(
        node,
        repository=repository,
        root=root,
        implementation=implementation,
        depth=depth,
    )
    for table_name in [str(item) for item in node.get("tables", [])]:
        _render_namespace_table_row(
            table_name,
            root=root,
            namespace_path=namespace_path,
            implementation=implementation,
            depth=depth + 1,
        )
    for child in [item for item in node.get("namespaces", []) if isinstance(item, dict)]:
        _render_namespace_tree_rows(
            child,
            repository=repository,
            root=root,
            implementation=implementation,
            depth=depth + 1,
        )


def _render_namespace_explorer(config: AppConfig) -> None:
    repository = LanceRepository(config.max_query_rows)
    if "namespace_root_value" not in st.session_state:
        st.session_state.namespace_root_value = (
            st.session_state.get("namespace_root") or _suggest_namespace_root(config)
        )
    with st.form("namespace-root"):
        root_col, impl_col, go_col = st.columns([0.62, 0.22, 0.16], vertical_alignment="bottom")
        root_value = root_col.text_input(
            "Namespace catalog root",
            key="namespace_root_value",
            help="Local path or s3:// root for the namespace catalog.",
        )
        implementation = impl_col.selectbox(
            "Implementation",
            ["dir"],
            help="Directory namespace catalogs can live on local storage or object storage.",
        )
        submitted = go_col.form_submit_button("Open catalog", width="stretch")
    if submitted:
        try:
            st.session_state.namespace_root = normalize_uri(root_value)
            st.session_state.namespace_root_explicit = True
            st.session_state.namespace_path = []
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))

    if not st.session_state.get("namespace_root_explicit"):
        st.info(
            "Enter a namespace catalog root and click Open catalog to browse namespaces.",
            icon=":material/info:",
        )
        st.caption(
            "For demo data, use the parent directory of the generated `.lance` table. "
            "For S3, use the namespace catalog root such as `s3://bucket/lance-root`."
        )
        return

    root = str(st.session_state.get("namespace_root") or "")
    if not root:
        st.warning("Open a namespace catalog root before browsing namespaces.")
        return
    namespace_path = _current_namespace_path()
    st.caption(f"Catalog root: `{root}`")
    st.caption(f"Focused namespace: `{format_namespace_path(namespace_path)}`")
    _render_namespace_breadcrumbs(namespace_path)

    controls = st.columns([1, 1, 8])
    if _icon_button(controls[0], "Namespace Up", ":material/arrow_upward:"):
        st.session_state.namespace_path = list(namespace_path[:-1])
        st.rerun()
    if _icon_button(controls[1], "Refresh Namespaces", ":material/refresh:"):
        bump_generation(root)
        st.rerun()

    try:
        tree = cached_namespace_tree(root, implementation, 8, generation_for(root))
    except Exception as exc:
        st.error(f"Unable to load namespace tree: {exc}")
        return

    st.subheader("Namespace Tree")
    st.caption(
        "Click a namespace name to focus it. Hover over a namespace row to reveal add, import, "
        "delete, and metadata controls."
    )
    show_code_export(
        "create_namespace_table",
        {
            "namespace_root": root,
            "namespace_path": list(namespace_path),
            "table_name": "new_table",
        },
        template_directory=template_directory(config),
    )
    with st.container(key="namespace-tree-list", gap=None):
        _render_namespace_tree_rows(
            tree,
            repository=repository,
            root=root,
            implementation=implementation,
        )
    display_result(st.session_state.operation_results.get("create_namespace"))
    display_result(st.session_state.operation_results.get("drop_namespace"))
    display_result(st.session_state.operation_results.get("import_namespace_table"))


def _render_path_explorer(config: AppConfig) -> None:
    """Render URI navigation and table selection for local/S3 storage."""

    current_uri = st.session_state.current_uri
    if st.session_state.get("uri_bar_synced") != current_uri:
        st.session_state["uri_bar_value"] = current_uri
        st.session_state["uri_bar_synced"] = current_uri
    st.caption("Location", help=help_text("uri_bar"))
    with st.form("uri_bar"):
        uri_col, go_col = st.columns([7, 1], vertical_alignment="bottom")
        entered_uri = uri_col.text_input("URI", key="uri_bar_value", label_visibility="collapsed")
        go = go_col.form_submit_button("Go", width="stretch")
    if go:
        try:
            navigate(entered_uri)
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))

    controls = st.columns([1, 1, 1, 1, 1, 9])
    if _icon_button(controls[0], "Back", ":material/arrow_back:") and navigate_back():
        st.rerun()
    if _icon_button(controls[1], "Forward", ":material/arrow_forward:") and navigate_forward():
        st.rerun()
    if _icon_button(controls[2], "Up", ":material/arrow_upward:"):
        navigate_up()
        st.rerun()
    if _icon_button(controls[3], "Home", ":material/home:"):
        navigate(config.home_uri)
        st.rerun()
    if _icon_button(controls[4], "Refresh", ":material/refresh:"):
        bump_generation(current_uri)
        st.rerun()

    current_uri = st.session_state.current_uri
    st.caption(current_uri)
    _render_breadcrumbs(current_uri)

    if is_lance_table_path(current_uri):
        if st.session_state.get("selected_table_uri") != current_uri:
            select_table(current_uri)
            st.rerun()
        st.info("This URI looks like a Lance table and is now the selected table.")
        show_code_export(
            "open_table",
            {"table_uri": current_uri, "open_version": None},
            template_directory=template_directory(config),
        )
        return

    generation = generation_for(current_uri)
    try:
        entries = children_for_uri(current_uri, generation)
    except Exception as exc:
        st.error(f"Unable to list this URI: {exc}")
        entries = []

    st.subheader("Directory Listing")
    if "explorer_lance_only" not in st.session_state:
        st.session_state["explorer_lance_only"] = True
    lance_only = st.checkbox(
        "Hide non-Lance files",
        key="explorer_lance_only",
        help="Show folders and .lance tables only.",
    )
    if lance_only:
        entries = [entry for entry in entries if entry.is_dir or entry.is_table]
    entries = sorted(entries, key=_entry_sort_key)
    if not entries:
        st.caption("No child paths found.")
    with st.container(key="directory-listing", gap=None):
        selected_table = st.session_state.get("selected_table_uri", "")
        for index, entry in enumerate(entries):
            entry_type = _entry_type(entry.is_dir, entry.is_table)
            is_selected = entry.is_table and entry.uri == selected_table
            help_label = (
                "Select table" if entry.is_table else "Open folder" if entry.is_dir else "View path"
            )
            if st.button(
                _selected_entry_label(entry.name, entry_type, selected=is_selected),
                key=f"entry-{index}-{entry.uri}",
                help=f"{help_label}: {entry.uri}",
                icon=_entry_icon(entry_type, selected=is_selected),
                type="tertiary",
            ):
                if entry.is_table:
                    select_table(entry.uri)
                elif entry.is_dir:
                    navigate(entry.uri)
                else:
                    navigate(entry.uri)
                st.rerun()


def render(config: AppConfig) -> None:
    """Render path and namespace navigation for selecting Lance tables."""

    st.title("Explorer")
    _inject_explorer_styles()
    path_tab, namespace_tab = st.tabs(["Path Explorer", "Namespace Explorer"])
    with path_tab:
        _render_path_explorer(config)
    with namespace_tab:
        _render_namespace_explorer(config)

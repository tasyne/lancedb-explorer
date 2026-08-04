from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from jinja2 import ChoiceLoader, Environment, FileSystemLoader, StrictUndefined

_SECRET_MARKERS = ("secret", "password", "credential", "access_key", "token")


@dataclass(frozen=True, slots=True)
class TemplateSpec:
    """Manifest entry describing a single generated-code template."""

    template_id: str
    file: str
    title: str
    language: str
    required_context: tuple[str, ...]


class TemplateRegistry:
    """Load code templates from an optional override directory and the package."""

    def __init__(self, template_directory: str | Path | None = None) -> None:
        packaged = Path(__file__).resolve().parents[1] / "templates" / "python"
        override = (
            Path(template_directory or os.getenv("LANCE_EXPLORER_TEMPLATE_DIR", "")).expanduser()
            if (template_directory or os.getenv("LANCE_EXPLORER_TEMPLATE_DIR"))
            else None
        )

        self.search_paths = tuple(
            path for path in (override, packaged) if path is not None and path.exists()
        )
        if not self.search_paths:
            raise FileNotFoundError("No code-template directory is available")

        manifest_path = self._resolve("manifest.yaml")
        raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
        templates = raw.get("templates", {})
        self._specs = {
            template_id: TemplateSpec(
                template_id=template_id,
                file=str(config["file"]),
                title=str(config.get("title", template_id.replace("_", " ").title())),
                language=str(config.get("language", "python")),
                required_context=tuple(config.get("required_context", ())),
            )
            for template_id, config in templates.items()
        }

    def get(self, template_id: str) -> TemplateSpec:
        """Return one template specification by ID."""

        try:
            return self._specs[template_id]
        except KeyError as exc:
            raise KeyError(f"Unknown code template: {template_id}") from exc

    def all(self) -> tuple[TemplateSpec, ...]:
        """Return all configured template specifications."""

        return tuple(self._specs.values())

    def fingerprint(self, template_id: str) -> str:
        """Return a source hash used to invalidate rendered-code caches."""

        spec = self.get(template_id)
        source = self._resolve(spec.file).read_bytes()
        return hashlib.sha256(source).hexdigest()

    def _resolve(self, name: str) -> Path:
        for root in self.search_paths:
            candidate = root / name
            if candidate.exists():
                return candidate
        raise FileNotFoundError(f"Template resource not found: {name}")


class TemplateRenderer:
    """Strict Jinja renderer for code-export snippets."""

    def __init__(self, template_directory: str | Path | None = None) -> None:
        self.registry = TemplateRegistry(template_directory)
        self.environment = Environment(
            loader=ChoiceLoader(
                [FileSystemLoader(str(path)) for path in self.registry.search_paths]
            ),
            undefined=StrictUndefined,
            autoescape=False,
            keep_trailing_newline=True,
            trim_blocks=True,
            lstrip_blocks=True,
        )
        self.environment.filters["pyrepr"] = repr
        self.environment.filters["json"] = lambda value: json.dumps(value, indent=2, sort_keys=True)

    def render(self, template_id: str, context: Mapping[str, Any]) -> str:
        """Render a template after validating required and secret-free context."""

        render_context = {**self._runtime_context(), **dict(context)}
        self._validate_safe_context(render_context)
        spec = self.registry.get(template_id)
        missing = [name for name in spec.required_context if name not in render_context]
        if missing:
            raise ValueError(f"Missing template context: {', '.join(missing)}")
        return self.environment.get_template(spec.file).render(**render_context).rstrip() + "\n"

    @staticmethod
    def _validate_safe_context(context: Mapping[str, Any]) -> None:
        unsafe = [
            key for key in context if any(marker in key.lower() for marker in _SECRET_MARKERS)
        ]
        if unsafe:
            raise ValueError(
                "Secret-bearing values cannot be passed to code templates: " + ", ".join(unsafe)
            )

    @staticmethod
    def _runtime_context() -> dict[str, str]:
        return {
            "aws_endpoint": os.getenv("AWS_ENDPOINT") or os.getenv("AWS_ENDPOINT_URL") or "",
            "aws_default_region": os.getenv("AWS_DEFAULT_REGION")
            or os.getenv("AWS_REGION")
            or "",
            "allow_http": os.getenv("ALLOW_HTTP", "false"),
        }

from __future__ import annotations

import json
from dataclasses import fields
from pathlib import Path
from typing import Any

from .models import HardwareSku
from .simple import ProjectMetrics


def _read_json(path: str | Path) -> Any:
    with Path(path).open(encoding="utf-8") as source:
        return json.load(source)


def load_catalog(path: str | Path) -> list[HardwareSku]:
    raw = _read_json(path)
    accepted = {field.name for field in fields(HardwareSku)}
    return [
        HardwareSku(**{key: value for key, value in item.items() if key in accepted})
        for item in raw["skus"]
    ]


def load_project_metrics(path: str | Path) -> ProjectMetrics:
    """Load and validate the business scenario from a small YAML file."""

    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - installation guidance
        raise RuntimeError("PyYAML is required: pip install -r requirements.txt") from exc

    with Path(path).open(encoding="utf-8") as source:
        raw = yaml.safe_load(source)
    if not isinstance(raw, dict) or not isinstance(raw.get("project_metrics"), dict):
        raise ValueError("YAML must contain a project_metrics mapping")

    values = raw["project_metrics"]
    accepted = {field.name for field in fields(ProjectMetrics)}
    unknown = set(values) - accepted
    if unknown:
        raise ValueError(f"Unknown project_metrics fields: {sorted(unknown)}")
    return ProjectMetrics(**values)

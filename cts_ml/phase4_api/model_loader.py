"""Load Phase 3 sklearn Pipeline + manifest from disk."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def default_manifest_path(model_path: Path) -> Path:
    return model_path.parent / "manifest.json"


def load_manifest(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"manifest not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_model_joblib(path: Path) -> Any:
    import joblib

    if not path.is_file():
        raise FileNotFoundError(f"model.joblib not found: {path}")
    return joblib.load(path)


def load_bundle(*, model_path: Path, manifest_path: Path | None) -> tuple[Any, dict[str, Any]]:
    mp = default_manifest_path(model_path) if manifest_path is None else manifest_path
    manifest = load_manifest(mp)
    clf = load_model_joblib(model_path)
    return clf, manifest

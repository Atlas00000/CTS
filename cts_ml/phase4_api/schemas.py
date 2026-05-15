"""Pydantic response models for Phase 4 API."""

from __future__ import annotations

from pydantic import BaseModel, Field


class HealthOut(BaseModel):
    ok: bool
    model_loaded: bool
    model_path: str | None = None
    manifest_path: str | None = None
    label_column: str | None = None
    threshold: float
    host: str
    port: int


class ScoreOut(BaseModel):
    """Aligned with EA shadow logging: score, threshold, would_allow."""

    score: float = Field(..., description="Positive-class probability (y_has_fill).")
    threshold: float = Field(..., description="CTS_AI_THRESHOLD; allow if score >= threshold.")
    would_allow: bool = Field(..., description="True iff score >= threshold (filter policy when enabled).")


class ErrorOut(BaseModel):
    detail: str
    missing_keys: list[str] | None = None

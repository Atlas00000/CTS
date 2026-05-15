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
    adaptive_enabled: bool = False
    adaptive_config_path: str | None = None
    adaptive_version: int | None = None


class FeaturesOut(BaseModel):
    """Contract for EA / client: keys required in POST /score body."""

    feature_columns: list[str]
    numeric_columns: list[str]
    boolean_columns: list[str]
    categorical_columns: list[str]
    label_column: str | None = None


class ScoreOut(BaseModel):
    """Aligned with EA shadow logging: score, threshold, would_allow."""

    score: float = Field(..., description="Positive-class probability (y_has_fill).")
    threshold: float = Field(..., description="Effective allow threshold (per-bucket when adaptive on).")
    would_allow: bool = Field(..., description="True iff score >= threshold (filter policy when enabled).")
    inference_ms: float = Field(..., description="Server-side scoring time (milliseconds).")
    bucket_id: str | None = Field(None, description="Adaptive bucket key (combined mode).")
    risk_multiplier: float | None = Field(None, description="Optional sizing hint from adaptive policy.")
    regime_rule_v1: str | None = None
    atr_quartile: str | None = None


class PolicyOut(BaseModel):
    bucket_id: str
    threshold: float
    risk_multiplier: float
    regime_rule_v1: str
    atr_quartile: str


class ErrorDetail(BaseModel):
    error: str
    missing_keys: list[str] | None = None

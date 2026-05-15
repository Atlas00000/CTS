"""Phase 4 — FastAPI: GET /health, GET /features, POST /score (localhost only)."""

from __future__ import annotations

import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

from dotenv import load_dotenv
from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from phase4_api.adaptive import AdaptivePolicyResolver, load_resolver
from phase4_api.errors import MissingFeaturesError
from phase4_api.model_loader import load_bundle
from phase4_api.schemas import ErrorDetail, FeaturesOut, HealthOut, PolicyOut, ScoreOut
from phase4_api.scorer import score_positive_proba

_DIR = Path(__file__).resolve().parent
_CTS_ML_DIR = _DIR.parent

load_dotenv(_DIR / ".env", override=False)

_score_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="cts_score")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    CTS_PHASE3_MODEL: Path
    CTS_AI_THRESHOLD: float = 0.65
    CTS_API_HOST: str = "127.0.0.1"
    CTS_API_PORT: int = 8008
    CTS_MANIFEST_PATH: Path | None = None
    CTS_SCORE_TIMEOUT_MS: int = 200
    CTS_ADAPTIVE_CONFIG: Path | None = None


def _resolve_under_cts_ml(p: Path) -> Path:
    if p.is_absolute():
        return p
    return (_CTS_ML_DIR / p).resolve()


class AppState:
    settings: Settings | None = None
    clf: Any | None = None
    manifest: dict[str, Any] | None = None
    adaptive: AdaptivePolicyResolver | None = None
    load_error: str | None = None


state = AppState()


def _require_model() -> tuple[Settings, Any, dict[str, Any]]:
    if state.settings is None:
        raise HTTPException(status_code=503, detail=state.load_error or "Invalid configuration")
    if state.clf is None or state.manifest is None:
        raise HTTPException(
            status_code=503,
            detail=state.load_error or "Model not loaded",
        )
    return state.settings, state.clf, state.manifest


def _effective_threshold(body: dict[str, Any], fallback: float) -> tuple[float, dict[str, Any] | None]:
    if state.adaptive is None:
        return fallback, None
    pol = state.adaptive.resolve(body)
    return float(pol["threshold"]), pol


def _run_score(clf: Any, manifest: dict[str, Any], body: dict[str, Any]) -> float:
    return score_positive_proba(clf, manifest, body)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        state.settings = Settings()
    except ValidationError as e:
        state.settings = None
        state.clf = None
        state.manifest = None
        state.load_error = f"Settings validation failed: {e}"
        yield
        return

    try:
        model_p = _resolve_under_cts_ml(state.settings.CTS_PHASE3_MODEL)
        man_p = (
            _resolve_under_cts_ml(state.settings.CTS_MANIFEST_PATH)
            if state.settings.CTS_MANIFEST_PATH
            else None
        )
        state.clf, state.manifest = load_bundle(model_path=model_p, manifest_path=man_p)
        state.adaptive = None
        if state.settings.CTS_ADAPTIVE_CONFIG is not None:
            adapt_p = _resolve_under_cts_ml(state.settings.CTS_ADAPTIVE_CONFIG)
            state.adaptive = load_resolver(adapt_p)
        state.load_error = None
    except Exception as e:  # noqa: BLE001
        state.clf = None
        state.manifest = None
        state.adaptive = None
        state.load_error = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
    yield
    _score_pool.shutdown(wait=False, cancel_futures=True)


app = FastAPI(
    title="CTS Phase 4 scorer",
    version="0.3.0",
    lifespan=lifespan,
    description="Local y_has_fill model + optional adaptive thresholds (AI_integration.md §6–§7).",
)


@app.exception_handler(MissingFeaturesError)
async def missing_features_handler(_request: Request, exc: MissingFeaturesError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content=ErrorDetail(
            error="missing_feature_keys",
            missing_keys=exc.missing_keys,
        ).model_dump(),
    )


@app.exception_handler(RequestValidationError)
async def validation_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "error": "request_validation_failed",
            "missing_keys": None,
            "detail": exc.errors(),
        },
    )


@app.get("/health", response_model=HealthOut)
def health() -> HealthOut:
    s = state.settings
    if s is None:
        return HealthOut(
            ok=False,
            model_loaded=False,
            model_path=None,
            manifest_path=None,
            label_column=None,
            threshold=0.65,
            host="127.0.0.1",
            port=8008,
            adaptive_enabled=False,
        )
    loaded = state.clf is not None and state.manifest is not None
    model_p = _resolve_under_cts_ml(s.CTS_PHASE3_MODEL)
    man_p = (
        _resolve_under_cts_ml(s.CTS_MANIFEST_PATH)
        if s.CTS_MANIFEST_PATH
        else (model_p.parent / "manifest.json")
    )
    adapt_p = (
        str(_resolve_under_cts_ml(s.CTS_ADAPTIVE_CONFIG))
        if s.CTS_ADAPTIVE_CONFIG is not None
        else None
    )
    return HealthOut(
        ok=loaded and state.load_error is None,
        model_loaded=loaded,
        model_path=str(model_p),
        manifest_path=str(man_p),
        label_column=state.manifest.get("label_column") if state.manifest else None,
        threshold=s.CTS_AI_THRESHOLD,
        host=s.CTS_API_HOST,
        port=s.CTS_API_PORT,
        adaptive_enabled=state.adaptive is not None,
        adaptive_config_path=adapt_p,
        adaptive_version=state.adaptive.version if state.adaptive else None,
    )


@app.get("/features", response_model=FeaturesOut)
def features() -> FeaturesOut:
    _settings, _clf, manifest = _require_model()
    return FeaturesOut(
        feature_columns=list(manifest["feature_columns"]),
        numeric_columns=list(manifest.get("numeric_columns", [])),
        boolean_columns=list(manifest.get("boolean_columns", [])),
        categorical_columns=list(manifest.get("categorical_columns", [])),
        label_column=manifest.get("label_column"),
    )


@app.post("/score", response_model=ScoreOut)
def score(body: Annotated[dict[str, Any], Body(...)]) -> ScoreOut:
    s, clf, manifest = _require_model()
    timeout_s = max(0.001, float(s.CTS_SCORE_TIMEOUT_MS) / 1000.0)
    t0 = time.perf_counter()
    fut = _score_pool.submit(_run_score, clf, manifest, body)
    try:
        p = fut.result(timeout=timeout_s)
    except FuturesTimeoutError:
        fut.cancel()
        raise HTTPException(
            status_code=504,
            detail=f"score_timeout: exceeded {s.CTS_SCORE_TIMEOUT_MS} ms server budget",
        ) from None
    except MissingFeaturesError:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"score_error: {type(e).__name__}: {e}") from e

    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    thr, pol = _effective_threshold(body, float(s.CTS_AI_THRESHOLD))
    return ScoreOut(
        score=p,
        threshold=thr,
        would_allow=p >= thr,
        inference_ms=round(elapsed_ms, 3),
        bucket_id=pol["bucket_id"] if pol else None,
        risk_multiplier=pol["risk_multiplier"] if pol else None,
        regime_rule_v1=pol["regime_rule_v1"] if pol else None,
        atr_quartile=pol["atr_quartile"] if pol else None,
    )


@app.post("/policy", response_model=PolicyOut)
def policy(body: Annotated[dict[str, Any], Body(...)]) -> PolicyOut:
    if state.adaptive is None:
        raise HTTPException(status_code=503, detail="adaptive_config_not_loaded")
    pol = state.adaptive.resolve(body)
    return PolicyOut(
        bucket_id=pol["bucket_id"],
        threshold=pol["threshold"],
        risk_multiplier=pol["risk_multiplier"],
        regime_rule_v1=pol["regime_rule_v1"],
        atr_quartile=pol["atr_quartile"],
    )

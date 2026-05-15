"""Phase 4 Week 1 — FastAPI: GET /health, POST /score (localhost only)."""

from __future__ import annotations

import traceback
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

from dotenv import load_dotenv
from fastapi import Body, FastAPI, HTTPException
from pydantic import ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from phase4_api.model_loader import load_bundle
from phase4_api.schemas import HealthOut, ScoreOut
from phase4_api.scorer import score_positive_proba

_DIR = Path(__file__).resolve().parent
_CTS_ML_DIR = _DIR.parent

# phase4_api/.env (optional); env vars can also be set in the shell.
load_dotenv(_DIR / ".env", override=False)


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


def _resolve_under_cts_ml(p: Path) -> Path:
    if p.is_absolute():
        return p
    return (_CTS_ML_DIR / p).resolve()


class AppState:
    settings: Settings | None = None
    clf: Any | None = None
    manifest: dict[str, Any] | None = None
    load_error: str | None = None


state = AppState()


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
        state.load_error = None
    except Exception as e:  # noqa: BLE001 — surface any startup failure in /health
        state.clf = None
        state.manifest = None
        state.load_error = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
    yield


app = FastAPI(
    title="CTS Phase 4 scorer",
    version="0.1.0",
    lifespan=lifespan,
    description="Local y_has_fill model endpoint for EA shadow/filter (AI_integration.md §6).",
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
        )
    loaded = state.clf is not None and state.manifest is not None
    model_p = _resolve_under_cts_ml(s.CTS_PHASE3_MODEL)
    man_p = (
        _resolve_under_cts_ml(s.CTS_MANIFEST_PATH)
        if s.CTS_MANIFEST_PATH
        else (model_p.parent / "manifest.json")
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
    )


@app.post("/score", response_model=ScoreOut)
def score(body: Annotated[dict[str, Any], Body(...)]) -> ScoreOut:
    if state.settings is None:
        raise HTTPException(status_code=503, detail=state.load_error or "Invalid configuration")
    if state.clf is None or state.manifest is None:
        raise HTTPException(
            status_code=503,
            detail=state.load_error or "Model not loaded",
        )
    s = state.settings
    try:
        p = score_positive_proba(state.clf, state.manifest, body)
    except ValueError as e:
        msg = str(e)
        if msg.startswith("missing_keys:"):
            keys = msg.split(":", 1)[1].split(",") if ":" in msg else []
            keys = [k for k in keys if k]
            raise HTTPException(
                status_code=422,
                detail={"error": "missing feature keys", "missing_keys": keys},
            ) from e
        raise HTTPException(status_code=422, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"score_error: {type(e).__name__}: {e}") from e

    thr = float(s.CTS_AI_THRESHOLD)
    return ScoreOut(score=p, threshold=thr, would_allow=p >= thr)


# OpenAPI-friendly error shape for 422 (FastAPI default) remains; 503 uses detail string or dict.

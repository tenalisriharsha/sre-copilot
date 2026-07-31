"""Liveness/readiness probes."""

from fastapi import APIRouter

from sre_copilot import __version__

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "version": __version__}

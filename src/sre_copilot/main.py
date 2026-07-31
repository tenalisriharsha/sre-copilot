"""FastAPI application factory."""

import logging

from fastapi import FastAPI

from sre_copilot import __version__
from sre_copilot.api import alerts, health
from sre_copilot.config import get_settings
from sre_copilot.pipeline import AlertPipeline


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level.upper())

    app = FastAPI(title=settings.app_name, version=__version__)
    app.state.pipeline = AlertPipeline()
    app.include_router(health.router)
    app.include_router(alerts.router)
    return app


app = create_app()

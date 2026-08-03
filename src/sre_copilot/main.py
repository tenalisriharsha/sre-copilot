"""FastAPI application factory."""

import logging

from fastapi import FastAPI

from sre_copilot import __version__
from sre_copilot.api import alerts, health
from sre_copilot.config import get_settings
from sre_copilot.metrics.correlator import MetricsCorrelator
from sre_copilot.pipeline import AlertPipeline
from sre_copilot.rag.retriever import RunbookRetriever


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level.upper())

    app = FastAPI(title=settings.app_name, version=__version__)
    app.state.retriever = RunbookRetriever.from_settings(settings)
    app.state.correlator = MetricsCorrelator.from_settings(settings)
    app.state.pipeline = AlertPipeline(
        retriever=app.state.retriever,
        correlator=app.state.correlator,
    )
    app.include_router(health.router)
    app.include_router(alerts.router)
    return app


app = create_app()

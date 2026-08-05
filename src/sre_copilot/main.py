"""FastAPI application factory."""

import logging

from fastapi import FastAPI

from sre_copilot import __version__
from sre_copilot.api import alerts, health
from sre_copilot.config import get_settings
from sre_copilot.llm.diagnosis import DiagnosisService
from sre_copilot.metrics.correlator import MetricsCorrelator
from sre_copilot.pipeline import AlertPipeline
from sre_copilot.rag.retriever import RunbookRetriever
from sre_copilot.slack.notifier import SlackNotifier


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level.upper())

    app = FastAPI(title=settings.app_name, version=__version__)
    app.state.retriever = RunbookRetriever.from_settings(settings)
    app.state.correlator = MetricsCorrelator.from_settings(settings)
    app.state.diagnoser = DiagnosisService.from_settings(settings)
    app.state.notifier = SlackNotifier.from_settings(settings)
    app.state.pipeline = AlertPipeline(
        retriever=app.state.retriever,
        correlator=app.state.correlator,
        diagnoser=app.state.diagnoser,
        notifier=app.state.notifier,
    )
    app.include_router(health.router)
    app.include_router(alerts.router)
    return app


app = create_app()

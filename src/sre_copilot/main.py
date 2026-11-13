"""FastAPI application factory."""

import logging
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI

from sre_copilot import __version__
from sre_copilot.api import alerts, health
from sre_copilot.config import get_settings
from sre_copilot.llm.diagnosis import DiagnosisService
from sre_copilot.metrics.correlator import MetricsCorrelator
from sre_copilot.pipeline import AlertPipeline
from sre_copilot.rag.retriever import RunbookRetriever
from sre_copilot.slack.notifier import SlackNotifier


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    try:
        yield
    finally:
        async with AsyncExitStack() as stack:
            for service in (app.state.correlator, app.state.diagnoser, app.state.notifier):
                if service is not None:
                    stack.push_async_callback(service.aclose)
            # Let acknowledged alerts finish before closing the clients they use.
            stack.push_async_callback(app.state.pipeline.aclose)


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level.upper())

    app = FastAPI(title=settings.app_name, version=__version__, lifespan=_lifespan)
    app.state.retriever = RunbookRetriever.from_settings(settings)
    app.state.correlator = MetricsCorrelator.from_settings(settings)
    app.state.diagnoser = DiagnosisService.from_settings(settings)
    app.state.notifier = SlackNotifier.from_settings(settings)
    app.state.pipeline = AlertPipeline(
        retriever=app.state.retriever,
        correlator=app.state.correlator,
        diagnoser=app.state.diagnoser,
        notifier=app.state.notifier,
        concurrency=settings.pipeline_concurrency,
        max_pending=settings.pipeline_max_pending,
        state_ttl_seconds=settings.alert_state_ttl_seconds,
        state_max_entries=settings.alert_state_max_entries,
    )
    app.include_router(health.router)
    app.include_router(alerts.router)
    return app


app = create_app()

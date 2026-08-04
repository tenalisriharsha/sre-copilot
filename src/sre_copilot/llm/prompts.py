"""Prompt builder: alert + runbook excerpts + metrics summary → messages."""

import json
from collections.abc import Sequence

from sre_copilot.metrics.models import MetricsSnapshot
from sre_copilot.models import Alert
from sre_copilot.rag.documents import RetrievalHit

SYSTEM_PROMPT = """\
You are an SRE on-call assistant diagnosing a Kubernetes alert.
You are given the alert, relevant runbook excerpts, and recent metrics for
the affected workload.

Respond with a JSON object of the form:
{
  "likely_cause": "one or two sentences naming the most likely root cause",
  "confidence": "low" | "medium" | "high",
  "remediation_steps": ["ordered, concrete steps the on-call engineer should take"]
}

Ground the diagnosis in the provided runbooks and metrics; say so when the
evidence is thin instead of guessing. Respond with JSON only."""


def build_messages(
    alert: Alert,
    runbook_hits: Sequence[RetrievalHit],
    snapshot: MetricsSnapshot | None,
) -> tuple[str, str]:
    """Build the (system, user) messages for a diagnosis chat call."""
    return SYSTEM_PROMPT, _user_prompt(alert, runbook_hits, snapshot)


def _user_prompt(
    alert: Alert,
    runbook_hits: Sequence[RetrievalHit],
    snapshot: MetricsSnapshot | None,
) -> str:
    sections = [
        "## Alert",
        json.dumps(
            {
                "alertname": alert.alertname,
                "status": alert.status,
                "severity": alert.severity,
                "labels": alert.labels,
                "annotations": alert.annotations,
            },
            indent=2,
        ),
        "## Runbook excerpts",
        _format_runbooks(runbook_hits),
        "## Recent metrics",
        _format_metrics(snapshot),
    ]
    return "\n\n".join(sections)


def _format_runbooks(runbook_hits: Sequence[RetrievalHit]) -> str:
    if not runbook_hits:
        return "No matching runbook excerpts found."
    return "\n\n".join(
        f"### {hit.chunk.title} — {hit.chunk.section} (score {hit.score:.2f})\n{hit.chunk.text}"
        for hit in runbook_hits
    )


def _format_metrics(snapshot: MetricsSnapshot | None) -> str:
    if snapshot is None:
        return "Metrics correlation is disabled."
    if snapshot.error is not None:
        return f"Metrics unavailable: {snapshot.error}"
    if not snapshot.series:
        return "No metric series matched this alert."
    lines = [f"Window: last {snapshot.window_minutes} minutes"]
    for series in snapshot.series:
        latest = f"{series.latest_value:.4g}" if series.latest_value is not None else "n/a"
        lines.append(f"- {series.name}: {len(series.points)} points, latest {latest}")
    return "\n".join(lines)

"""Block Kit message builder for alert notifications.

The payload targets Slack incoming webhooks: a plain-text fallback (used in
push notifications and clients without Block Kit) plus a single attachment
whose ``color`` sidebar encodes severity and whose blocks carry the alert
context, the LLM diagnosis, the top runbook excerpt and the metrics summary.
"""

from collections.abc import Sequence
from typing import Any

from sre_copilot.llm.models import Diagnosis
from sre_copilot.metrics.models import MetricsSnapshot
from sre_copilot.models import Alert
from sre_copilot.rag.documents import RetrievalHit

# Slack's preset attachment colors for common severities.
_SEVERITY_COLORS = {
    "critical": "danger",
    "warning": "warning",
    "info": "#439FE0",
}
_DEFAULT_COLOR = "#439FE0"

# Slack limits: header text 150 chars, section text 3000 chars.
_HEADER_LIMIT = 150
_EXCERPT_LIMIT = 600


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _color_for(alert: Alert) -> str:
    if alert.status == "resolved":
        return "good"
    return _SEVERITY_COLORS.get(alert.severity, _DEFAULT_COLOR)


def _diagnosis_block(diagnosis: Diagnosis | None) -> dict[str, Any]:
    if diagnosis is None:
        text = "*Diagnosis*\nNo diagnosis available (LLM stage disabled or failed)."
    else:
        lines = [
            f"*Diagnosis* (confidence: {diagnosis.confidence})",
            diagnosis.likely_cause,
        ]
        if diagnosis.remediation_steps:
            lines.append("*Remediation:*")
            lines.extend(
                f"{i}. {step}" for i, step in enumerate(diagnosis.remediation_steps, start=1)
            )
        text = "\n".join(lines)
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def _runbook_block(hits: Sequence[RetrievalHit]) -> dict[str, Any]:
    if not hits:
        text = "*Runbook*\nNo matching runbook excerpt found."
    else:
        top = hits[0]
        excerpt = _truncate(top.chunk.text.strip(), _EXCERPT_LIMIT)
        text = (
            f"*Runbook:* {top.chunk.title} — {top.chunk.section} (score {top.score:.2f})\n"
            f"```{excerpt}```"
        )
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def _metrics_block(snapshot: MetricsSnapshot | None) -> dict[str, Any]:
    if snapshot is None:
        text = "*Metrics*\nMetrics correlation is disabled."
    elif snapshot.error is not None:
        text = f"*Metrics*\nMetrics unavailable: {snapshot.error}"
    elif not snapshot.series:
        text = f"*Metrics*\nNo metric data in the last {snapshot.window_minutes}m."
    else:
        lines = [f"*Metrics* (last {snapshot.window_minutes}m)"]
        for series in snapshot.series:
            latest = series.latest_value
            value = f"{latest:g}" if latest is not None else "n/a"
            lines.append(f"• `{series.name}`: latest {value} ({len(series.points)} points)")
        text = "\n".join(lines)
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def build_message(
    alert: Alert,
    runbook_hits: Sequence[RetrievalHit] = (),
    snapshot: MetricsSnapshot | None = None,
    diagnosis: Diagnosis | None = None,
) -> dict[str, Any]:
    """Build the Slack webhook payload for one processed alert."""
    icon = ":white_check_mark:" if alert.status == "resolved" else ":rotating_light:"
    header = _truncate(f"{icon} {alert.status.upper()}: {alert.alertname}", _HEADER_LIMIT)
    summary = alert.annotations.get("summary") or "No summary annotation."
    context = (
        f"*severity:* {alert.severity}  |  "
        f"*namespace:* {alert.labels.get('namespace', 'n/a')}  |  "
        f"*pod:* {alert.labels.get('pod', 'n/a')}  |  "
        f"*fingerprint:* {alert.fingerprint or 'n/a'}"
    )
    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": header}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": context}]},
        {"type": "section", "text": {"type": "mrkdwn", "text": summary}},
        {"type": "divider"},
        _diagnosis_block(diagnosis),
        _runbook_block(runbook_hits),
        _metrics_block(snapshot),
    ]
    return {
        "text": f"{alert.status.upper()}: {alert.alertname} — {summary}",
        "attachments": [{"color": _color_for(alert), "blocks": blocks}],
    }

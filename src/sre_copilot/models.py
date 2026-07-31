"""Pydantic models for the Alertmanager v4 webhook payload."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Alert(BaseModel):
    """A single alert instance as delivered by Alertmanager."""

    model_config = ConfigDict(populate_by_name=True)

    status: Literal["firing", "resolved"]
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)
    starts_at: datetime = Field(alias="startsAt")
    ends_at: datetime | None = Field(default=None, alias="endsAt")
    generator_url: str = Field(default="", alias="generatorURL")
    fingerprint: str = ""

    @property
    def alertname(self) -> str:
        return self.labels.get("alertname", "unknown")

    @property
    def severity(self) -> str:
        return self.labels.get("severity", "unknown")


class WebhookPayload(BaseModel):
    """Top-level Alertmanager webhook payload (a group of alerts)."""

    model_config = ConfigDict(populate_by_name=True)

    version: str = "4"
    group_key: str = Field(default="", alias="groupKey")
    status: Literal["firing", "resolved"]
    receiver: str = ""
    group_labels: dict[str, str] = Field(default_factory=dict, alias="groupLabels")
    common_labels: dict[str, str] = Field(default_factory=dict, alias="commonLabels")
    common_annotations: dict[str, str] = Field(default_factory=dict, alias="commonAnnotations")
    external_url: str = Field(default="", alias="externalURL")
    alerts: list[Alert] = Field(default_factory=list)


class AlertAck(BaseModel):
    """Response returned to Alertmanager after accepting a payload."""

    status: Literal["accepted"] = "accepted"
    received: int
    fingerprints: list[str]
    detail: dict[str, Any] = Field(default_factory=dict)

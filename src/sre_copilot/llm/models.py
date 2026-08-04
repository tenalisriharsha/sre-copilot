"""Structured output model for the LLM diagnosis stage."""

from typing import Literal

from pydantic import BaseModel, Field


class Diagnosis(BaseModel):
    """The LLM's structured take on one alert.

    Produced from the alert, its runbook excerpts and its metrics snapshot;
    the JSON schema of this model is what the prompt asks the LLM to fill.
    """

    likely_cause: str
    confidence: Literal["low", "medium", "high"] = "low"
    remediation_steps: list[str] = Field(default_factory=list)

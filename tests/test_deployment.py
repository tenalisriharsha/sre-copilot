"""Structural checks for the Dockerfile and Helm chart (Phase 6).

These don't need the ``docker``/``helm`` binaries, so they always run as
part of the normal suite; real builds are verified manually (see PROGRESS.md).
"""

from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]
CHART = ROOT / "chart" / "sre-copilot"


def test_dockerfile_is_a_multi_stage_non_root_build():
    text = (ROOT / "Dockerfile").read_text()
    assert "AS builder" in text
    assert "AS runtime" in text
    assert "-c constraints.txt" in text
    assert "USER sre-copilot" in text
    assert "HEALTHCHECK" in text
    assert "uvicorn" in text
    assert "sre_copilot.main:app" in text


def test_chart_yaml_declares_an_application_chart():
    chart = yaml.safe_load((CHART / "Chart.yaml").read_text())
    assert chart["name"] == "sre-copilot"
    assert chart["type"] == "application"
    assert chart["version"]
    assert chart["appVersion"]


def test_values_yaml_has_the_settings_the_templates_expect():
    values = yaml.safe_load((CHART / "values.yaml").read_text())
    assert values["replicaCount"] == 1
    assert "llmApiKey" in values["secret"]
    assert "slackWebhookUrl" in values["secret"]
    assert values["autoscaling"]["enabled"] is False
    # More than one replica needs shared pipeline state; see README.
    assert values["autoscaling"]["maxReplicas"] == 1


def test_all_expected_templates_exist():
    expected = {
        "_helpers.tpl",
        "configmap.yaml",
        "secret.yaml",
        "deployment.yaml",
        "service.yaml",
        "hpa.yaml",
        "NOTES.txt",
    }
    present = {p.name for p in (CHART / "templates").iterdir()}
    assert expected <= present


def test_secret_template_is_conditional_on_existing_secret():
    text = (CHART / "templates" / "secret.yaml").read_text()
    assert "{{- if not .Values.secret.existingSecret }}" in text


def test_deployment_wires_env_from_configmap_and_secret():
    text = (CHART / "templates" / "deployment.yaml").read_text()
    assert "configMapRef" in text
    assert "SRE_COPILOT_LLM_API_KEY" in text
    assert "SRE_COPILOT_SLACK_WEBHOOK_URL" in text
    assert "livenessProbe" in text
    assert "readinessProbe" in text

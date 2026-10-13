"""Regenerate the README preview images from a real local run.

Starts ``uvicorn sre_copilot.main:app`` on 127.0.0.1:8000 with default
settings (no LLM key, no Slack webhook, Prometheus at the default
``http://prometheus:9090``, which does not resolve locally). Each terminal
image runs its command with ``bash -c`` and renders the captured stdout and
stderr unmodified; the command shown after ``$`` is the exact string that
ran. Swagger images are screenshots of the running server's ``/docs``.

Usage (needs curl and jq on PATH):

    pip install playwright==1.56.0 && playwright install chromium
    python scripts/capture_previews.py            # every image
    python scripts/capture_previews.py 04 07      # only some
"""

import html
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "screenshots"
BASE = "http://127.0.0.1:8000"
FINGERPRINT = "a1b2c3d4e5f6"


def sample_alert(status: str) -> dict:
    return {
        "version": "4",
        "status": status,
        "receiver": "sre-copilot",
        "groupLabels": {"alertname": "KubePodCrashLooping"},
        "alerts": [
            {
                "status": status,
                "labels": {
                    "alertname": "KubePodCrashLooping",
                    "namespace": "payments",
                    "pod": "payments-api-6d9f7c8b5-x2v4k",
                    "severity": "critical",
                },
                "annotations": {
                    "summary": "Pod payments/payments-api-6d9f7c8b5-x2v4k is crash looping"
                },
                "startsAt": "2026-07-31T02:14:03Z",
                "fingerprint": FINGERPRINT,
            }
        ],
    }


TERMINAL_CSS = """
body { margin: 0; background: #ffffff; }
.win { width: 900px; background: #0d1117; border: 1px solid #30363d;
       border-radius: 10px; overflow: hidden; font-family: 'DejaVu Sans Mono', monospace; }
.bar { background: #161b22; padding: 9px 14px; color: #8b949e; font-size: 13px;
       border-bottom: 1px solid #30363d; }
.dot { display: inline-block; width: 12px; height: 12px; border-radius: 50%; margin-right: 6px;
       vertical-align: -1px; }
pre { margin: 0; padding: 14px 20px 18px; color: #e6edf3; font-size: 13.5px; line-height: 1.3;
      white-space: pre-wrap; word-break: break-all; font-family: inherit; }
.prompt { color: #79c0ff; }
"""


def render_terminal(page: Page, title: str, command: str, cwd: Path, out: Path) -> None:
    """Run ``command`` in bash and screenshot its real output in a terminal frame."""
    result = subprocess.run(
        ["bash", "-c", command], cwd=cwd, capture_output=True, text=True, timeout=60
    )
    output = result.stdout + result.stderr
    if result.returncode != 0:
        raise RuntimeError(f"command failed ({result.returncode}): {command}\n{output}")
    dots = "".join(
        f'<span class="dot" style="background:{c}"></span>'
        for c in ("#ff5f56", "#ffbd2e", "#27c93f")
    )
    page.set_viewport_size({"width": 902, "height": 200})
    page.set_content(
        f"<style>{TERMINAL_CSS}</style><div class='win'>"
        f"<div class='bar'>{dots}&nbsp;{html.escape(title)}</div>"
        f"<pre><span class='prompt'>$</span> {html.escape(command)}\n"
        f"{html.escape(output.rstrip())}</pre></div>"
    )
    page.locator(".win").screenshot(path=str(out))
    print(f"wrote {out.relative_to(ROOT)}")


def wait_until(url: str, predicate, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                if predicate(json.load(resp)):
                    return
        except OSError:
            pass
        time.sleep(0.2)
    raise TimeoutError(url)


def main(selected: set[str]) -> None:
    for tool in ("curl", "jq"):
        if shutil.which(tool) is None:
            sys.exit(f"{tool} is required")

    def want(name: str) -> bool:
        return not selected or name in selected

    workdir = Path(tempfile.mkdtemp(prefix="sre-copilot-previews-"))
    (workdir / "sample-alert.json").write_text(json.dumps(sample_alert("firing"), indent=2))
    (workdir / "resolved-alert.json").write_text(json.dumps(sample_alert("resolved"), indent=2))

    env = {k: v for k, v in os.environ.items() if not k.startswith("SRE_COPILOT_")}
    env["SRE_COPILOT_CHROMA_PERSIST_DIR"] = str(workdir / "chroma")
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "sre_copilot.main:app", "--port", "8000"],
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        wait_until(f"{BASE}/healthz", lambda body: body.get("status") == "ok")
        with sync_playwright() as pw:
            # Swagger UI loads its JS/CSS from a CDN; honour a configured proxy.
            proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
            browser = pw.chromium.launch(
                proxy={"server": proxy, "bypass": "127.0.0.1,localhost"} if proxy else None
            )
            page = browser.new_page()
            title = "sre-copilot (local run: no Prometheus, LLM key or Slack webhook configured)"

            if want("01"):
                page.set_viewport_size({"width": 1280, "height": 900})
                page.goto(f"{BASE}/docs")
                page.wait_for_selector(".opblock")
                page.screenshot(path=str(OUT / "01-swagger-overview.png"))
                print("wrote docs/screenshots/01-swagger-overview.png")
            if want("02"):
                page.set_viewport_size({"width": 1280, "height": 900})
                page.goto(f"{BASE}/docs")
                page.locator("#operations-alerts-receive_alerts_api_v1_alerts_post").click()
                page.wait_for_selector(".opblock-body")
                page.screenshot(path=str(OUT / "02-swagger-alerts-endpoint.png"))
                print("wrote docs/screenshots/02-swagger-alerts-endpoint.png")
            if want("03"):
                render_terminal(
                    page,
                    "sre-copilot: GET /healthz",
                    "curl -s localhost:8000/healthz | jq",
                    workdir,
                    OUT / "03-healthz.png",
                )
            # 07 shows the result of 04's POST, so asking for 07 also runs 04.
            if want("04") or want("07"):
                render_terminal(
                    page,
                    title,
                    "curl -s -o ack.json -w 'HTTP %{http_code}\\n' -X POST "
                    "localhost:8000/api/v1/alerts -H 'Content-Type: application/json' "
                    "-d @sample-alert.json && jq . ack.json",
                    workdir,
                    OUT / "04-alert-ingested.png",
                )
            if want("07"):
                # Not shown: wait for the background stages, then show the result.
                wait_until(
                    f"{BASE}/api/v1/alerts/{FINGERPRINT}", lambda body: body["state"] == "done"
                )
                render_terminal(
                    page,
                    title,
                    f"curl -s localhost:8000/api/v1/alerts/{FINGERPRINT} | jq",
                    workdir,
                    OUT / "07-alert-status.png",
                )
            if want("06"):
                render_terminal(
                    page,
                    title,
                    "curl -s -o ack.json -w 'HTTP %{http_code}\\n' -X POST "
                    "localhost:8000/api/v1/alerts -H 'Content-Type: application/json' "
                    "-d @resolved-alert.json && jq . ack.json",
                    workdir,
                    OUT / "06-alert-resolved.png",
                )
            if want("05"):
                page.set_viewport_size({"width": 1280, "height": 900})
                page.goto(f"{BASE}/docs")
                page.locator("#operations-health-healthz_healthz_get").click()
                page.wait_for_selector(".opblock-body")
                page.locator("#operations-health-healthz_healthz_get").screenshot(
                    path=str(OUT / "05-swagger-healthz-endpoint.png")
                )
                print("wrote docs/screenshots/05-swagger-healthz-endpoint.png")
            browser.close()
    finally:
        server.terminate()
        server.wait(timeout=30)
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    main(set(sys.argv[1:]))

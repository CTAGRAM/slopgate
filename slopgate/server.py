"""GitHub webhook receiver: every new or updated pull request gets triaged and labelled."""

import hashlib
import hmac
import json
import logging

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request

from . import config
from .pipeline import SlopGate, summary

log = logging.getLogger("uvicorn.error")
settings = config.load()
gate = SlopGate(settings)
app = FastAPI(title="SlopGate")
TRIGGERS = {"opened", "reopened", "edited", "synchronize", "ready_for_review"}

if not settings.webhook_secret:
    log.warning("GITHUB_WEBHOOK_SECRET is not set: webhook signatures are NOT checked")


@app.get("/healthz")
def healthz():
    return {"ok": True, "model": settings.model}


@app.get("/triage")
def triage(url: str):
    pr, t = gate.triage(url)
    return summary(pr, t)


def _triage_and_apply(url: str) -> None:
    try:
        pr, t = gate.triage(url)
        gate.apply(pr, t)
        log.info("triaged %s -> %s (%.0f%%)", url, t.verdict, t.confidence * 100)
    except Exception:
        log.exception("triage failed for %s", url)


@app.post("/webhook")
async def webhook(
    request: Request,
    tasks: BackgroundTasks,
    x_github_event: str = Header(""),
    x_hub_signature_256: str = Header(""),
):
    body = await request.body()
    if settings.webhook_secret:
        expected = "sha256=" + hmac.new(settings.webhook_secret.encode(), body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, x_hub_signature_256):
            raise HTTPException(401, "bad signature")
    if x_github_event != "pull_request":
        return {"ignored": x_github_event}
    payload = json.loads(body)
    if payload.get("action") not in TRIGGERS:
        return {"ignored": payload.get("action")}
    url = payload["pull_request"]["html_url"]
    tasks.add_task(_triage_and_apply, url)  # answer GitHub fast; the read happens right after
    return {"queued": url}

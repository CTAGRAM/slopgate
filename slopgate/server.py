"""GitHub webhook receiver, plus the arena page: every contender on one PR, live."""

import hashlib
import hmac
import json
import logging
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from functools import lru_cache
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse

from . import config
from .arena import contenders, run_safely
from .judge import build_state, facts
from .pipeline import SlopGate, summary

log = logging.getLogger("uvicorn.error")
settings = config.load()
gate = SlopGate(settings)
app = FastAPI(title="SlopGate")
TRIGGERS = {"opened", "reopened", "edited", "synchronize", "ready_for_review"}
STATIC = Path(__file__).parent / "static"
RESULTS = Path(__file__).resolve().parents[1] / "eval" / "results"
FEED: deque[dict] = deque(maxlen=30)  # the latest webhook triages, newest first

if not settings.webhook_secret:
    log.warning("GITHUB_WEBHOOK_SECRET is not set: webhook signatures are NOT checked")


@app.get("/healthz")
def healthz():
    return {"ok": True, "model": settings.model}


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/triage")
def triage(url: str):
    pr, t = gate.triage(url)
    return summary(pr, t)


@app.get("/feed")
def feed():
    return list(FEED)


@app.get("/results")
def results():
    """The held-out evaluation: PRs CodeRabbit reviewed, never used while building SlopGate."""
    path = RESULTS / "coderabbit.json"
    return json.loads(path.read_text())["everyone"] if path.exists() else None


@lru_cache(maxsize=1)
def _field():
    return contenders(settings, gate.github)  # built once: anti-slop starts its proxy here


def _sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


@app.get("/arena/stream")
def arena_stream(url: str):
    def events():
        try:
            pr = gate.github.pull_request(url)
        except Exception as e:  # noqa: BLE001
            yield _sse("fail", {"error": str(e)[:300]})
            return
        yield _sse("pr", {"url": pr.url, "title": pr.title, "repo": f"{pr.owner}/{pr.repo}",
                          "number": pr.number, "author": pr.author, "facts": facts(pr)})
        state, field = build_state(pr), _field()
        yield _sse("start", {"contenders": [{"name": c.label} for c in field]})
        with ThreadPoolExecutor(len(field)) as pool:
            for done in as_completed([pool.submit(run_safely, c, pr, state) for c in field]):
                yield _sse("opinion", asdict(done.result()))
        yield _sse("done", {})

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _triage_and_apply(url: str) -> None:
    try:
        pr, t = gate.triage(url)
        gate.apply(pr, t)
        FEED.appendleft(summary(pr, t) | {"title": pr.title, "author": pr.author, "at": time.time()})
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

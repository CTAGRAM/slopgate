"""GitHub webhook receiver, plus the dashboard: live gate, arena, scoreboard, threats and stack."""

import hashlib
import hmac
import json
import logging
import os
import queue
import statistics
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from functools import lru_cache
from itertools import cycle
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse

from . import config, report
from .events import Bus
from .arena import FINAL, contenders, final_opinion, run_safely
from .escalate import system_two
from .judge import build_state, fact_values, facts, is_trusted
from .pipeline import SlopGate, summary

log = logging.getLogger("uvicorn.error")
settings = config.load()
gate = SlopGate(settings)
app = FastAPI(title="SlopGate")
TRIGGERS = {"opened", "reopened", "edited", "synchronize", "ready_for_review"}
STATIC = Path(__file__).parent / "static"
RESULTS = Path(__file__).resolve().parents[1] / "eval" / "results"
FEED: deque[dict] = deque(maxlen=30)  # the latest triages, newest first
BUS = Bus()  # every stage of every PR, for the live views
TOTALS = {"triaged": 0, "spam": 0, "injections": 0, "started": time.time()}
DEMO_PRS = cycle(f"https://github.com/CTAGRAM/slopgate-demo/pull/{n}" for n in (2, 4, 3, 5, 6))

if not settings.webhook_secret:
    log.warning("GITHUB_WEBHOOK_SECRET is not set: webhook signatures are NOT checked")


@app.get("/healthz")
def healthz():
    return {"ok": True, "model": settings.model}


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/support.js")
def support_js():
    return FileResponse(STATIC / "support.js", media_type="text/javascript")


@app.get("/api/dashboard")
def dashboard():
    """The evaluation, precomputed by eval/dashboard.py."""
    path = RESULTS / "dashboard.json"
    return json.loads(path.read_text()) if path.exists() else None


@app.get("/api/status")
def status():
    llm = system_two(settings)
    times = [f["server_ms"] for f in FEED if f.get("server_ms")]
    return {
        "model": settings.model,
        "system_two": f"{llm[2]} on {'DO Gradient' if 'do-ai.run' in llm[0] else 'Codiv'}" if llm else None,
        "gradient": bool(settings.gradient_key and settings.gradient_model),
        "host": os.environ.get("SLOPGATE_HOST_LABEL", "local"),
        "webhook_verified": bool(settings.webhook_secret),
        "median_ms": statistics.median(times) if times else None,
        **TOTALS,
    }


@app.get("/feed")
def feed():
    return list(FEED)


@app.get("/sim")
def sim():
    return FileResponse(STATIC / "sim.html")


@app.get("/api/events")
def events():
    """Every stage of every PR, live: the 3D pipeline, the dashboard and demo/watch.py listen here."""
    q, backlog = BUS.subscribe()

    def stream():
        try:
            yield _sse("hello", {"backlog": backlog, "now": time.time()})
            while True:
                try:
                    yield _sse("stage", q.get(timeout=15))
                except queue.Empty:
                    yield ": keep-alive\n\n"
        finally:
            BUS.unsubscribe(q)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/triage")
def triage(url: str):
    pr, t = gate.triage(url)
    return summary(pr, t)


def _record(item: dict) -> None:
    FEED.appendleft(item | {"at": time.time()})
    TOTALS["triaged"] += 1
    TOTALS["spam"] += item["verdict"] == "spam"
    TOTALS["injections"] += "injection" in item["flags"]


@app.post("/api/replay")
def replay():
    """'Simulate PR': run a real demo PR through the gate again. Read-only: nothing is labelled."""
    url = next(DEMO_PRS)
    emit = BUS.emitter(url, "replay")
    emit("received")
    try:
        pr, t = gate.triage(url, emit=emit)
    except Exception as e:
        emit("failed", error=str(e)[:300])
        raise
    item = summary(pr, t) | {"replay": True}
    _record(item)
    emit("done", item=item, labels=[], applied=False)
    return item


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
                          "number": pr.number, "author": pr.author, "facts": facts(pr), "info": fact_values(pr)})
        state, field = build_state(pr), _field()
        names = [c.label for c in field]
        final = "SlopGate · OpenJev" in names and "anti-slop (34 rules)" in names
        yield _sse("start", {"contenders": [{"name": n} for n in ([FINAL] if final else []) + names]})
        got = {}
        with ThreadPoolExecutor(len(field)) as pool:
            for done in as_completed([pool.submit(run_safely, c, pr, state) for c in field]):
                o = done.result()
                got[o.contender] = o
                yield _sse("opinion", asdict(o))
                if final and "SlopGate · OpenJev" in got and "anti-slop (34 rules)" in got and FINAL not in got:
                    got[FINAL] = final_opinion(got["SlopGate · OpenJev"], got["anti-slop (34 rules)"],
                                               is_trusted(pr, settings.judge_all_authors))
                    yield _sse("opinion", asdict(got[FINAL]))
        yield _sse("done", {})

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _triage_and_apply(url: str, emit) -> None:
    try:
        pr, t = gate.triage(url, emit=emit)
        emit("applying")
        gate.apply(pr, t)
        item = summary(pr, t)
        _record(item)
        emit("done", item=item, labels=[name for name, _, _ in report.labels(t)] + ([t.area] if t.area else []), applied=True)
        log.info("triaged %s -> %s (%.0f%%)", url, t.verdict, t.confidence * 100)
    except Exception as e:
        emit("failed", error=str(e)[:300])
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
    emit = BUS.emitter(url, "webhook")
    emit("received", action=payload.get("action"), title=payload["pull_request"].get("title"),
         author=payload["pull_request"].get("user", {}).get("login"))
    tasks.add_task(_triage_and_apply, url, emit)  # answer GitHub fast; the read happens right after
    return {"queued": url}

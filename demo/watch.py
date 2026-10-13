"""Watch the gate in your terminal: every stage of every PR, as it happens.

    uv run python demo/watch.py                       # local server
    uv run python demo/watch.py https://your.host     # a deployed one
"""

import json
import sys
import time

import httpx

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000").rstrip("/")
C = {"dim": "\033[2m", "b": "\033[1m", "red": "\033[31m", "grn": "\033[32m", "yel": "\033[33m",
     "blu": "\033[34m", "mag": "\033[35m", "cyn": "\033[36m", "off": "\033[0m"}
VERDICT = {"spam": "red", "needs_changes": "yel", "needs_review": "yel", "fast_track": "grn"}
started: dict[str, float] = {}


def paint(color: str, text: str) -> str:
    return f"{C[color]}{text}{C['off']}"


def describe(e: dict) -> tuple[str, str]:
    s = e["stage"]
    if s == "received":
        return "cyn", f"{e.get('title') or e['url']}  ({e['source']})"
    if s == "fetching":
        return "dim", "reading the PR from GitHub"
    if s == "facts":
        i = e.get("info") or {}
        return "dim", (f"{e['repo']}#{e['number']} by @{e['author']} · age {i.get('age_days')}d · "
                       f"{i.get('prs_24h')} PRs/24h · swarm {i.get('swarm')} · "
                       f"{'trusted' if e.get('trusted') else 'not trusted'}")
    if s == "rules_start":
        return "dim", "anti-slop's 34 rules started (in parallel)"
    if s == "read_start":
        return "dim", f"System One read started ({e.get('model')})"
    if s == "read_done":
        p = e.get("probabilities") or {}
        top = ", ".join(f"{k} {v:.2f}" for k, v in sorted(p.items(), key=lambda kv: -kv[1])[:4])
        return VERDICT.get(e["verdict"], "b"), f"read: {e['verdict']} · {top} · model {e.get('server_ms') or 0:.0f} ms"
    if s == "rules_done":
        if e.get("error"):
            return "dim", f"rules unavailable: {e['error']}"
        if e.get("result") == "skipped":
            return "dim", "rules skipped: anti-slop exempts owners, members and collaborators"
        names = ", ".join(c["name"] for c in e.get("checks") or [])
        return ("red" if e.get("failed", 0) >= 2 else "grn"), f"rules: {e.get('failed')}/{e.get('total')} failed {names}"
    if s == "fused":
        kind = f" ({e['spam_type']})" if e.get("spam_type") else ""
        return VERDICT.get(e["verdict"], "b"), paint("b", f"FINAL {e['verdict'].upper()}{kind}") + (
            "  · unsure, escalating" if e.get("uncertain") else "")
    if s == "escalated":
        return "mag", "System Two: asking an open-weight chat model for a second opinion"
    if s == "second_opinion":
        return "mag", f"second opinion: {e.get('verdict')} · {(e.get('text') or '')[:90]}"
    if s == "applying":
        return "dim", "labelling the PR and posting the scorecard"
    if s == "done":
        labels = ", ".join(e.get("labels") or []) or "none (replay: read-only)"
        return "grn", f"done · labels: {labels}"
    if s == "failed":
        return "red", f"failed: {e.get('error')}"
    return "dim", s


def show(e: dict) -> None:
    if e["stage"] == "received" or e["id"] not in started:
        started[e["id"]] = e["t"]
        print()
    ms = (e["t"] - started[e["id"]]) * 1000
    color, text = describe(e)
    clock = time.strftime("%H:%M:%S", time.localtime(e["t"]))
    print(f"{paint('dim', clock)} {ms:>7.0f} ms  {paint('b', e['stage']):<24} {paint(color, text)}", flush=True)


def main() -> None:
    print(paint("b", f"SlopGate · watching {BASE}/api/events") + paint("dim", "  (Ctrl-C to stop)"))
    while True:
        try:
            with httpx.stream("GET", f"{BASE}/api/events", timeout=None) as r:
                event = None
                for line in r.iter_lines():
                    if line.startswith("event: "):
                        event = line[7:]
                    elif line.startswith("data: "):
                        data = json.loads(line[6:])
                        if event == "hello":
                            print(paint("dim", f"connected · {len(data['backlog'])} recent events on the server"))
                        elif event == "stage":
                            show(data)
        except (httpx.HTTPError, KeyboardInterrupt) as exc:
            if isinstance(exc, KeyboardInterrupt):
                return
            print(paint("dim", f"connection lost ({exc.__class__.__name__}); retrying in 2 s"))
            time.sleep(2)


if __name__ == "__main__":
    main()

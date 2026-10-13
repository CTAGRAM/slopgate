"""Run the real anti-slop GitHub Action (peakoss/anti-slop) on any PR, safely, as a contender.

anti-slop has no dry-run: when a PR fails, it labels, comments on and closes it. So it never
gets a real token. It talks to GitHub through a local proxy that forwards GET requests with our
token and refuses every write; the writes it tries are what we record as its verdict.

    git clone --depth 1 https://github.com/peakoss/anti-slop eval/vendor/anti-slop
    uv run python -m slopgate.antislop https://github.com/OWNER/REPO/pull/N
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import yaml

from . import config
from .arena import Opinion
from .github import PullRequest

VENDOR = Path(os.environ.get("ANTISLOP_DIR", Path(__file__).resolve().parents[1] / "eval" / "vendor" / "anti-slop"))
NO_ACTIONS = {"close-pr": "false", "lock-pr": "false", "failure-pr-message": "",
              "failure-add-pr-labels": "", "failure-remove-pr-labels": "", "success-add-pr-labels": ""}


class ReadOnlyProxy:
    """GETs go to api.github.com with our token; anything else is refused and remembered."""

    def __init__(self, token: str):
        upstream = httpx.Client(base_url="https://api.github.com", timeout=30,
                                headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"})
        self.blocked: list[str] = []
        self.failures = 0  # rate limits and server errors: a run that hit any is not a fair result
        gate = threading.Semaphore(4)  # anti-slop fires requests in bursts; GitHub punishes bursts
        proxy = self

        def fetch(path: str) -> httpx.Response:
            for attempt in range(4):
                with gate:
                    r = upstream.get(path)
                limited = r.status_code == 429 or (r.status_code == 403 and "rate limit" in r.text.lower())
                if not limited:
                    break
                time.sleep(int(r.headers.get("retry-after", 30 * (attempt + 1))))
            if r.status_code == 429 or r.status_code >= 500 or (r.status_code == 403 and "rate limit" in r.text.lower()):
                proxy.failures += 1
            return r

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _reply(self, status: int, body: bytes, ctype: str = "application/json"):
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                r = fetch(self.path)
                self._reply(r.status_code, r.content, r.headers.get("content-type", "application/json"))

            def _refuse(self):
                proxy.blocked.append(f"{self.command} {self.path.split('?')[0]}")
                self._reply(403, b'{"message": "read-only evaluation proxy"}')

            do_POST = do_PATCH = do_PUT = do_DELETE = _refuse

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()


def _defaults() -> dict[str, str]:
    inputs = yaml.safe_load((VENDOR / "action.yaml").read_text())["inputs"]
    env = {f"INPUT_{k.upper()}": str(v.get("default", "")) for k, v in inputs.items()}
    env |= {f"INPUT_{k.upper()}": v for k, v in NO_ACTIONS.items()}
    env["INPUT_GITHUB-TOKEN"] = "read-only-proxy"  # never a real token
    return env


def _outputs(path: Path) -> dict[str, str]:
    """Parse a GITHUB_OUTPUT file (`key<<DELIM ... DELIM` blocks)."""
    out, lines = {}, path.read_text().splitlines()
    i = 0
    while i < len(lines):
        if "<<" in lines[i]:
            key, delim = lines[i].split("<<", 1)
            j = lines.index(delim, i + 1)
            out[key] = "\n".join(lines[i + 1:j])
            i = j
        elif "=" in lines[i]:
            k, v = lines[i].split("=", 1)
            out[k] = v
        i += 1
    return out


FAILED_CHECK = re.compile(r"^\[FAIL\] (\S+) \S (.*)$", re.M)


class AntiSlop:
    """Runs the unmodified anti-slop action on one PR and reports what its rules found."""

    def __init__(self, token: str):
        if not available():
            raise RuntimeError(f"anti-slop needs Node and a checkout in {VENDOR}")
        self.proxy = ReadOnlyProxy(token)
        self.defaults = _defaults()

    def check(self, pr: PullRequest) -> dict:
        proxy = self.proxy
        pull = httpx.get(f"{proxy.url}/repos/{pr.owner}/{pr.repo}/pulls/{pr.number}").json()
        repo = httpx.get(f"{proxy.url}/repos/{pr.owner}/{pr.repo}").json()
        before, failures_before = len(proxy.blocked), proxy.failures
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "event.json").write_text(json.dumps(
                {"action": "opened", "number": pr.number, "pull_request": pull, "repository": repo, "sender": pull["user"]}))
            (tmp / "out").touch()
            (tmp / "summary.md").touch()
            env = os.environ | self.defaults | {
                "GITHUB_API_URL": proxy.url, "GITHUB_EVENT_NAME": "pull_request_target",
                "GITHUB_EVENT_PATH": str(tmp / "event.json"), "GITHUB_REPOSITORY": f"{pr.owner}/{pr.repo}",
                "GITHUB_OUTPUT": str(tmp / "out"), "GITHUB_STEP_SUMMARY": str(tmp / "summary.md"),
                "GITHUB_ACTIONS": "false", "RUNNER_DEBUG": "0",
            }
            start = time.perf_counter()
            run = subprocess.run(["node", str(VENDOR / "dist" / "index.mjs")], env=env, capture_output=True,
                                 text=True, timeout=120)
            seconds = time.perf_counter() - start
            out = _outputs(tmp / "out")
        failures = proxy.failures - failures_before
        return {
            "result": out.get("result", "error"),
            "failed": int(out.get("failed-checks", 0) or 0), "total": int(out.get("total-checks", 0) or 0),
            "checks": [{"name": n, "why": w.strip()} for n, w in FAILED_CHECK.findall(run.stdout)],
            "blocked_writes": proxy.blocked[before:], "seconds": seconds,
            "error": "no result" if "result" not in out else f"{failures} GitHub API errors" if failures else None,
        }


def contender(token: str):
    rules = AntiSlop(token)

    def run(pr: PullRequest, state: str) -> Opinion:
        r = rules.check(pr)
        detail = (f"{r['result']}: {r['failed']}/{r['total']} checks failed" if r["total"]
                  else "skipped: the author is exempt (owner, member or collaborator)")
        if r["blocked_writes"]:
            detail += f"; would have: {', '.join(sorted({t.split()[0] for t in r['blocked_writes']}))}"
        return Opinion("anti-slop (34 rules)", "Rules", "spam" if r["result"] == "failed" else "fast_track",
                       None, r["seconds"], None, detail, r["error"],
                       extra={"failed": r["failed"], "total": r["total"], "checks": r["checks"]})
    run.label = "anti-slop (34 rules)"
    return run


def available() -> bool:
    return (VENDOR / "dist" / "index.mjs").exists() and shutil.which("node") is not None


if __name__ == "__main__":
    from .github import GitHub
    settings = config.load()
    pr = GitHub(settings.github_token).pull_request(sys.argv[1])
    print(contender(settings.github_token)(pr, ""))

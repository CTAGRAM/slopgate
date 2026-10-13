"""Run the real anti-slop GitHub Action (peakoss/anti-slop) on any PR, safely, as a contender.

anti-slop has no dry-run: when a PR fails, it labels, comments on and closes it. So it never
gets a real token. It talks to GitHub through a local proxy that forwards GET requests with our
token and refuses every write; the writes it tries are what we record as its verdict.

    git clone --depth 1 https://github.com/peakoss/anti-slop eval/vendor/anti-slop
    uv run --with pyyaml python eval/antislop.py https://github.com/OWNER/REPO/pull/N
"""

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from slopgate import config  # noqa: E402
from slopgate.arena import Opinion  # noqa: E402
from slopgate.github import PullRequest  # noqa: E402

VENDOR = Path(__file__).parent / "vendor" / "anti-slop"
NO_ACTIONS = {"close-pr": "false", "lock-pr": "false", "failure-pr-message": "",
              "failure-add-pr-labels": "", "failure-remove-pr-labels": "", "success-add-pr-labels": ""}


class ReadOnlyProxy:
    """GETs go to api.github.com with our token; anything else is refused and remembered."""

    def __init__(self, token: str):
        upstream = httpx.Client(base_url="https://api.github.com", timeout=30,
                                headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"})
        self.blocked: list[str] = []
        proxy = self

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
                r = upstream.get(self.path)
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


def contender(token: str):
    if not (VENDOR / "dist" / "index.mjs").exists():
        raise SystemExit(f"clone anti-slop first: git clone --depth 1 https://github.com/peakoss/anti-slop {VENDOR}")
    proxy = ReadOnlyProxy(token)
    defaults = _defaults()

    def run(pr: PullRequest, state: str) -> Opinion:
        pull = httpx.get(f"{proxy.url}/repos/{pr.owner}/{pr.repo}/pulls/{pr.number}").json()
        repo = httpx.get(f"{proxy.url}/repos/{pr.owner}/{pr.repo}").json()
        before = len(proxy.blocked)
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "event.json").write_text(json.dumps(
                {"action": "opened", "number": pr.number, "pull_request": pull, "repository": repo, "sender": pull["user"]}))
            (tmp / "out").touch()
            env = os.environ | defaults | {
                "GITHUB_API_URL": proxy.url, "GITHUB_EVENT_NAME": "pull_request_target",
                "GITHUB_EVENT_PATH": str(tmp / "event.json"), "GITHUB_REPOSITORY": f"{pr.owner}/{pr.repo}",
                "GITHUB_OUTPUT": str(tmp / "out"), "GITHUB_STEP_SUMMARY": str(tmp / "summary.md"),
                "GITHUB_ACTIONS": "false", "RUNNER_DEBUG": "0",
            }
            start = time.perf_counter()
            subprocess.run(["node", str(VENDOR / "dist" / "index.mjs")], env=env, capture_output=True, timeout=120)
            seconds = time.perf_counter() - start
            out = _outputs(tmp / "out")
        result = out.get("result", "error")
        tried = proxy.blocked[before:]
        detail = f"{out.get('failed-checks', '?')}/{out.get('total-checks', '?')} checks failed"
        if tried:
            detail += f"; would have: {', '.join(sorted({t.split()[0] for t in tried}))}"
        return Opinion("anti-slop (34 rules)", "Rules", "spam" if result == "failed" else "fast_track",
                       None, seconds, None, f"{result}: {detail}", None if result != "error" else "no result")
    run.label = "anti-slop (34 rules)"
    return run


if __name__ == "__main__":
    from slopgate.github import GitHub
    settings = config.load()
    pr = GitHub(settings.github_token).pull_request(sys.argv[1])
    print(contender(settings.github_token)(pr, ""))

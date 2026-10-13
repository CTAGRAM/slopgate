"""Deploy SlopGate to a Hugging Face Space (Docker, free CPU tier, no card needed).

    uv run --with huggingface_hub python deploy/hf_space.py

Reads HF_TOKEN, CODIV_API_KEY, DEPLOY_GITHUB_TOKEN and GITHUB_WEBHOOK_SECRET from .env.local and stores
them as Space secrets; nothing secret is uploaded as a file.
"""

import shutil
import sys
import tempfile
from pathlib import Path

from huggingface_hub import HfApi

ROOT = Path(__file__).resolve().parents[1]
SPACE_README = """---
title: SlopGate
emoji: 🛡️
colorFrom: green
colorTo: gray
sdk: docker
app_port: 8080
pinned: false
license: mit
short_description: Open-weight gatekeeper that triages pull requests
---

# SlopGate

An open-weight gatekeeper that triages every pull request: spam, AI slop, prompt injection and risky
changes, read by OpenJev and fused with anti-slop's 34 rules. Source, evaluation and docs:
https://github.com/CTAGRAM/slopgate
"""


def env() -> dict[str, str]:
    out = {}
    for line in (ROOT / ".env.local").read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def main() -> None:
    e = env()
    missing = [k for k in ("HF_TOKEN", "CODIV_API_KEY", "DEPLOY_GITHUB_TOKEN", "GITHUB_WEBHOOK_SECRET") if not e.get(k)]
    if missing:
        sys.exit(f"add to .env.local first: {', '.join(missing)}")
    api = HfApi(token=e["HF_TOKEN"])
    repo_id = f"{api.whoami()['name']}/slopgate"
    api.create_repo(repo_id, repo_type="space", space_sdk="docker", exist_ok=True)

    secrets = {"CODIV_API_KEY": e["CODIV_API_KEY"], "GITHUB_TOKEN": e["DEPLOY_GITHUB_TOKEN"],
               "GITHUB_WEBHOOK_SECRET": e["GITHUB_WEBHOOK_SECRET"]}
    for key, value in secrets.items():
        api.add_space_secret(repo_id, key, value)
    for key, value in {"SLOPGATE_JUDGE_ALL_AUTHORS": e.get("SLOPGATE_JUDGE_ALL_AUTHORS", "1"),
                       "SLOPGATE_HOST_LABEL": "Hugging Face Space"}.items():
        api.add_space_variable(repo_id, key, value)

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        for name in ("pyproject.toml", "uv.lock", "LICENSE", "Dockerfile"):
            shutil.copy(ROOT / name, tmp / name)
        shutil.copytree(ROOT / "slopgate", tmp / "slopgate", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(ROOT / "eval" / "results", tmp / "eval" / "results", ignore=shutil.ignore_patterns("*.old.jsonl"))
        (tmp / "README.md").write_text(SPACE_README)
        api.upload_folder(folder_path=tmp, repo_id=repo_id, repo_type="space", commit_message="Deploy SlopGate")

    host = repo_id.replace("/", "-").replace("_", "-").lower()
    print(f"Space:   https://huggingface.co/spaces/{repo_id}")
    print(f"App:     https://{host}.hf.space")
    print(f"Webhook: https://{host}.hf.space/webhook")


if __name__ == "__main__":
    main()

"""Settings from the environment, with .env.local / .env as fallbacks for local runs."""

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def _github_token() -> str | None:
    if token := os.environ.get("GITHUB_TOKEN"):
        return token
    try:  # local dev: reuse the GitHub CLI login
        out = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, check=True)
        return out.stdout.strip() or None
    except (OSError, subprocess.CalledProcessError):
        return None


@dataclass(frozen=True)
class Settings:
    openjev_url: str
    openjev_key: str | None
    model: str
    github_token: str | None
    webhook_secret: str | None
    gradient_url: str
    gradient_key: str | None
    gradient_model: str | None
    judge_all_authors: bool  # like CodeRabbit's include_all_authors: also judge trusted authors for spam


def load() -> Settings:
    for name in (".env.local", ".env"):
        _load_env_file(Path.cwd() / name)
    env = os.environ.get
    return Settings(
        openjev_url=env("OPENJEV_BASE_URL", "https://api.codiv.ai").rstrip("/"),
        openjev_key=env("OPENJEV_API_KEY") or env("CODIV_API_KEY"),
        model=env("SLOPGATE_MODEL", "openjev-latest"),
        github_token=_github_token(),
        webhook_secret=env("GITHUB_WEBHOOK_SECRET"),
        gradient_url=env("GRADIENT_BASE_URL", "https://inference.do-ai.run/v1").rstrip("/"),
        gradient_key=env("GRADIENT_API_KEY"),
        gradient_model=env("GRADIENT_MODEL"),
        judge_all_authors=env("SLOPGATE_JUDGE_ALL_AUTHORS", "").lower() in ("1", "true", "yes"),
    )

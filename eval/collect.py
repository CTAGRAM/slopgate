"""Build the evaluation set: PRs maintainers labelled spam, and PRs merged in the same repos.

Pairing each repo's spam with that repo's own merged PRs keeps the test honest: the model
cannot win by telling docs repos from code repos. Bots and deleted accounts are skipped, since
a deleted account would leak the answer.

    uv run python eval/collect.py --per-class 60
"""

import argparse
import dataclasses
import json
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from slopgate import config  # noqa: E402
from slopgate.github import GitHub  # noqa: E402

OUT = Path(__file__).parent / "data" / "prs.jsonl"
SEARCH_PAUSE = 2.2  # the search API allows 30 requests a minute


def search(gh: GitHub, q: str, pages: int = 1) -> list[dict]:
    items = []
    for page in range(1, pages + 1):
        time.sleep(SEARCH_PAUSE)
        items += gh._get("/search/issues", q=q, per_page=100, page=page)["items"]
    return items


def human(item: dict) -> bool:
    user = item.get("user") or {}
    return user.get("type") == "User" and user.get("login") != "ghost"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-class", type=int, default=60)
    ap.add_argument("--per-repo", type=int, default=3)
    ap.add_argument("--since", default="2025-01-01")
    args = ap.parse_args()
    gh = GitHub(config.load().github_token)

    spam, per_repo = [], Counter()
    for item in search(gh, f"is:pr label:spam created:>={args.since}", pages=5):
        repo = item["repository_url"].split("/repos/")[1]
        if human(item) and per_repo[repo] < args.per_repo:
            spam.append((item["html_url"], repo))
            per_repo[repo] += 1
        if len(spam) >= args.per_class:
            break

    merged = []
    for repo, n in per_repo.items():
        for item in search(gh, f"repo:{repo} is:pr is:merged -label:spam created:>={args.since}"):
            if human(item) and n > 0:
                merged.append((item["html_url"], repo))
                n -= 1
        if len(merged) >= args.per_class:
            break

    OUT.parent.mkdir(parents=True, exist_ok=True)
    done = {json.loads(l)["url"] for l in OUT.read_text().splitlines()} if OUT.exists() else set()
    with OUT.open("a") as f:
        for label, rows in (("spam", spam), ("merged", merged)):
            for url, repo in rows:
                if url in done:
                    continue
                try:
                    time.sleep(SEARCH_PAUSE)  # pull_request() makes one search call
                    pr = gh.pull_request(url)
                except Exception as e:  # noqa: BLE001 - skip unreadable PRs, keep going
                    print(f"skip {url}: {e}", file=sys.stderr)
                    continue
                if pr.account_created_at is None:
                    continue  # deleted account: would leak the label
                row = dataclasses.asdict(pr) | {"label": label}
                f.write(json.dumps(row, default=str) + "\n")
                f.flush()
                print(f"{label:6} {url}")
    print(f"spam={len(spam)} merged={len(merged)} repos={len(per_repo)} -> {OUT}")


if __name__ == "__main__":
    main()

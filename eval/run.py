"""Every contender on every PR in eval/data/<set>.jsonl, then eval/results/<set>.md and .json.

Each contender's answers go to their own file, so contenders run (and resume) independently:

    uv run python eval/run.py --skip anti-slop      # the fast contenders first
    uv run python eval/run.py --only anti-slop      # anti-slop is slow: ~50 GitHub calls per PR
    uv run python eval/run.py --report              # just rebuild the tables

SlopGate's questions and verdict rules were written before this dataset was collected.
"""

import argparse
import dataclasses
import json
import re
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from slopgate import config  # noqa: E402
from slopgate.arena import contenders, run_safely  # noqa: E402
from slopgate.github import GitHub, PullRequest  # noqa: E402
from slopgate.judge import TRUSTED, build_state  # noqa: E402

DATA = Path(__file__).parent / "data"
RESULTS = Path(__file__).parent / "results"
GAP = 3.2  # seconds per PR: up to three Codiv calls each, and Codiv allows 60 a minute


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def load(name: str) -> list[tuple[PullRequest, str]]:
    rows = []
    for line in (DATA / f"{name}.jsonl").read_text().splitlines():
        d = json.loads(line)
        label = d.pop("label")
        for k in ("created_at", "account_created_at"):
            d[k] = datetime.fromisoformat(d[k]) if d[k] else None
        rows.append((PullRequest(**d), label))
    return rows


def answers(folder: Path, name: str) -> dict[str, dict]:
    path = folder / f"{slug(name)}.jsonl"
    if not path.exists():
        return {}
    return {(r := json.loads(l))["url"]: r for l in path.read_text().splitlines()}


def when(sec: float | None) -> str:
    if sec is None:
        return "-"
    return f"{sec * 1000:.0f} ms" if sec < 1 else f"{sec:.1f} s" if sec < 120 else f"{sec / 60:.1f} min"


def score(name: str, rows: list[dict]) -> dict:
    judged = [r for r in rows if r["opinion"]["verdict"] and not r["opinion"]["error"]]
    tp = sum(r["label"] == "spam" and r["opinion"]["verdict"] == "spam" for r in judged)
    fp = sum(r["label"] != "spam" and r["opinion"]["verdict"] == "spam" for r in judged)
    fn = sum(r["label"] == "spam" and r["opinion"]["verdict"] != "spam" for r in judged)
    n_merged = sum(r["label"] != "spam" for r in judged)
    n_spam = sum(r["label"] == "spam" for r in judged)
    waved = sum(r["label"] == "spam" and r["opinion"]["verdict"] == "fast_track" for r in judged)
    observed = bool(rows) and rows[0]["opinion"]["kind"] == "Observed"  # CodeRabbit has no fast-track
    times = [r["opinion"]["seconds"] for r in judged if r["opinion"]["seconds"] is not None]
    model = [r["opinion"]["model_seconds"] for r in judged if r["opinion"].get("model_seconds")]
    tokens = [r["opinion"]["tokens"] for r in judged if r["opinion"]["tokens"]]
    return {
        "name": name, "kind": rows[0]["opinion"]["kind"] if rows else "?",
        "judged": len(judged), "total": len(rows),
        "precision": tp / (tp + fp) if tp + fp else None,
        "recall": tp / (tp + fn) if tp + fn else None,
        "fpr": fp / n_merged if n_merged else None,
        "waved": None if observed or not n_spam else waved / n_spam,
        "median": statistics.median(times) if times else None,
        "median_model": statistics.median(model) if model else None,
        "tokens": statistics.mean(tokens) if tokens else None,
    }


def table(title: str, names: list[str], folder: Path, data) -> tuple[list[str], list[dict]]:
    urls = {pr.url for pr, _ in data}
    n_spam = sum(label == "spam" for _, label in data)
    scores = [score(n, [r for r in answers(folder, n).values() if r["url"] in urls]) for n in names]
    scores = [s for s in scores if s["total"]]
    pct = lambda v: "-" if v is None else f"{v:.0%}"
    lines = [
        f"**{title}: {len(data)} real pull requests from {len({(p.owner, p.repo) for p, _ in data})} repositories**, "
        f"{n_spam} that maintainers labelled `spam` and {len(data) - n_spam} merged PRs from the same repositories.",
        "",
        "| Contender | Kind | Judged | Spam caught (recall) | Precision | Spam fast-tracked | False alarms on merged PRs | Median time | Model time | Tokens / PR |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for s in scores:
        tokens = "-" if s["tokens"] is None else f"{s['tokens']:.0f}"
        lines.append(f"| {s['name']} | {s['kind']} | {s['judged']}/{s['total']} | {pct(s['recall'])} | "
                     f"{pct(s['precision'])} | {pct(s['waved'])} | {pct(s['fpr'])} | {when(s['median'])} | "
                     f"{when(s['median_model'])} | {tokens} |")
    return lines, scores


def report(set_name: str, names: list[str], data) -> None:
    folder = RESULTS / set_name
    # Outside contributors: the people spam actually comes from, and the only ones CodeRabbit's slop
    # detection (and SlopGate, by default) judge. Owners' "spam" PRs in this data are forks running
    # upstream's labelling automation on their own PRs, not a maintainer's judgement.
    outside = [(pr, label) for pr, label in data if pr.author_association not in TRUSTED]
    top, scores = table("Outside contributors", names, folder, outside)
    everyone, _ = table("Everyone", names, folder, data)
    lines = top + ["", *everyone]
    (RESULTS / f"{set_name}.md").write_text("\n".join(lines) + "\n")
    (RESULTS / f"{set_name}.urls.tsv").write_text("".join(f"{label}\t{pr.url}\n" for pr, label in data))
    n_spam = sum(label == "spam" for _, label in outside)
    (RESULTS / f"{set_name}.json").write_text(json.dumps(
        {"n": len(outside), "spam": n_spam, "population": "outside contributors", "contenders": scores}, indent=2))
    print("\n".join(lines))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", default="prs", help="eval/data/<set>.jsonl")
    ap.add_argument("--only", nargs="*", default=[], help="run just these contenders (name prefixes)")
    ap.add_argument("--skip", nargs="*", default=[], help="leave these contenders out (name prefixes)")
    ap.add_argument("--report", action="store_true", help="only rebuild the tables")
    args = ap.parse_args()

    # like-for-like with CodeRabbit's default: trusted authors are never judged for spam
    settings = dataclasses.replace(config.load(), judge_all_authors=False)
    gh = GitHub(settings.github_token)
    every = contenders(settings, gh)
    names = [c.label for c in every]
    match = lambda c, prefixes: any(slug(c.label).startswith(slug(p)) for p in prefixes)
    field = [c for c in every if (not args.only or match(c, args.only)) and not match(c, args.skip)]

    data = load(args.set)
    folder = RESULTS / args.set
    folder.mkdir(parents=True, exist_ok=True)
    if not args.report:
        for pr, _ in data:  # rows saved before SlopGate read CONTRIBUTING guides and looked for swarms
            if not pr.contributing:
                pr.contributing = gh.contributing(pr.owner, pr.repo)
            if not pr.pr_template:
                pr.pr_template = gh.pr_template(pr.owner, pr.repo)
            if pr.similar_recent is None and any(getattr(c, "kind_hint", None) == "System One" for c in field):
                time.sleep(2.1)  # one search call each; the search API allows 30 a minute
                gh.swarm(pr)
        done = {c.label: answers(folder, c.label) for c in field}
        for i, (pr, label) in enumerate(data, 1):
            todo = [c for c in field if pr.url not in done[c.label]]
            if not todo:
                continue
            start, state = time.monotonic(), build_state(pr)
            with ThreadPoolExecutor(len(todo)) as pool:
                opinions = list(pool.map(lambda c: run_safely(c, pr, state), todo))
            for c, o in zip(todo, opinions):
                with (folder / f"{slug(c.label)}.jsonl").open("a") as f:
                    f.write(json.dumps({"url": pr.url, "label": label, "opinion": dataclasses.asdict(o)}) + "\n")
            print(f"[{i}/{len(data)}] {label:6} " + "  ".join(f"{slug(o.contender)}={o.verdict}" for o in opinions), flush=True)
            time.sleep(max(0.0, GAP - (time.monotonic() - start)))
    report(args.set, names, data)


if __name__ == "__main__":
    main()

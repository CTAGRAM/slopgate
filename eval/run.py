"""Every contender on every PR in eval/data/<set>.jsonl, then eval/results/<set>.md.

    uv run --with pyyaml python eval/run.py                 # all contenders
    uv run --with pyyaml python eval/run.py --skip anti-slop

SlopGate's questions and verdict rules were written before this dataset was collected.
"""

import argparse
import dataclasses
import json
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from slopgate import config  # noqa: E402
from slopgate.arena import compare, contenders  # noqa: E402
from slopgate.github import GitHub, PullRequest  # noqa: E402
from slopgate.judge import build_state  # noqa: E402

DATA = Path(__file__).parent / "data"
RESULTS = Path(__file__).parent / "results"
GAP = 3.2  # seconds per PR: three Codiv calls each, and Codiv allows 60 a minute


def load(name: str) -> list[tuple[PullRequest, str]]:
    rows = []
    for line in (DATA / f"{name}.jsonl").read_text().splitlines():
        d = json.loads(line)
        label = d.pop("label")
        for k in ("created_at", "account_created_at"):
            d[k] = datetime.fromisoformat(d[k]) if d[k] else None
        rows.append((PullRequest(**d), label))
    return rows


def when(sec: float | None) -> str:
    if sec is None:
        return "-"
    return f"{sec * 1000:.0f} ms" if sec < 1 else f"{sec:.1f} s" if sec < 120 else f"{sec / 60:.1f} min"


def score(name: str, rows: list[dict]) -> dict:
    mine = [(r["label"], o) for r in rows for o in r["opinions"] if o["contender"] == name]
    judged = [(label, o) for label, o in mine if o["verdict"] and not o["error"]]
    tp = sum(l == "spam" and o["verdict"] == "spam" for l, o in judged)
    fp = sum(l != "spam" and o["verdict"] == "spam" for l, o in judged)
    fn = sum(l == "spam" and o["verdict"] != "spam" for l, o in judged)
    n_merged = sum(l != "spam" for l, _ in judged)
    times = [o["seconds"] for _, o in judged if o["seconds"] is not None]
    tokens = [o["tokens"] for _, o in judged if o["tokens"]]
    return {
        "name": name, "kind": next((o["kind"] for _, o in mine), "?"),
        "coverage": f"{len(judged)}/{len(mine)}",
        "precision": tp / (tp + fp) if tp + fp else None,
        "recall": tp / (tp + fn) if tp + fn else None,
        "fpr": fp / n_merged if n_merged else None,
        "median": statistics.median(times) if times else None,
        "tokens": statistics.mean(tokens) if tokens else None,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", default="prs", help="eval/data/<set>.jsonl")
    ap.add_argument("--skip", nargs="*", default=[], help="contenders to leave out, by name prefix")
    args = ap.parse_args()

    settings = config.load()
    gh = GitHub(settings.github_token)
    field = contenders(settings, gh)
    if not any("anti-slop".startswith(s) for s in args.skip):
        import antislop
        field.append(antislop.contender(settings.github_token))
    field = [c for c in field if not any(c.label.lower().startswith(s.lower()) for s in args.skip)]

    data = load(args.set)
    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"{args.set}.jsonl"
    done = {json.loads(l)["url"]: json.loads(l) for l in out.read_text().splitlines()} if out.exists() else {}
    rows = []
    with out.open("a") as f:
        for i, (pr, label) in enumerate(data, 1):
            if pr.url in done:
                rows.append(done[pr.url])
                continue
            start = time.monotonic()
            opinions = compare(pr, build_state(pr), field)
            row = {"url": pr.url, "label": label, "opinions": [dataclasses.asdict(o) for o in opinions]}
            f.write(json.dumps(row) + "\n")
            f.flush()
            rows.append(row)
            print(f"[{i}/{len(data)}] {label:6} " + "  ".join(f"{o.contender.split(' ')[-1]}={o.verdict}" for o in opinions))
            time.sleep(max(0.0, GAP - (time.monotonic() - start)))

    n_spam = sum(r["label"] == "spam" for r in rows)
    pct = lambda v: "-" if v is None else f"{v:.0%}"
    lines = [
        f"**{len(rows)} real pull requests**: {n_spam} that maintainers labelled `spam`, and "
        f"{len(rows) - n_spam} merged PRs from the same repositories.",
        "",
        "| Contender | Kind | Judged | Precision | Recall | False alarms on merged PRs | Median time | Tokens / PR |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for c in field:
        s = score(c.label, rows)
        tokens = "-" if s["tokens"] is None else f"{s['tokens']:.0f}"
        lines.append(f"| {s['name']} | {s['kind']} | {s['coverage']} | {pct(s['precision'])} | {pct(s['recall'])} | "
                     f"{pct(s['fpr'])} | {when(s['median'])} | {tokens} |")
    (RESULTS / f"{args.set}.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()

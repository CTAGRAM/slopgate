"""Score SlopGate on eval/data/prs.jsonl and write eval/results/summary.md.

    uv run python eval/run.py --models openjev-latest clef-flash-1.0
"""

import argparse
import json
import statistics
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from slopgate import config  # noqa: E402
from slopgate.github import PullRequest  # noqa: E402
from slopgate.judge import judge  # noqa: E402
from slopgate.openjev import OpenJev  # noqa: E402

DATA = Path(__file__).parent / "data" / "prs.jsonl"
RESULTS = Path(__file__).parent / "results"
MIN_GAP = 1.05  # seconds between request starts: Codiv allows 60 a minute per key

_lock, _last = threading.Lock(), [0.0]


def throttle() -> None:
    with _lock:
        wait = _last[0] + MIN_GAP - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.monotonic()


def load() -> list[tuple[PullRequest, str]]:
    rows = []
    for line in DATA.read_text().splitlines():
        d = json.loads(line)
        label = d.pop("label")
        for k in ("created_at", "account_created_at"):
            d[k] = datetime.fromisoformat(d[k]) if d[k] else None
        rows.append((PullRequest(**d), label))
    return rows


def auc(pos: list[float], neg: list[float]) -> float:
    """Probability a random spam PR scores higher than a random merged one."""
    wins = sum(1.0 if p > n else 0.5 if p == n else 0.0 for p in pos for n in neg)
    return wins / (len(pos) * len(neg))


def evaluate(model_id: str, rows) -> dict:
    s = config.load()
    model = OpenJev(s.openjev_url, s.openjev_key, model_id)

    def one(item):
        pr, label = item
        throttle()
        try:
            _, t = judge(pr, model)
        except Exception as e:  # noqa: BLE001
            return {"url": pr.url, "label": label, "error": str(e)}
        return {"url": pr.url, "label": label, "verdict": t.verdict, "p_spam": t.probabilities["spam"],
                "p_slop": t.probabilities["ai_slop"], "confidence": t.confidence,
                "server_ms": t.reading.server_ms, "tokens": t.reading.input_tokens}

    with ThreadPoolExecutor(4) as pool:
        out = list(pool.map(one, rows))
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / f"{model_id}.jsonl").write_text("\n".join(json.dumps(r) for r in out) + "\n")

    ok = [r for r in out if "error" not in r]
    tp = sum(r["label"] == "spam" and r["verdict"] == "spam" for r in ok)
    fp = sum(r["label"] != "spam" and r["verdict"] == "spam" for r in ok)
    fn = sum(r["label"] == "spam" and r["verdict"] != "spam" for r in ok)
    merged = sum(r["label"] != "spam" for r in ok)
    lat = sorted(r["server_ms"] for r in ok if r["server_ms"])
    return {
        "model": model_id, "n": len(ok), "errors": len(out) - len(ok),
        "precision": tp / (tp + fp) if tp + fp else 0.0,
        "recall": tp / (tp + fn) if tp + fn else 0.0,
        "false_positive_rate": fp / merged if merged else 0.0,
        "auc": auc([r["p_spam"] for r in ok if r["label"] == "spam"],
                   [r["p_spam"] for r in ok if r["label"] != "spam"]),
        "p50_ms": statistics.median(lat) if lat else None,
        "p95_ms": lat[int(0.95 * (len(lat) - 1))] if lat else None,
        "tokens_per_pr": statistics.mean(r["tokens"] for r in ok) if ok else 0,
        "false_positives": [r["url"] for r in ok if r["label"] != "spam" and r["verdict"] == "spam"],
        "missed": [r["url"] for r in ok if r["label"] == "spam" and r["verdict"] != "spam"],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="+", default=["openjev-latest"])
    args = ap.parse_args()
    rows = load()
    n_spam = sum(label == "spam" for _, label in rows)
    print(f"{len(rows)} PRs: {n_spam} labelled spam, {len(rows) - n_spam} merged")

    results = [evaluate(m, rows) for m in args.models]
    lines = [
        f"Evaluated on {len(rows)} real pull requests: {n_spam} that maintainers labelled `spam`, "
        f"and {len(rows) - n_spam} merged PRs from the same repositories.",
        "",
        "| Model | Precision | Recall | False alarms on merged PRs | AUC | p50 | p95 | Tokens / PR |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        lines.append(f"| `{r['model']}` | {r['precision']:.0%} | {r['recall']:.0%} | {r['false_positive_rate']:.0%} | "
                     f"{r['auc']:.2f} | {r['p50_ms']:.0f} ms | {r['p95_ms']:.0f} ms | {r['tokens_per_pr']:.0f} |")
    for r in results:
        lines += ["", f"**{r['model']}**: {r['errors']} errors.",
                  "False positives: " + (", ".join(r["false_positives"]) or "none"),
                  "", "Missed spam: " + (", ".join(r["missed"]) or "none")]
    (RESULTS / "summary.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()

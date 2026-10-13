"""Everything the dashboard shows about the evaluation, computed from eval/results, into one JSON file.

    uv run python eval/dashboard.py        # writes eval/results/dashboard.json

The server only serves that file, so a deployment needs no PR snapshots (eval/data stays local).
"""

import json
import re
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run import RESULTS, answers, score  # noqa: E402

DATA = Path(__file__).parent / "data"
CONTENDERS = ["SlopGate · OpenJev", "SlopGate · Clef-flash", "DiffusionGemma 26B as chat", "CodeRabbit", "anti-slop (34 rules)"]
VERDICTS = ["spam", "needs_review", "needs_changes", "fast_track"]
SETS = {"main": "prs", "heldout": "coderabbit"}


def auc(rows: list[dict]) -> float | None:
    pos = [r["opinion"]["p_spam"] for r in rows if r["label"] == "spam" and r["opinion"]["p_spam"] is not None]
    neg = [r["opinion"]["p_spam"] for r in rows if r["label"] != "spam" and r["opinion"]["p_spam"] is not None]
    if not pos or not neg:
        return None
    return sum(1.0 if p > n else 0.5 if p == n else 0.0 for p in pos for n in neg) / (len(pos) * len(neg))


def detail_bits(detail: str) -> tuple[float | None, list[str], str | None]:
    """System One opinions carry 'NN% confident, flags: a, b, type: x' in their detail."""
    conf = re.match(r"(\d+)% confident", detail or "")
    flags = re.search(r"flags: ([a-z_, ]+?)(?:, type:|$)", detail or "")
    kind = re.search(r"type: ([a-z-]+)", detail or "")
    return (int(conf.group(1)) / 100 if conf else None,
            [f.strip() for f in flags.group(1).split(",")] if flags else [],
            kind.group(1) if kind else None)


def contender_block(name: str, rows: list[dict], n: int) -> dict:
    s = score(name, rows) | {"total": n}  # coverage is out of the whole set, even mid-run
    judged = [r for r in rows if r["opinion"]["verdict"] and not r["opinion"]["error"]]
    walls = sorted(r["opinion"]["seconds"] for r in judged if r["opinion"]["seconds"] is not None)
    fp = sum(r["label"] != "spam" and r["opinion"]["verdict"] == "spam" for r in judged)
    merged = sum(r["label"] != "spam" for r in judged)
    cm = [[sum(r["label"] == lab and r["opinion"]["verdict"] == v for r in judged) for v in VERDICTS]
          for lab in ("spam", "merged")]
    return s | {
        "auc": auc(judged), "p95": walls[int(0.95 * (len(walls) - 1))] if walls else None,
        "false_alarms": f"{fp} / {merged}" if merged else "-", "cm": cm,
    }


def openjev_details(rows: list[dict]) -> dict:
    judged = [r for r in rows if r["opinion"]["verdict"] and not r["opinion"]["error"]]
    p = [(r["opinion"]["p_spam"], r["label"]) for r in judged if r["opinion"]["p_spam"] is not None]
    hist = [{"spam": 0, "merged": 0} for _ in range(10)]
    for prob, label in p:
        hist[min(9, int(prob * 10))]["spam" if label == "spam" else "merged"] += 1
    bins = defaultdict(list)
    for prob, label in p:
        bins[min(9, int(prob * 10))].append((prob, label == "spam"))
    calib = [{"bin": b, "predicted": statistics.mean(x for x, _ in v), "observed": sum(y for _, y in v) / len(v), "n": len(v)}
             for b, v in sorted(bins.items())]
    ece = sum(c["n"] * abs(c["predicted"] - c["observed"]) for c in calib) / max(1, len(p))
    flags, uncertain, kinds = Counter(), 0, Counter()
    for r in judged:
        conf, fl, kind = detail_bits(r["opinion"]["detail"])
        flags.update(fl)
        kinds[kind] += bool(kind)
        if conf is not None and (conf < 0.5 or 0.35 <= (r["opinion"]["p_spam"] or 0) < 0.8):
            uncertain += 1
    model = sorted(r["opinion"]["model_seconds"] * 1000 for r in judged if r["opinion"].get("model_seconds"))
    edges = [50, 100, 150, 200, 300]
    lat = [0] * (len(edges) + 1)
    for ms in model:
        lat[sum(ms >= e for e in edges)] += 1
    return {
        "verdicts": Counter(r["opinion"]["verdict"] for r in judged),
        "hist": hist, "calibration": calib, "ece": ece, "points": p,
        "flags": flags, "spam_types": {k: v for k, v in kinds.items() if k},
        "escalated": uncertain / max(1, len(judged)),
        "latency": {"bins": lat, "labels": ["<50", "50-100", "100-150", "150-200", "200-300", "300+"],
                    "median": statistics.median(model) if model else None,
                    "p95": model[int(0.95 * (len(model) - 1))] if model else None},
    }


def repos_table(oj_rows: list[dict]) -> list[dict]:
    by = defaultdict(list)
    for r in oj_rows:
        by["/".join(r["url"].split("/")[3:5])].append(r)
    out = []
    for repo, rows in sorted(by.items(), key=lambda kv: -len(kv[1])):
        flags = Counter(f for r in rows for f in detail_bits(r["opinion"]["detail"])[1])
        out.append({"repo": repo, "n": len(rows),
                    "labelled_spam": sum(r["label"] == "spam" for r in rows) / len(rows),
                    "called_spam": sum(r["opinion"]["verdict"] == "spam" for r in rows) / len(rows),
                    "review": sum(r["opinion"]["verdict"] in ("needs_review", "needs_changes") for r in rows) / len(rows),
                    "top_flag": flags.most_common(1)[0][0] if flags else None})
    return out


def monthly(set_file: str) -> dict:
    path = DATA / f"{set_file}.jsonl"
    if not path.exists():
        return {}
    c = defaultdict(Counter)
    for line in path.read_text().splitlines():
        d = json.loads(line)
        c[d["created_at"][:7]][d["label"]] += 1
    months = sorted(c)
    return {"months": months, "spam": [c[m]["spam"] for m in months], "merged": [c[m]["merged"] for m in months]}


def swarm_example() -> list[dict]:
    """The scrapy swarm from the README, with real authors and titles."""
    path = DATA / "prs.jsonl"
    if not path.exists():
        return []
    rows = {json.loads(l)["number"]: json.loads(l) for l in path.read_text().splitlines()
            if '"repo": "scrapy"' in l}
    return [{"number": n, "author": rows[n]["author"], "title": rows[n]["title"], "created_at": rows[n]["created_at"]}
            for n in (8307, 8308, 8309) if n in rows]


def history() -> list[dict]:
    out = []
    for version, folder in (("v1", "prs-v1"), ("v2", "prs-v2"), ("v3", "prs")):
        rows = list(answers(RESULTS / folder, CONTENDERS[0]).values())
        if rows:
            s = score(CONTENDERS[0], rows)
            out.append({"version": version, "recall": s["recall"], "precision": s["precision"], "fpr": s["fpr"]})
    return out


def main() -> None:
    out = {"sets": {}, "history": history(), "swarm": swarm_example()}
    for key, set_file in SETS.items():
        folder = RESULTS / set_file
        blocks = {}
        oj = list(answers(folder, CONTENDERS[0]).values())
        for name in CONTENDERS:
            rows = list(answers(folder, name).values())
            if rows:
                blocks[name] = contender_block(name, rows, len(oj))
        labels = {r["url"]: r["label"] for r in oj}
        out["sets"][key] = {
            "n": len(labels), "spam": sum(l == "spam" for l in labels.values()),
            "repos": len({"/".join(u.split("/")[3:5]) for u in labels}),
            "contenders": blocks, "openjev": openjev_details(oj),
            "repo_table": repos_table(oj), "monthly": monthly(set_file),
        }
    target = RESULTS / "dashboard.json"
    target.write_text(json.dumps(out, indent=1, default=float))
    print(f"wrote {target} ({target.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()

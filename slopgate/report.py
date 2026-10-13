"""The maintainer-facing comment and labels for a triage."""

from .judge import SIGNALS, Triage

LABEL_PREFIX = "slopgate:"
VERDICT_LABELS = {  # verdict -> (label, colour, description)
    "fast_track": ("slopgate:fast-track", "0E8A16", "SlopGate: clear and ready for review"),
    "needs_review": ("slopgate:needs-review", "FBCA04", "SlopGate: needs a careful human look"),
    "needs_changes": ("slopgate:needs-changes", "D93F0B", "SlopGate: genuine but incomplete"),
    "spam": ("slopgate:spam", "B60205", "SlopGate: spam or zero-value change"),
}
FLAG_LABELS = {
    "injection": ("slopgate:prompt-injection", "5319E7", "SlopGate: text aimed at AI reviewers"),
    "risky": ("slopgate:risky-files", "1D76DB", "SlopGate: touches CI, dependencies or scripts"),
}
EFFORT = ["none", "minimal", "some", "substantial"]


def labels(t: Triage) -> list[tuple[str, str, str]]:
    out = [VERDICT_LABELS[t.verdict]] + [FLAG_LABELS[f] for f in t.flags if f in FLAG_LABELS]
    return out


def _bar(p: float) -> str:
    filled = round(p * 10)
    return "█" * filled + "░" * (10 - filled)


def comment(t: Triage, linked_issue: int | None = None) -> str:
    title = t.verdict.replace("_", " ").upper()
    rows = [f"| {name} | `{_bar(t.probabilities[key])}` {t.probabilities[key]:.0%} |"
            for key, (_, name) in SIGNALS.items()]
    if "matches_issue" in t.probabilities:
        p = t.probabilities["matches_issue"]
        rows.append(f"| Does what issue #{linked_issue} asks | `{_bar(p)}` {p:.0%} |")
    if "follows_rules" in t.probabilities:
        p = t.probabilities["follows_rules"]
        rows.append(f"| Follows this repo's CONTRIBUTING rules | `{_bar(p)}` {p:.0%} |")
    if t.rules and not t.rules.get("error"):
        names = ", ".join(f"`{c['name']}`" for c in t.rules["checks"]) or "none"
        rows.append(f"| anti-slop rule checks failed | {t.rules['failed']} of {t.rules['total']}: {names} |")
    rows.append(f"| Effort shown | {EFFORT[min(3, round(t.effort))]} ({t.effort:.1f} / 3) |")
    if t.area:
        rows.append(f"| Area | `{t.area}` |")

    kind = f" ({t.spam_type.replace('_', '-')})" if t.spam_type else ""
    why = (f"{t.rules['failed']} anti-slop rule checks failed" if "rules" in t.flags
           else f"{t.confidence:.0%} confident")
    parts = [
        f"**SlopGate: `{title}`**{kind} · {why}",
        "",
        "| Signal | Probability |",
        "|---|---|",
        *rows,
    ]
    if t.notes:
        parts += [""] + [f"- {n}" for n in t.notes]
    if t.second_opinion:
        parts += ["", "**Second opinion** (open-weight LLM, asked because the fast reading was unsure):",
                  "", *[f"> {line}" for line in t.second_opinion.splitlines()]]
    r = t.reading
    speed = f"{r.server_ms:.0f} ms" if r.server_ms else f"{r.wall_ms:.0f} ms"
    parts += ["", f"<sub>Advisory only: a maintainer makes the final call. Read by `{r.model}` "
                  f"(open weights) in {speed}, {r.input_tokens:,} tokens.</sub>"]
    return "\n".join(parts)

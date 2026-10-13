"""Fetch -> read -> escalate if unsure -> label and comment. Shared by the CLI and the server."""

from concurrent.futures import ThreadPoolExecutor

from . import antislop, report
from .config import Settings
from .escalate import second_opinion
from .github import GitHub, PullRequest
from .judge import Triage, apply_rules, classify_spam, is_trusted, judge
from .openjev import OpenJev


class SlopGate:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.github = GitHub(settings.github_token)
        self.model = OpenJev(settings.openjev_url, settings.openjev_key, settings.model)
        self.rules = antislop.AntiSlop(settings.github_token) if antislop.available() else None
        self._pool = ThreadPoolExecutor(4)

    def triage(self, url: str, escalate: bool = True) -> tuple[PullRequest, Triage]:
        pr = self.github.pull_request(url)
        # anti-slop's rules run alongside the model read, so they add little to the wait
        rules = self._pool.submit(self.rules.check, pr) if self.rules else None
        state, t = judge(pr, self.model, self.settings.judge_all_authors)
        try:
            checked = rules.result(timeout=120) if rules else None
        except Exception:  # noqa: BLE001 - without the rules, the read alone decides
            checked = None
        t = classify_spam(apply_rules(t, checked, is_trusted(pr, self.settings.judge_all_authors)), state, self.model)
        if escalate and t.uncertain:
            t = second_opinion(self.settings, state, t)
        return pr, t

    def apply(self, pr: PullRequest, t: Triage) -> None:
        wanted = report.labels(t)
        for name, color, description in wanted:
            self.github.ensure_label(pr.owner, pr.repo, name, color, description)
        add = [name for name, _, _ in wanted] + ([t.area] if t.area else [])
        self.github.set_labels(pr.owner, pr.repo, pr.number, add, report.LABEL_PREFIX)
        issue = pr.linked_issue["number"] if pr.linked_issue else None
        self.github.upsert_comment(pr.owner, pr.repo, pr.number, report.comment(t, issue))


def summary(pr: PullRequest, t: Triage) -> dict:
    r = t.reading
    return {
        "url": pr.url, "repo": f"{pr.owner}/{pr.repo}", "number": pr.number, "title": pr.title, "author": pr.author,
        "verdict": t.verdict, "spam_type": t.spam_type, "confidence": round(t.confidence, 3),
        "uncertain": t.uncertain, "flags": t.flags, "area": t.area,
        "probabilities": {k: round(v, 3) for k, v in t.probabilities.items()},
        "effort": round(t.effort, 2), "notes": t.notes, "second_opinion": t.second_opinion,
        "model": r.model, "server_ms": r.server_ms, "wall_ms": round(r.wall_ms), "input_tokens": r.input_tokens,
        "rules": {k: t.rules[k] for k in ("failed", "total", "checks")} if t.rules and not t.rules.get("error") else None,
    }

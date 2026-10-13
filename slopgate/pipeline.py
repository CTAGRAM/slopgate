"""Fetch -> read -> escalate if unsure -> label and comment. Shared by the CLI and the server."""

from . import report
from .config import Settings
from .escalate import second_opinion
from .github import GitHub, PullRequest
from .judge import Triage, judge
from .openjev import OpenJev


class SlopGate:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.github = GitHub(settings.github_token)
        self.model = OpenJev(settings.openjev_url, settings.openjev_key, settings.model)

    def triage(self, url: str, escalate: bool = True) -> tuple[PullRequest, Triage]:
        pr = self.github.pull_request(url)
        state, t = judge(pr, self.model, self.settings.judge_all_authors)
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
        "url": pr.url, "verdict": t.verdict, "spam_type": t.spam_type, "confidence": round(t.confidence, 3),
        "uncertain": t.uncertain, "flags": t.flags, "area": t.area,
        "probabilities": {k: round(v, 3) for k, v in t.probabilities.items()},
        "effort": round(t.effort, 2), "notes": t.notes, "second_opinion": t.second_opinion,
        "model": r.model, "server_ms": r.server_ms, "wall_ms": round(r.wall_ms), "input_tokens": r.input_tokens,
    }

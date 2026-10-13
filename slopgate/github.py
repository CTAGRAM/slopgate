"""What SlopGate reads from (and writes to) GitHub, as plain REST calls."""

import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import httpx

PR_URL = re.compile(r"github\.com/([^/\s]+)/([^/\s]+)/pull/(\d+)")
CLOSING_REF = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#(\d+)", re.I)
ANY_REF = re.compile(r"(?<![\w/])#(\d+)\b")
COMMENT_MARKER = "<!-- slopgate -->"


def parse_pr_url(url: str) -> tuple[str, str, int]:
    m = PR_URL.search(url)
    if not m:
        raise ValueError(f"not a pull request URL: {url}")
    return m.group(1), m.group(2), int(m.group(3))


STOPWORDS = {"the", "and", "for", "with", "from", "this", "that", "fix", "fixes", "add", "adds", "update",
             "when", "into", "not", "use", "feat", "chore", "docs"}


def _words(title: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", title.lower()) if len(w) > 2 and w not in STOPWORDS}


def _jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def _ts(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


@dataclass
class PullRequest:
    owner: str
    repo: str
    number: int
    url: str
    title: str
    body: str
    author: str
    author_association: str
    created_at: datetime
    files: list[dict]
    account_created_at: datetime | None
    prs_in_prior_24h: int | None
    linked_issue: dict | None
    repo_labels: list[dict] = field(default_factory=list)
    contributing: str = ""
    similar_recent: int | None = None  # near-identical PRs by other authors in the 48 h before this one
    similar_authors: int | None = None
    same_issue_prs: int | None = None  # other PRs that already reference the same linked issue

    @property
    def account_age_days(self) -> int | None:
        if not self.account_created_at:
            return None
        return (self.created_at - self.account_created_at).days


class GitHub:
    def __init__(self, token: str | None):
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._http = httpx.Client(base_url="https://api.github.com", headers=headers, timeout=30)
        self._labels: dict[str, list[dict]] = {}
        self._contributing: dict[str, str] = {}

    def _get(self, path: str, **params):
        for attempt in range(5):
            r = self._http.get(path, params=params)
            limited = r.status_code == 429 or (r.status_code == 403 and "rate limit" in r.text.lower())
            if not limited or attempt == 4:
                break
            # primary limits say when they reset; secondary limits only say "wait a few minutes"
            reset = r.headers.get("retry-after") or (
                max(1, int(r.headers["x-ratelimit-reset"]) - int(time.time())) if r.headers.get("x-ratelimit-remaining") == "0" else 60)
            time.sleep(min(int(reset), 300))
        r.raise_for_status()
        return r.json()

    def repo_labels(self, owner: str, repo: str) -> list[dict]:
        key = f"{owner}/{repo}"
        if key not in self._labels:
            self._labels[key] = self._get(f"/repos/{key}/labels", per_page=100)
        return self._labels[key]

    def contributing(self, owner: str, repo: str) -> str:
        """The repo's CONTRIBUTING guide, so PRs are judged against the project's own rules."""
        key = f"{owner}/{repo}"
        if key not in self._contributing:
            self._contributing[key] = ""
            for path in ("CONTRIBUTING.md", ".github/CONTRIBUTING.md", "docs/CONTRIBUTING.md"):
                r = self._http.get(f"/repos/{key}/contents/{path}", headers={"Accept": "application/vnd.github.raw"})
                if r.status_code == 200:
                    self._contributing[key] = r.text
                    break
        return self._contributing[key]

    def swarm(self, pr: "PullRequest", hours: int = 48) -> None:
        """Fill in how many other people recently opened near-identical PRs, or PRs for the same issue.
        Only PRs opened before this one count: that is all a gate would see when this one arrives."""
        fmt = "%Y-%m-%dT%H:%M:%SZ"
        start = (pr.created_at - timedelta(hours=hours)).strftime(fmt)
        end = pr.created_at.strftime(fmt)
        try:
            items = self._get("/search/issues", q=f"repo:{pr.owner}/{pr.repo} is:pr created:{start}..{end}", per_page=100)["items"]
        except httpx.HTTPStatusError:
            items = []
        mine = _words(pr.title)
        similar = [i for i in items if i["number"] != pr.number and i["user"]["login"] != pr.author
                   and _jaccard(mine, _words(i["title"])) >= 0.4]
        pr.similar_recent = len(similar)
        pr.similar_authors = len({i["user"]["login"] for i in similar})
        if pr.linked_issue:
            try:
                events = self._get(f"/repos/{pr.owner}/{pr.repo}/issues/{pr.linked_issue['number']}/timeline", per_page=100)
            except httpx.HTTPStatusError:
                events = []
            others = {e["source"]["issue"]["number"] for e in events
                      if e.get("event") == "cross-referenced" and "pull_request" in e.get("source", {}).get("issue", {})
                      and e["source"]["issue"]["number"] != pr.number
                      and _ts(e["created_at"]) <= pr.created_at
                      and e["source"]["issue"]["user"]["login"] != pr.author}
            pr.same_issue_prs = len(others)

    def prs_in_window(self, author: str, end: datetime, hours: int = 24) -> int | None:
        """How many PRs the author opened anywhere on GitHub in the hours before `end`."""
        start = end - timedelta(hours=hours)
        fmt = "%Y-%m-%dT%H:%M:%SZ"
        q = f"type:pr author:{author} created:{start.strftime(fmt)}..{end.strftime(fmt)}"
        try:
            return self._get("/search/issues", q=q, per_page=1)["total_count"]
        except httpx.HTTPStatusError:
            return None  # search is rate limited separately; a missing count is not fatal

    def pull_request(self, url: str) -> PullRequest:
        owner, repo, number = parse_pr_url(url)
        base = f"/repos/{owner}/{repo}"
        pr = self._get(f"{base}/pulls/{number}")
        files = self._get(f"{base}/pulls/{number}/files", per_page=100)
        author = pr["user"]["login"]
        created = _ts(pr["created_at"])

        account_created = None
        if pr["user"].get("type") != "Bot":
            try:
                account_created = _ts(self._get(f"/users/{author}")["created_at"])
            except httpx.HTTPStatusError:
                pass  # deleted account

        body = pr.get("body") or ""
        ref = CLOSING_REF.search(body) or ANY_REF.search(body)
        linked = None
        if ref:
            try:
                issue = self._get(f"{base}/issues/{ref.group(1)}")
                if "pull_request" not in issue:
                    linked = {"number": issue["number"], "title": issue["title"], "body": issue.get("body") or ""}
            except httpx.HTTPStatusError:
                pass

        result = PullRequest(
            owner=owner, repo=repo, number=number, url=pr["html_url"],
            title=pr["title"], body=body, author=author,
            author_association=pr.get("author_association", "NONE"),
            created_at=created, files=files,
            account_created_at=account_created,
            prs_in_prior_24h=self.prs_in_window(author, created),
            linked_issue=linked,
            repo_labels=self.repo_labels(owner, repo),
            contributing=self.contributing(owner, repo),
        )
        self.swarm(result)
        return result

    # --- writes -----------------------------------------------------------------

    def ensure_label(self, owner: str, repo: str, name: str, color: str, description: str) -> None:
        if any(l["name"] == name for l in self.repo_labels(owner, repo)):
            return
        r = self._http.post(f"/repos/{owner}/{repo}/labels",
                            json={"name": name, "color": color, "description": description})
        if r.status_code not in (201, 422):  # 422: it already exists
            r.raise_for_status()
        self._labels.pop(f"{owner}/{repo}", None)

    def set_labels(self, owner: str, repo: str, number: int, add: list[str], remove_prefix: str) -> None:
        """Add `add`, and drop any older labels of ours (those starting with `remove_prefix`)."""
        issue = f"/repos/{owner}/{repo}/issues/{number}"
        current = [l["name"] for l in self._get(f"{issue}/labels")]
        for name in current:
            if name.startswith(remove_prefix) and name not in add:
                self._http.delete(f"{issue}/labels/{name}")
        if add:
            self._http.post(f"{issue}/labels", json={"labels": add}).raise_for_status()

    def upsert_comment(self, owner: str, repo: str, number: int, body: str) -> None:
        """One SlopGate comment per PR: edit it on re-triage instead of piling up new ones."""
        comments = self._get(f"/repos/{owner}/{repo}/issues/{number}/comments", per_page=100)
        mine = next((c for c in comments if COMMENT_MARKER in (c.get("body") or "")), None)
        body = f"{COMMENT_MARKER}\n{body}"
        if mine:
            self._http.patch(f"/repos/{owner}/{repo}/issues/comments/{mine['id']}", json={"body": body}).raise_for_status()
        else:
            self._http.post(f"/repos/{owner}/{repo}/issues/{number}/comments", json={"body": body}).raise_for_status()

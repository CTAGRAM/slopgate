"""What SlopGate reads from (and writes to) GitHub, as plain REST calls."""

import re
import time
from concurrent.futures import ThreadPoolExecutor
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
    pr_template: str = ""
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
        self._templates: dict[str, str] = {}

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

    def pr_template(self, owner: str, repo: str) -> str:
        """The repo's pull request template: its HTML comments are the maintainers' words, not the contributor's."""
        key = f"{owner}/{repo}"
        if key not in self._templates:
            self._templates[key] = ""
            for path in (".github/pull_request_template.md", ".github/PULL_REQUEST_TEMPLATE.md",
                         "PULL_REQUEST_TEMPLATE.md", "docs/pull_request_template.md"):
                r = self._http.get(f"/repos/{key}/contents/{path}", headers={"Accept": "application/vnd.github.raw"})
                if r.status_code == 200:
                    self._templates[key] = r.text
                    break
        return self._templates[key]

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

    def similar_recent(self, owner: str, repo: str, number: int, author: str, title: str,
                       created: datetime, hours: int = 48) -> tuple[int, int]:
        """Near-identical PRs by other people in the hours before this one: (PRs, authors).
        Only earlier PRs count: that is all a gate would see when this one arrives."""
        fmt = "%Y-%m-%dT%H:%M:%SZ"
        start, end = (created - timedelta(hours=hours)).strftime(fmt), created.strftime(fmt)
        try:
            items = self._get("/search/issues", q=f"repo:{owner}/{repo} is:pr created:{start}..{end}", per_page=100)["items"]
        except httpx.HTTPStatusError:
            items = []
        mine = _words(title)
        similar = [i for i in items if i["number"] != number and i["user"]["login"] != author
                   and _jaccard(mine, _words(i["title"])) >= 0.4]
        return len(similar), len({i["user"]["login"] for i in similar})

    def same_issue(self, owner: str, repo: str, issue: int, number: int, author: str, created: datetime) -> int:
        """Other people's PRs that already referenced the same issue when this one arrived."""
        try:
            events = self._get(f"/repos/{owner}/{repo}/issues/{issue}/timeline", per_page=100)
        except httpx.HTTPStatusError:
            return 0
        return len({e["source"]["issue"]["number"] for e in events
                    if e.get("event") == "cross-referenced" and "pull_request" in e.get("source", {}).get("issue", {})
                    and e["source"]["issue"]["number"] != number and _ts(e["created_at"]) <= created
                    and e["source"]["issue"]["user"]["login"] != author})

    def swarm(self, pr: "PullRequest") -> None:
        """Fill in the swarm facts for a PR loaded without them (evaluation snapshots)."""
        pr.similar_recent, pr.similar_authors = self.similar_recent(
            pr.owner, pr.repo, pr.number, pr.author, pr.title, pr.created_at)
        pr.same_issue_prs = self.same_issue(pr.owner, pr.repo, pr.linked_issue["number"], pr.number, pr.author,
                                            pr.created_at) if pr.linked_issue else None

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
        author, created, body = pr["user"]["login"], _ts(pr["created_at"]), pr.get("body") or ""
        ref = CLOSING_REF.search(body) or ANY_REF.search(body)

        def account() -> datetime | None:
            if pr["user"].get("type") == "Bot":
                return None
            try:
                return _ts(self._get(f"/users/{author}")["created_at"])
            except httpx.HTTPStatusError:
                return None  # deleted account

        def linked() -> dict | None:
            if not ref:
                return None
            try:
                issue = self._get(f"{base}/issues/{ref.group(1)}")
            except httpx.HTTPStatusError:
                return None
            if "pull_request" in issue:
                return None
            return {"number": issue["number"], "title": issue["title"], "body": issue.get("body") or ""}

        # everything below depends only on the PR itself, so read it all at once
        with ThreadPoolExecutor(8) as pool:
            jobs = {
                "files": pool.submit(self._get, f"{base}/pulls/{number}/files", per_page=100),
                "account": pool.submit(account), "linked": pool.submit(linked),
                "prs_24h": pool.submit(self.prs_in_window, author, created),
                "labels": pool.submit(self.repo_labels, owner, repo),
                "contributing": pool.submit(self.contributing, owner, repo),
                "template": pool.submit(self.pr_template, owner, repo),
                "similar": pool.submit(self.similar_recent, owner, repo, number, author, pr["title"], created),
                "same_issue": pool.submit(self.same_issue, owner, repo, int(ref.group(1)), number, author, created)
                if ref else None,
            }
            got = {k: f.result() if f else None for k, f in jobs.items()}

        result = PullRequest(
            owner=owner, repo=repo, number=number, url=pr["html_url"],
            title=pr["title"], body=body, author=author,
            author_association=pr.get("author_association", "NONE"),
            created_at=created, files=got["files"],
            account_created_at=got["account"],
            prs_in_prior_24h=got["prs_24h"],
            linked_issue=got["linked"],
            repo_labels=got["labels"],
            contributing=got["contributing"],
            pr_template=got["template"],
            similar_recent=got["similar"][0], similar_authors=got["similar"][1],
            same_issue_prs=got["same_issue"] if got["linked"] else None,
        )
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

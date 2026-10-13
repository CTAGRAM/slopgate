"""What SlopGate reads from (and writes to) GitHub, as plain REST calls."""

import re
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

    def _get(self, path: str, **params):
        r = self._http.get(path, params=params)
        r.raise_for_status()
        return r.json()

    def repo_labels(self, owner: str, repo: str) -> list[dict]:
        key = f"{owner}/{repo}"
        if key not in self._labels:
            self._labels[key] = self._get(f"/repos/{key}/labels", per_page=100)
        return self._labels[key]

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

        return PullRequest(
            owner=owner, repo=repo, number=number, url=pr["html_url"],
            title=pr["title"], body=body, author=author,
            author_association=pr.get("author_association", "NONE"),
            created_at=created, files=files,
            account_created_at=account_created,
            prs_in_prior_24h=self.prs_in_window(author, created),
            linked_issue=linked,
            repo_labels=self.repo_labels(owner, repo),
        )

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

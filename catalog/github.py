"""Minimal GitHub REST client built on the standard library."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from urllib.parse import quote

API = "https://api.github.com"
USER_AGENT = "ps5-homebrew-catalog-verifier"
TIMEOUT = 30


class GitHubError(RuntimeError):
    pass


class GitHub:
    def __init__(self, token: str | None = None):
        self.token = token if token is not None else os.environ.get("GITHUB_TOKEN")

    def _request(self, method: str, path: str, body: dict | None = None, raw: bool = False):
        """Return decoded JSON (or text when raw), or None for 404. Other failures raise GitHubError."""
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(API + path, data=data, method=method, headers={
            "Accept": "application/vnd.github.raw" if raw else "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": USER_AGENT,
        })
        if data is not None:
            request.add_header("Content-Type", "application/json")
        if self.token:
            request.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                payload = response.read()
                if raw:
                    return payload.decode("utf-8", errors="replace")
                return json.loads(payload) if payload else {}
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return None
            if error.code in (403, 429) and error.headers.get("x-ratelimit-remaining") == "0":
                raise GitHubError("GitHub API rate limit reached; set GITHUB_TOKEN") from error
            raise GitHubError(f"GitHub API returned HTTP {error.code} for {method} {path}") from error
        except (urllib.error.URLError, TimeoutError, ValueError) as error:
            raise GitHubError(f"GitHub API request failed for {method} {path}: {error}") from error

    def _get(self, path: str):
        return self._request("GET", path)

    def graphql(self, query: str, variables: dict | None = None) -> dict:
        """The `data` of a GraphQL answer; an answer with errors raises GitHubError."""
        answer = self._request("POST", "/graphql", {"query": query, "variables": variables or {}})
        if not answer or answer.get("errors") or "data" not in answer:
            errors = "; ".join(e.get("message", "") for e in (answer or {}).get("errors", [])) or "no data"
            raise GitHubError(f"GitHub GraphQL request failed: {errors}")
        return answer["data"]

    def repo(self, owner: str, name: str) -> dict | None:
        return self._get(f"/repos/{quote(owner)}/{quote(name)}")

    def release_by_tag(self, owner: str, name: str, tag: str) -> dict | None:
        return self._get(f"/repos/{quote(owner)}/{quote(name)}/releases/tags/{quote(tag, safe='')}")

    def releases(self, owner: str, name: str) -> list[dict]:
        return self._get(f"/repos/{quote(owner)}/{quote(name)}/releases?per_page=20") or []

    def commit_author(self, repository: str, sha: str) -> str | None:
        """GitHub login of a commit's author, or None when it isn't linked to an account."""
        commit = self._get(f"/repos/{repository}/commits/{quote(sha)}") or {}
        return (commit.get("author") or {}).get("login")

    def account_type(self, login: str) -> str | None:
        """'User' or 'Organization', or None when the account doesn't exist."""
        account = self._get(f"/users/{quote(login)}")
        return account.get("type") if account else None

    def is_public_member(self, org: str, user: str) -> bool:
        """True when user publicly belongs to org (GitHub answers 204 or 404)."""
        return self._get(f"/orgs/{quote(org)}/public_members/{quote(user)}") is not None

    def user(self, login: str) -> dict | None:
        return self._get(f"/users/{quote(login)}")

    def tree(self, owner: str, name: str, ref: str) -> list[str]:
        """Paths of all files at ref (GitHub may truncate very large trees)."""
        tree = self._get(f"/repos/{quote(owner)}/{quote(name)}/git/trees/{quote(ref, safe='')}?recursive=1") or {}
        return [item["path"] for item in tree.get("tree", []) if item.get("type") == "blob"]

    def file_text(self, owner: str, name: str, path: str, ref: str) -> str | None:
        return self._request("GET", f"/repos/{quote(owner)}/{quote(name)}/contents/{quote(path)}"
                                    f"?ref={quote(ref, safe='')}", raw=True)

    # Used only by the discovery job.

    def search(self, kind: str, query: str, page: int = 1, sort: str = "") -> dict:
        """One page (up to 100 results) of /search/code or /search/repositories."""
        order = f"&sort={quote(sort)}&order=desc" if sort else ""
        return self._get(f"/search/{kind}?q={quote(query)}&per_page=100&page={page}{order}") or {}

    def owner_repos(self, owner: str) -> list[dict]:
        """An account's own public repositories, most recently pushed first."""
        return self._get(f"/users/{quote(owner)}/repos?type=owner&sort=pushed&per_page=100") or []

    def open_pull_files(self, repository: str) -> dict[str, int]:
        """Every file path touched by an open pull request, mapped to the pull request's number."""
        files: dict[str, int] = {}
        for pull in self._get(f"/repos/{repository}/pulls?state=open&per_page=100") or []:
            for item in self._get(f"/repos/{repository}/pulls/{pull['number']}/files?per_page=100") or []:
                files.setdefault(item["filename"], pull["number"])
        return files

    def open_issue(self, repository: str, label: str) -> dict | None:
        issues = self._get(f"/repos/{repository}/issues?state=open&labels={quote(label)}&per_page=10") or []
        return next((i for i in issues if "pull_request" not in i), None)

    def ensure_label(self, repository: str, label: str, color: str, description: str) -> None:
        if self._get(f"/repos/{repository}/labels/{quote(label)}") is None:
            self._request("POST", f"/repos/{repository}/labels",
                          {"name": label, "color": color, "description": description})

    def create_issue(self, repository: str, title: str, body: str, labels: list[str]) -> dict:
        return self._request("POST", f"/repos/{repository}/issues", {"title": title, "body": body, "labels": labels})

    def update_issue(self, repository: str, number: int, title: str, body: str) -> dict:
        return self._request("PATCH", f"/repos/{repository}/issues/{number}", {"title": title, "body": body})

    # Used only by the update job, with the catalog bot's token.

    def open_pull(self, repository: str, head_branch: str) -> dict | None:
        owner = repository.split("/")[0]
        pulls = self._get(f"/repos/{repository}/pulls?state=open&head={quote(owner)}:{quote(head_branch)}") or []
        return pulls[0] if pulls else None

    def closed_pull_titles(self, repository: str, head_branch: str) -> list[str]:
        owner = repository.split("/")[0]
        pulls = self._get(f"/repos/{repository}/pulls?state=closed&per_page=20"
                          f"&head={quote(owner)}:{quote(head_branch)}") or []
        return [p.get("title", "") for p in pulls if not p.get("merged_at")]

    def close_pull(self, repository: str, number: int) -> dict:
        return self._request("PATCH", f"/repos/{repository}/pulls/{number}", {"state": "closed"})

    def create_pull(self, repository: str, head: str, base: str, title: str, body: str) -> dict:
        return self._request("POST", f"/repos/{repository}/pulls",
                             {"head": head, "base": base, "title": title, "body": body})

    def update_pull(self, repository: str, number: int, title: str, body: str) -> dict:
        return self._request("PATCH", f"/repos/{repository}/pulls/{number}", {"title": title, "body": body})

    # Used only by the automatic merge of a developer's release bump, with the catalog bot's token.
    # Both name the commit that was checked: GitHub refuses them when the pull request has moved on.

    def approve_pull(self, repository: str, number: int, sha: str, body: str) -> dict:
        return self._request("POST", f"/repos/{repository}/pulls/{number}/reviews",
                             {"commit_id": sha, "event": "APPROVE", "body": body})

    def merge_pull(self, repository: str, number: int, sha: str, title: str) -> dict:
        merged = self._request("PUT", f"/repos/{repository}/pulls/{number}/merge",
                               {"sha": sha, "merge_method": "squash", "commit_title": title})
        if merged is None:
            raise GitHubError(f"pull request #{number} was not found")
        return merged

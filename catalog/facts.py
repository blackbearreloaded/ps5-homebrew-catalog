"""Facts about a listed release that GitHub knows and the record doesn't state.

The store API (docs/api.md) publishes each app's download size, release date
and content version. None of them needs the artifact: the size and date come
from the release in GitHub's API, and the content version from the
`sce_sys/param.json` the repository holds at the release tag.

The content version (`contentVersion`, "01.000.070") is what a console reports
for an installed title, so it is the value clients compare to find updates. It
is `None` when the repository has no param.json for this title at the tag, or
its contentVersion isn't in the PlayStation format; clients then can't tell
whether an installed copy is current.

Facts belong to one exact file, so they are cached by the record's sha256 and
looked up again when an app moves to a new release, or when its icon moves:
the content version is read from the param.json beside the icon, so a record
whose icon now points at a commit that holds one must be asked again.

The release notes (catalog/notes.py) are the exception: a developer can edit
them at any time. So an answer is trusted for a day, then asked again; when
GitHub can't answer, the older one keeps being used.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from . import artifacts
from .github import GitHub, GitHubError
from .records import Record

CONTENT_VERSION = re.compile(r"[0-9]{2}\.[0-9]{3}\.[0-9]{3}")
MAX_PARAM_BYTES = 65536
MAX_PARAM_FILES = 5     # param.json files tried when the repository has several (vendored samples)
MAX_NOTES = 40000       # characters of release notes kept
FRESH_SECONDS = 86400   # how long a cached answer is used before GitHub is asked again


@dataclass(frozen=True)
class Facts:
    size: int | None = None                # bytes of the listed file
    released: str | None = None            # when the release was published (ISO 8601, UTC)
    prerelease: bool | None = None
    content_version: str | None = None     # param.json contentVersion at the tag
    param_path: str | None = None          # where it was read from ("version" when taken from the record)
    notes: str | None = None               # the release's notes as the developer wrote them (GitHub Markdown)
    uploader: str | None = None            # who attached the file: "actions" (a workflow) or "developer"


def content_version_key(value: str | None) -> tuple[int, int, int] | None:
    """A content version as three integers, the way clients order them; None when it isn't one."""
    if not value or not CONTENT_VERSION.fullmatch(value):
        return None
    major, minor, patch = value.split(".")
    return int(major), int(minor), int(patch)


def _content_version(text: str, titleid: str) -> str | None:
    """The contentVersion of a param.json, when the file is this title's and the value is well formed."""
    try:
        param = json.loads(text)
    except ValueError:
        return None
    if not isinstance(param, dict) or param.get("titleId") != titleid:
        return None
    value = param.get("contentVersion")
    return value if isinstance(value, str) and CONTENT_VERSION.fullmatch(value) else None


def find_content_version(record: Record, github: GitHub, fetch=None) -> tuple[str | None, str | None]:
    """(contentVersion, where it was found) for the record's release; raises GitHubError when GitHub can't answer."""
    fetch = fetch or artifacts.fetch_small
    data = record.data
    # The icon usually sits next to param.json; that path costs one plain download and no API request.
    raw = f"https://raw.githubusercontent.com/{record.owner}/{record.repo}/"
    icon = data["icon_url"] or ""
    if icon.startswith(raw) and icon.endswith("/sce_sys/icon0.png"):
        url = icon.removesuffix("icon0.png") + "param.json"
        try:
            found = _content_version(fetch(url, MAX_PARAM_BYTES).decode("utf-8", errors="replace"), data["titleid"])
        except (artifacts.DownloadError, OSError):
            found = None
        if found:
            return found, url.removeprefix(raw).split("/", 1)[-1]
    paths = sorted((p for p in github.tree(record.owner, record.repo, record.tag) if p.endswith("sce_sys/param.json")),
                   key=lambda p: (p.count("/"), p))
    for path in paths[:MAX_PARAM_FILES]:
        found = _content_version(github.file_text(record.owner, record.repo, path, record.tag) or "", data["titleid"])
        if found:
            return found, path
    # Releases tagged with the content version itself need no param.json in the repository.
    if CONTENT_VERSION.fullmatch(data["version"]):
        return data["version"], "version"
    return None, None


def lookup(record: Record, github: GitHub, fetch=None) -> Facts:
    """Ask GitHub about the record's release; raises GitHubError when it can't answer."""
    release = github.release_by_tag(record.owner, record.repo, record.tag) or {}
    asset = next((a for a in release.get("assets", []) if a.get("name") == record.asset_name), {})
    content_version, where = find_content_version(record, github, fetch)
    body = release.get("body")
    login = (asset.get("uploader") or {}).get("login")
    uploader = None if not login else "actions" if login == "github-actions[bot]" else "developer"
    return Facts(size=asset.get("size"), released=release.get("published_at"),
                 prerelease=release.get("prerelease"), content_version=content_version, param_path=where,
                 notes=body[:MAX_NOTES] if isinstance(body, str) and body.strip() else None, uploader=uploader)


def cached(record: Record, github: GitHub | None, cache: Path | None, fetch=None) -> tuple[Facts, str | None]:
    """Facts for a release, from the cache when it has them; (Facts(), reason) when they can't be had now."""
    if record.reserved:
        return Facts(), None
    entry = cache / "facts" / f"{record.data['sha256']}.json" if cache else None
    older = None        # a cached answer that is due to be asked again
    if entry and entry.is_file():
        try:
            saved = json.loads(entry.read_text(encoding="utf-8"))
            # An entry without "notes" or "uploader" was written before they were read.
            if saved.pop("icon_url", None) == record.data["icon_url"] and "notes" in saved and "uploader" in saved:
                older = Facts(**saved)
                if github is None or time.time() - entry.stat().st_mtime < FRESH_SECONDS:
                    return older, None
        except (OSError, ValueError, TypeError, AttributeError):
            pass
        if older is None:
            entry.unlink(missing_ok=True)      # unreadable, or answered for another icon
    if github is None:
        return Facts(), None
    try:
        facts = lookup(record, github, fetch)
    except GitHubError as error:
        # A new answer isn't cached, so the next build asks again; an older one keeps serving.
        return (older, None) if older else (Facts(), str(error))
    if entry:
        entry.parent.mkdir(parents=True, exist_ok=True)
        entry.write_text(json.dumps(asdict(facts) | {"icon_url": record.data["icon_url"]}), encoding="utf-8")
    return facts, None


def prune(cache: Path | None, records: list[Record]) -> None:
    """Drop cached facts of releases that are no longer listed."""
    if not cache or not (cache / "facts").is_dir():
        return
    wanted = {f"{r.data['sha256']}.json" for r in records if not r.reserved}
    for entry in (cache / "facts").glob("*.json"):
        if entry.name not in wanted:
            entry.unlink()


def update_note(old: Facts, new: Facts) -> str:
    """What an update means for consoles, for the update pull request."""
    if new.content_version is None:
        return ("No `contentVersion` could be read for the new release (no `sce_sys/param.json` for this title "
                "at the tag): consoles can't tell that an installed copy is outdated.")
    if old.content_version == new.content_version:
        return (f"`contentVersion` is still `{new.content_version}`: consoles won't see this release as an "
                "update until the developer raises it.")
    old_key, new_key = content_version_key(old.content_version), content_version_key(new.content_version)
    if old_key and new_key < old_key:
        return (f"`contentVersion` goes down, from `{old.content_version}` to `{new.content_version}`: consoles "
                "that have the listed release won't see this one as an update.")
    return f"`contentVersion`: `{old.content_version or 'unknown'}` → `{new.content_version}`."

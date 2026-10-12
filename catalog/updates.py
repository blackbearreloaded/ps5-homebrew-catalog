"""Find newer upstream releases and turn them into updated records.

For a listed release, the newest published release of its repository
(pre-releases included) becomes the proposed update when:

- it has an asset with the same file type that is unambiguously the successor
  of the listed one (same name, or the same name with the version changed, or
  the only asset of that type);
- GitHub reports a SHA-256 digest for that asset (nothing is downloaded).

The version follows the tag in the record's existing style, and a tag-pinned
icon_url is moved to the new tag when the icon exists there. Everything else in
the record stays unchanged.
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote, unquote

from . import artifacts
from .github import GitHub
from .records import Record, load_record, tag_version
from .report import Report

BUMP_FIELDS = ("version", "artifact_url", "sha256", "icon_url")


@dataclass
class Update:
    record: Record
    data: dict                      # the complete new record
    tag: str
    prerelease: bool
    notes: list[str] = field(default_factory=list)


def newest_release(github: GitHub, owner: str, repo: str) -> dict | None:
    """The newest published release (drafts skipped; pre-releases count).

    A release whose tag has no digit (build-cache, build-inputs, nightly) holds build files, not
    a version of the app, and is skipped as well.
    """
    for release in github.releases(owner, repo):
        if not release.get("draft") and any(c.isdigit() for c in release.get("tag_name", "")):
            return release
    return None


def _extension(name: str) -> str:
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def _version_tokens(tag: str, version: str | None) -> list[str]:
    tokens = {tag, tag_version(tag)}
    if version:
        tokens.add(version)
    return sorted((t for t in tokens if t), key=len, reverse=True)


def pick_asset(assets: list[dict], old_name: str, old_tag: str, old_version: str | None,
               new_tag: str) -> tuple[dict | None, str]:
    """Choose the successor of old_name among a release's assets; return (asset, how) or (None, why)."""
    ext = _extension(old_name)
    candidates = [a for a in assets if _extension(a.get("name", "")) == ext]
    by_name = {a["name"]: a for a in candidates}
    if old_name in by_name:
        return by_name[old_name], "same file name"
    for token in _version_tokens(old_tag, old_version):
        if token in old_name:
            replacement = new_tag if token == old_tag else tag_version(new_tag)
            expected = old_name.replace(token, replacement)
            if expected in by_name:
                return by_name[expected], "file name with the new version"
    if len(candidates) == 1:
        return candidates[0], f"the only .{ext} file"
    if not candidates:
        return None, f"the release has no .{ext} file"
    return None, f"the release has {len(candidates)} .{ext} files and none matches {old_name!r}"


def new_version(old_version: str, old_tag: str, new_tag: str) -> str:
    if old_version == old_tag:
        return new_tag
    return tag_version(new_tag)


def find_update(record: Record, github: GitHub, icon_exists=None) -> tuple[Update | None, str]:
    """Return (update, "") or (None, reason there is nothing to propose)."""
    if record.reserved:
        return None, "reservation"
    release = newest_release(github, record.owner, record.repo)
    if release is None:
        return None, "no published releases"
    tag = release.get("tag_name", "")
    if tag == record.tag:
        return None, "up to date"
    asset, how = pick_asset(release.get("assets", []), record.asset_name, record.tag,
                            record.data["version"], tag)
    if asset is None:
        return None, f"newer release {tag} found, but {how}"
    digest = asset.get("digest") or ""
    if not digest.startswith("sha256:"):
        return None, f"newer release {tag} found, but GitHub reports no digest for {asset['name']}"

    data = dict(record.data)
    data["artifact_url"] = f"{data['source_repo']}/releases/download/{quote(tag, safe='')}/{asset['name']}"
    data["sha256"] = digest.removeprefix("sha256:")
    data["version"] = new_version(data["version"], record.tag, tag)
    notes = [f"asset chosen by {how}: {asset['name']}"]

    old_segment = f"/{quote(record.tag, safe='')}/"
    if old_segment in data["icon_url"]:
        candidate = data["icon_url"].replace(old_segment, f"/{quote(tag, safe='')}/", 1)
        exists = icon_exists or _icon_exists
        if exists(candidate):
            data["icon_url"] = candidate
        else:
            notes.append("icon kept at the listed tag (not found at the new tag)")

    problems = validate(record.path.name, data)
    if problems:
        return None, f"newer release {tag} found, but the updated record would be invalid: {problems[0]}"
    return Update(record, data, tag, bool(release.get("prerelease")), notes), ""


def find_gone(record: Record, github: GitHub) -> str | None:
    """Why a listed app can no longer be installed (its repository, release or file is gone), or None.

    Only GitHub's plain "not found" counts; any other failure raises GitHubError and proves nothing.
    """
    if record.reserved:
        return None
    if github.repo(record.owner, record.repo) is None:
        return "the repository no longer exists"
    release = github.release_by_tag(record.owner, record.repo, record.tag)
    if release is None:
        return f"the release {record.tag} no longer exists"
    names = {a.get("name") for a in release.get("assets", [])}
    if not names & {record.asset_name, unquote(record.asset_name)}:
        return f"the release {record.tag} no longer has {record.asset_name}"
    return None


def _icon_exists(url: str) -> bool:
    try:
        return artifacts.inspect_icon(artifacts.fetch_small(url, artifacts.MAX_ICON_BYTES))[0] is not None
    except (artifacts.DownloadError, OSError):
        return False


def validate(filename: str, data: dict) -> list[str]:
    report = Report()
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / filename
        path.write_text(render(data), encoding="utf-8")
        load_record(path, report)
    return [message for level, _, message in report.items if level == "error"]


def render(data: dict) -> str:
    """Serialize a record the way the repository stores records."""
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def is_release_bump(old: Record, new: Record, github: GitHub) -> bool:
    """True when new only moves old to its repository's newest release.

    Such an update can come from anyone, including the catalog bot: the release
    it points at was published by the repository's owner.
    """
    if old.reserved or new.reserved or old.data["source_repo"] != new.data["source_repo"]:
        return False
    if any(old.data[f] != new.data[f] for f in old.data if f not in BUMP_FIELDS):
        return False
    release = newest_release(github, new.owner, new.repo)
    return bool(release) and release.get("tag_name") == new.tag

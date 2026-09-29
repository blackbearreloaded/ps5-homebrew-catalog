"""Draft a catalog record for someone's repository, without downloading artifacts.

Used by maintainers and AI agents following docs/maintainers/listing-runbook.md.
It gathers the facts GitHub can prove (release, asset, digest, title ID, title
name, icon, license detection) and leaves the judgment fields (kind,
description, author, license when undetected) for the person or agent to fill
and justify. Nothing here writes to GitHub.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote, urlsplit

from . import artifacts
from .github import GitHub
from .records import FIELDS, TITLE_ID, load_catalog
from .report import Report
from .updates import newest_release

ARTIFACT_EXTENSIONS = (".zip", ".ffpkg", ".ffpfsc")
PAYLOAD_EXTENSIONS = (".elf", ".bin", ".lua", ".js")
LICENSE_HEADING = re.compile(r"^#{1,6}\s.*\blicen[cs]", re.IGNORECASE)


@dataclass
class Draft:
    record: dict
    facts: list[str] = field(default_factory=list)
    todo: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    alternatives: list[str] = field(default_factory=list)


def parse_repo(value: str) -> tuple[str, str]:
    """Accept owner/repo or a github.com URL."""
    value = value.strip()
    if value.startswith("http"):
        value = urlsplit(value).path
    parts = [p for p in value.strip("/").split("/") if p]
    if len(parts) < 2:
        raise ValueError(f"expected owner/repository or a GitHub URL, got {value!r}")
    return parts[0], parts[1].removesuffix(".git")


def find_param_json(paths: list[str]) -> list[str]:
    """param.json files of native titles, shortest path (repository root) first."""
    found = [p for p in paths if p.endswith("sce_sys/param.json")]
    return sorted(found, key=lambda p: (p.count("/"), p))


def draft_record(repo_value: str, github: GitHub, apps_dir: Path, tag: str | None = None,
                 asset_name: str | None = None) -> Draft:
    owner, name = parse_repo(repo_value)
    record = {field_name: "" for field_name in FIELDS}
    draft = Draft(record)

    repo = github.repo(owner, name)
    if repo is None or repo.get("private"):
        draft.blockers.append(f"{owner}/{name} is not a public GitHub repository")
        return draft
    full_name = repo["full_name"]
    owner, name = full_name.split("/")
    record["source_repo"] = f"https://github.com/{full_name}"
    draft.facts.append(f"repository: {record['source_repo']} (archived: {repo.get('archived')}, "
                       f"fork: {repo.get('fork')})")
    if repo.get("archived"):
        draft.todo.append("the repository is archived; confirm it is still maintained")

    spdx = (repo.get("license") or {}).get("spdx_id")
    if spdx and spdx != "NOASSERTION":
        record["license"] = spdx
        draft.facts.append(f"license detected by GitHub: {spdx}")
    else:
        draft.todo.append("GitHub detects no license: read the README/LICENSE files, set `license` to the "
                          "SPDX identifier they state, quote the source in the PR, or stop if none is stated")

    release = github.release_by_tag(owner, name, tag) if tag else newest_release(github, owner, name)
    if release is None or release.get("draft"):
        draft.blockers.append("no published release" + (f" tagged {tag!r}" if tag else ""))
        return draft
    tag = release["tag_name"]
    draft.facts.append(f"release: {tag} ({'pre-release' if release.get('prerelease') else 'release'}, "
                       f"published {release.get('published_at')})")

    assets = release.get("assets", [])
    payloads = [a["name"] for a in assets if a["name"].lower().endswith(PAYLOAD_EXTENSIONS)]
    if payloads:
        draft.todo.append(f"the release also has payload-like files {payloads}; confirm the listed file is "
                          "a native title, not a payload")
    candidates = [a for a in assets if a["name"].lower().endswith(ARTIFACT_EXTENSIONS)]
    if asset_name:
        candidates = [a for a in candidates if a["name"] == asset_name]
    if not candidates:
        draft.blockers.append("the release has no .zip, .ffpkg or .ffpfsc file"
                              + (f" named {asset_name!r}" if asset_name else ""))
        return draft
    if len(candidates) > 1:
        draft.alternatives = [a["name"] for a in candidates]
        draft.todo.append("several possible files; the first was used. Pick the app itself with --asset: "
                          + ", ".join(draft.alternatives))
    asset = candidates[0]
    digest = asset.get("digest") or ""
    if not digest.startswith("sha256:"):
        draft.blockers.append(f"GitHub reports no digest for {asset['name']}")
        return draft
    record["artifact_url"] = f"{record['source_repo']}/releases/download/{quote(tag, safe='')}/{asset['name']}"
    record["sha256"] = digest.removeprefix("sha256:")
    record["version"] = tag.lstrip("vV")
    draft.facts.append(f"file: {asset['name']} ({asset.get('size', 0):,} bytes), GitHub digest {digest}")

    # Native title evidence: sce_sys/param.json at the release tag.
    params = find_param_json(github.tree(owner, name, tag))
    if not params:
        draft.blockers.append(f"no sce_sys/param.json at {tag}: no evidence this is a native PS5 title")
        return draft
    param_path = params[0]
    if len(params) > 1:
        draft.todo.append(f"several param.json files {params}; {param_path} was used, confirm it is the app's")
    try:
        param = json.loads(github.file_text(owner, name, param_path, tag) or "")
    except ValueError:
        draft.blockers.append(f"{param_path} is not valid JSON")
        return draft
    titleid = str(param.get("titleId", ""))
    localized = param.get("localizedParameters") or {}
    language = localized.get("defaultLanguage", "en-US")
    title_name = (localized.get(language) or {}).get("titleName", "")
    draft.facts.append(f"{param_path}: titleId {titleid!r}, titleName {title_name!r}, "
                       f"contentId {param.get('contentId')!r}, contentVersion {param.get('contentVersion')!r}")
    if not TITLE_ID.fullmatch(titleid) or not titleid.startswith("PPSA"):
        draft.blockers.append(f"titleId {titleid!r} is not a PS5 (PPSA) title ID")
        return draft
    record["titleid"] = titleid
    record["name"] = title_name

    icon_path = param_path.rsplit("/", 1)[0] + "/icon0.png"
    icon_url = f"https://raw.githubusercontent.com/{full_name}/{quote(tag, safe='')}/{quote(icon_path)}"
    try:
        image_format, warnings = artifacts.inspect_icon(artifacts.fetch_small(icon_url, artifacts.MAX_ICON_BYTES))
    except (artifacts.DownloadError, OSError):
        image_format, warnings = None, []
    if image_format:
        record["icon_url"] = icon_url
        draft.facts.append(f"icon: {icon_url} ({image_format})" + (f"; {'; '.join(warnings)}" if warnings else ""))
    else:
        draft.todo.append(f"no usable icon at {icon_path}; find the app's icon in the repository, pinned to {tag}")

    # Profile name as a starting point for `author`.
    profile = github.user(owner) or {}
    record["author"] = profile.get("name") or owner
    draft.todo.append(f"confirm `author` ({record['author']!r}) is how the developer credits themselves "
                      "(README, release notes)")
    draft.todo.append("write `description`: one factual sentence, at most 200 characters, based on the README")
    draft.todo.append("set `kind` to app, game or tool")

    # Clashes with the catalog.
    existing = {r.titleid: r for r in load_catalog(apps_dir, Report())}
    if titleid in existing:
        draft.blockers.append(f"{titleid} is already listed as {existing[titleid].data['name']!r}")
    for other in existing.values():
        if title_name and other.data["name"].casefold() == title_name.casefold():
            draft.todo.append(f"the name {title_name!r} is already used by {other.titleid}; choose a distinct name")

    section = license_section(github.file_text(owner, name, "README.md", tag) or "")
    if section:
        draft.facts.append("README license section: " + section)
    return draft


def license_section(readme: str, max_chars: int = 600) -> str:
    """The text under the README's first heading that mentions a license."""
    lines = readme.splitlines()
    for index, line in enumerate(lines):
        if LICENSE_HEADING.match(line):
            body = []
            for following in lines[index + 1:]:
                if following.startswith("#"):
                    break
                if following.strip():
                    body.append(following.strip())
            return " ".join(body)[:max_chars]
    return ""


def render_draft(draft: Draft) -> str:
    lines = ["Record draft (fill every empty field):", json.dumps(draft.record, indent=2, ensure_ascii=False), ""]
    for title, items in (("Blockers (do not submit)", draft.blockers), ("To do", draft.todo), ("Facts", draft.facts)):
        if items:
            lines.append(f"{title}:")
            lines.extend(f"- {item}" for item in items)
            lines.append("")
    return "\n".join(lines)

"""Offline validation of catalog records under apps/.

Every record has exactly FIELDS. A record whose URL fields (source_repo,
artifact_url, icon_url) are null is a title ID reservation shown as coming soon;
its sha256 is null too, and version and license may be null.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .report import Report

FIELDS = (
    "titleid", "name", "kind", "description", "license", "author",
    "version", "source_repo", "artifact_url", "sha256", "icon_url",
)
RESERVATION_NULL = ("source_repo", "artifact_url", "icon_url", "sha256")
RESERVATION_NULLABLE = ("version", "license")
MAX_RESERVATIONS_PER_ACCOUNT = 5
RESERVATION_STALE_DAYS = 180
KINDS = ("app", "game", "tool")
# The shelves of the website and the store, in the order they are shown. A record names the key;
# the label is what people read (docs/metadata.md, Categories).
CATEGORIES = {
    "console-ports": "Console game ports",
    "pc-ports": "PC game ports",
    "homebrew-games": "Homebrew games",
    "emulators": "Emulators",
    "streaming": "Game streaming",
    "video": "Video & TV",
    "music": "Music & audio",
    "ai": "AI",
    "utilities": "Utilities",
    "tools": "Tools & tests",
    "showcases": "Showcases",
}
# Fields a record may carry besides FIELDS while they are being introduced; checked when present.
OPTIONAL_FIELDS = ("category",)
MAX_FILE_BYTES = 8192
MAX_LENGTH = {
    "titleid": 9, "name": 64, "kind": 4, "category": 16, "description": 200, "license": 64,
    "author": 64, "version": 32, "source_repo": 200, "artifact_url": 500,
    "sha256": 64, "icon_url": 500,
}
# Title IDs that templates ship with; publishing under them guarantees collisions.
RESERVED_TITLE_IDS = {"PPSA99999": "the ps5-native-app-boilerplate default"}

TITLE_ID = re.compile(r"[A-Z]{4}[0-9]{5}")
RECORD_PATH = re.compile(r"apps/[A-Z]{4}[0-9]{5}\.json")
SHA256 = re.compile(r"[0-9a-f]{64}")
VERSION = re.compile(r"[0-9A-Za-z][0-9A-Za-z.+_-]*")
LICENSE = re.compile(r"[A-Za-z0-9.+-]+(?: (?:AND|OR|WITH) [A-Za-z0-9.+-]+)*")
REPO_PART = re.compile(r"[A-Za-z0-9_.-]+")
ASSET_NAME = re.compile(r"[^/?#%\s]+\.(?:zip|ffpfsc|ffpkg)")
TAG = re.compile(r"[^/?#\s]+")
ICON_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp")
# Unicode categories rejected in text: controls, invisible formatting (including
# bidirectional overrides), surrogates, private use, unassigned, line separators.
BAD_CATEGORIES = {"Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp"}


@dataclass(frozen=True)
class Record:
    path: Path
    data: dict

    @property
    def titleid(self) -> str:
        return self.data["titleid"]

    @property
    def reserved(self) -> bool:
        """True for a title ID reservation (no release yet), shown as coming soon."""
        return self.data["artifact_url"] is None

    @property
    def owner(self) -> str:
        return repo_parts(self.data["source_repo"])[0]

    @property
    def repo(self) -> str:
        return repo_parts(self.data["source_repo"])[1]

    @property
    def tag(self) -> str:
        return release_parts(self.data)[0]

    @property
    def asset_name(self) -> str:
        return release_parts(self.data)[1]


def repo_parts(source_repo: str) -> tuple[str, str]:
    owner, repo = urlsplit(source_repo).path.strip("/").split("/")
    return owner, repo


def release_parts(data: dict) -> tuple[str, str]:
    """Return the (tag, asset name) encoded in a validated artifact_url."""
    suffix = data["artifact_url"][len(data["source_repo"] + "/releases/download/"):]
    tag, asset = suffix.split("/")
    return unquote(tag), asset


def tag_version(tag: str) -> str:
    """The version a release tag names: the tag without a leading v before a digit (v1.2 -> 1.2)."""
    return tag[1:] if re.fullmatch(r"[vV][0-9].*", tag) else tag


def version_from_tag(tag: str) -> tuple[str, ...]:
    """Accepted `version` values for a release tag: the tag, or the tag without a leading v."""
    return (tag,) if tag_version(tag) == tag else (tag_version(tag), tag)


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def text_problem(value: str) -> str | None:
    for char in value:
        if unicodedata.category(char) in BAD_CATEGORIES:
            return f"contains a disallowed character U+{ord(char):04X}"
    if unicodedata.normalize("NFC", value) != value:
        return "is not NFC-normalized Unicode"
    if value.strip() != value:
        return "has leading or trailing whitespace"
    return None


def _check_fields(data: dict) -> list[str]:
    """Validate values; the field set was checked by the caller."""
    problems = []
    reservation = data["artifact_url"] is None
    if reservation:
        for field in RESERVATION_NULL:
            if data[field] is not None:
                problems.append(f"{field} must be null in a reservation (artifact_url is null)")
    for field, value in data.items():
        if value is None:
            if not (reservation and field in RESERVATION_NULL + RESERVATION_NULLABLE):
                problems.append(f"{field} must not be null" + (
                    "" if reservation else "; only reservations (artifact_url null) may leave fields null"))
            continue
        if not isinstance(value, str):
            problems.append(f"{field} must be a string")
            continue
        if not value:
            problems.append(f"{field} must not be empty")
            continue
        if len(value) > MAX_LENGTH[field]:
            problems.append(f"{field} is longer than {MAX_LENGTH[field]} characters")
        issue = text_problem(value)
        if issue:
            problems.append(f"{field} {issue}")
    if problems:
        return problems

    if not TITLE_ID.fullmatch(data["titleid"]):
        problems.append("titleid must be four uppercase letters and five digits, e.g. PPSA01234")
    elif data["titleid"] in RESERVED_TITLE_IDS:
        problems.append(f"titleid {data['titleid']} is reserved ({RESERVED_TITLE_IDS[data['titleid']]}); "
                        "choose a unique title ID")
    if data["kind"] not in KINDS:
        problems.append(f"kind must be one of: {', '.join(KINDS)}")
    if "category" in data and data["category"] not in CATEGORIES:
        problems.append(f"category must be one of: {', '.join(CATEGORIES)}")
    if data["version"] is not None and not VERSION.fullmatch(data["version"]):
        problems.append("version may contain only letters, digits and . + _ -")
    if data["license"] is not None and not LICENSE.fullmatch(data["license"]):
        problems.append("license must be an SPDX identifier or expression, e.g. GPL-3.0 or MIT OR Apache-2.0")
    if data["sha256"] is not None and not SHA256.fullmatch(data["sha256"]):
        problems.append("sha256 must be 64 lowercase hexadecimal characters")

    if reservation:
        return problems

    source = urlsplit(data["source_repo"])
    parts = source.path.strip("/").split("/")
    source_ok = (
        source.scheme == "https" and source.netloc == "github.com"
        and source.path == "/" + "/".join(parts) and len(parts) == 2
        and all(REPO_PART.fullmatch(p) and p not in {".", ".."} for p in parts)
        and not source.query and not source.fragment
    )
    if not source_ok:
        problems.append("source_repo must be https://github.com/<owner>/<repository>")
    else:
        prefix = data["source_repo"] + "/releases/download/"
        artifact = urlsplit(data["artifact_url"])
        suffix = data["artifact_url"][len(prefix):] if data["artifact_url"].startswith(prefix) else ""
        tag, _, asset = suffix.partition("/")
        if not (suffix and artifact.scheme == "https" and not artifact.query and not artifact.fragment
                and TAG.fullmatch(tag) and ASSET_NAME.fullmatch(asset)):
            problems.append("artifact_url must be <source_repo>/releases/download/<tag>/<asset> "
                            "ending in .zip, .ffpfsc or .ffpkg")
        elif unquote(tag) == "latest":
            problems.append("artifact_url must name a specific release tag, not 'latest'")
        elif data["version"] not in version_from_tag(unquote(tag)):
            choices = " or ".join(repr(v) for v in version_from_tag(unquote(tag)))
            problems.append(f"version must match the release tag {unquote(tag)!r} in artifact_url: use {choices}")

    if data["icon_url"] is not None:
        icon = urlsplit(data["icon_url"])
        if not (icon.scheme == "https" and icon.hostname and not icon.username and not icon.password
                and not icon.fragment and icon.path.lower().endswith(ICON_EXTENSIONS)):
            problems.append("icon_url must be a direct HTTPS link ending in .png, .jpg, .jpeg or .webp")
    return problems


def _field_set_problems(data: dict) -> list[str]:
    problems = []
    missing = [f for f in FIELDS if f not in data]
    extra = sorted(set(data) - set(FIELDS) - set(OPTIONAL_FIELDS))
    if missing:
        problems.append(f"missing field(s): {', '.join(missing)}")
    if extra:
        problems.append(f"unexpected field(s): {', '.join(extra)}")
    return problems


def record_problems(data: dict) -> list[str]:
    """Every field-level problem with a record's data (catalog-wide rules aside)."""
    return _field_set_problems(data) or _check_fields(data)


def load_record(path: Path, report: Report, display: str | None = None) -> Record | None:
    """Parse and validate one record file; report problems and return None on failure."""
    name = display or f"apps/{path.name}"
    if path.is_symlink() or not path.is_file():
        report.error(name, "must be a regular file")
        return None
    if path.stat().st_size > MAX_FILE_BYTES:
        report.error(name, f"is larger than {MAX_FILE_BYTES} bytes")
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_keys)
    except (UnicodeDecodeError, ValueError) as error:
        report.error(name, f"is not valid UTF-8 JSON: {error}")
        return None
    if not isinstance(data, dict):
        report.error(name, "must contain a single JSON object")
        return None
    problems = _field_set_problems(data) or _check_fields(data)
    if not problems and path.stem != data["titleid"]:
        problems.append(f"filename must be {data['titleid']}.json to match titleid")
    for problem in problems:
        report.error(name, problem)
    return None if problems else Record(path, data)


def load_catalog(apps_dir: Path, report: Report) -> list[Record]:
    """Validate every record plus catalog-wide uniqueness rules."""
    if not apps_dir.is_dir():
        report.error("apps", "directory is missing")
        return []
    records = []
    for path in sorted(apps_dir.iterdir()):
        if path.suffix != ".json" or not TITLE_ID.fullmatch(path.stem):
            report.error(f"apps/{path.name}", "only <TITLEID>.json record files belong in apps/")
            continue
        record = load_record(path, report)
        if record:
            records.append(record)
    if not records and not report.failed:
        report.error("apps", "contains no records")

    for field, normalize in (("name", str.casefold), ("artifact_url", str), ("sha256", str)):
        seen: dict[str, str] = {}
        for record in records:
            if record.data[field] is None:
                continue
            key = normalize(record.data[field])
            if key in seen:
                report.error(f"apps/{record.path.name}", f"{field} duplicates {seen[key]}")
            else:
                seen[key] = f"apps/{record.path.name}"
    return records

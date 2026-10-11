"""The catalog's news: short messages from its maintainers, shown by the store.

The source is news.json at the top of the repository: a list of items, each
with an id, a date, a title and a body. The build publishes the newest twenty
as api/v1/news.json. It is signed by itself (news.sig) and is not listed in
manifest.json: released stores refuse a manifest that names a file they don't
know.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from .report import Report

FILE = "news.json"
PUBLISHED = 20
FIELDS = ("id", "date", "title", "body")
ID = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")
TITLE_LIMIT, BODY_LIMIT = 120, 2000


def load(path: Path, report: Report) -> list[dict]:
    """The items of news.json, newest first. Problems are errors on the report; a missing file is no news."""
    if not path.is_file():
        return []
    try:
        items = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        report.error(FILE, f"not valid JSON: {error}")
        return []
    if not isinstance(items, list):
        report.error(FILE, "must be a list of items")
        return []
    seen, good = set(), []
    for number, item in enumerate(items, 1):
        where = f"item {number}"
        if not isinstance(item, dict) or sorted(item) != sorted(FIELDS) or \
                not all(isinstance(item[field], str) for field in FIELDS):
            report.error(FILE, f"{where}: needs exactly the text fields {', '.join(FIELDS)}")
            continue
        if not ID.fullmatch(item["id"]) or item["id"] in seen:
            report.error(FILE, f"{where}: id must be unique, lower-case letters, digits and hyphens (64 at most)")
            continue
        try:
            when = datetime.strptime(item["date"], "%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            report.error(FILE, f"{where}: date must look like 2026-10-11T09:00:00Z")
            continue
        title, body = item["title"].strip(), item["body"].strip()
        if not title or len(title) > TITLE_LIMIT or "\n" in title:
            report.error(FILE, f"{where}: title must be one line of at most {TITLE_LIMIT} characters")
            continue
        if not body or len(body) > BODY_LIMIT:
            report.error(FILE, f"{where}: body must have text, at most {BODY_LIMIT} characters")
            continue
        seen.add(item["id"])
        good.append((when, {"id": item["id"], "date": item["date"], "title": title, "body": body}))
    good.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _, item in good]

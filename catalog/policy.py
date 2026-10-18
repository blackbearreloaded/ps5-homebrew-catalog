"""Pull-request rules for community submissions."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .github import GitHub, GitHubError
from .records import MAX_RESERVATIONS_PER_ACCOUNT, RECORD_PATH, Record
from .report import Report
from .updates import is_release_bump

MAINTAINER_ASSOCIATIONS = {"OWNER", "MEMBER", "COLLABORATOR"}
REGULAR_FILE_MODE = "100644"


@dataclass(frozen=True)
class Change:
    status: str  # A (added), M (modified) or D (deleted)
    path: str
    mode: str | None = None  # git mode of the new blob, None when deleted


def is_maintainer(author_association: str) -> bool:
    return author_association in MAINTAINER_ASSOCIATIONS


def check_changes(changes: list[Change], maintainer: bool, report: Report) -> list[Change]:
    """Validate which files a PR touches; return the record changes to verify."""
    records = []
    for change in changes:
        if change.path.startswith("apps/"):
            if not RECORD_PATH.fullmatch(change.path):
                report.error(change.path, "only apps/<TITLEID>.json files may be added under apps/")
                continue
            if change.status != "D" and change.mode != REGULAR_FILE_MODE:
                report.error(change.path, "must be a regular, non-executable file")
                continue
            if change.status == "D" and not maintainer:
                report.error(change.path, "removing an app is done by maintainers; open a withdrawal issue")
                continue
            records.append(change)
        elif not maintainer:
            report.error(change.path, "community pull requests may change only apps/<TITLEID>.json; "
                                      "open an issue for other changes")
    if not maintainer and len([c for c in records if c.status != "D"]) > 1:
        report.error("apps", "submit one app per pull request")
    if not changes:
        report.error("pull request", "changes no files")
    return records


def is_bump(old: Record, new: Record, github: GitHub, report: Report, name: str) -> bool:
    try:
        bump = is_release_bump(old, new, github)
    except GitHubError as error:
        report.error(name, f"could not check the repository's releases: {error}")
        return False
    if bump:
        report.notice(name, f"updates {new.titleid} to the newest release of {new.owner}/{new.repo}; "
                            "allowed from any account")
    return bump


def derivative_notes(new: Record, listed: list[Record], github: GitHub) -> list[str]:
    """What a reviewer should ask about a new listing that builds on an app already in the catalog.

    The review policy lists a fork or derivative only when it is a distinct app, and a derivative
    names what it builds on in its description, not in its name. These are notes for the reviewer,
    never errors: a fork that adds a renderer or features of its own is welcome.
    """
    notes = []
    others = [r for r in listed if r.titleid != new.titleid]
    if not new.reserved:
        try:
            repo = github.repo(new.owner, new.repo) or {}
        except GitHubError:
            repo = {}
        if not isinstance(repo, dict):
            repo = {}
        if repo.get("fork"):
            listed_repos = {(r.owner.casefold(), r.repo.casefold()): r for r in others if not r.reserved}
            upstreams = [u.get("full_name") for u in (repo.get("parent") or {}, repo.get("source") or {})]
            upstreams = [u for u in dict.fromkeys(upstreams) if u and "/" in u]
            match = next(((u, listed_repos[tuple(u.casefold().split("/", 1))]) for u in upstreams
                          if tuple(u.casefold().split("/", 1)) in listed_repos), None)
            if match:
                notes.append(f"its repository is a fork of {match[0]}, which is listed as {match[1].data['name']} "
                             f"({match[1].titleid}): the review policy lists it only as a distinct app, so ask "
                             "what it does that the listed app doesn't")
            else:
                notes.append(f"its repository is a fork of {upstreams[0] if upstreams else 'another repository'}: "
                             "check that it is a distinct app, not a rebuild or a new name and theme")
    for other in others:
        name = other.data["name"]
        if (len(name) >= 4 and name.casefold() != new.data["name"].casefold()
                and re.search(rf"(?<!\w){re.escape(name)}(?!\w)", new.data["name"], re.IGNORECASE)):
            notes.append(f"its name contains {name!r}, the name of {other.titleid}: a derivative names the app "
                         "it builds on in its description, not in its name")
    return notes


def check_publisher(author: str, maintainer: bool, old: Record | None, new: Record,
                    github: GitHub, report: Report, holder: str | None = None, held: int = 0) -> None:
    """Decide whether the PR author may create or change this record.

    Releases belong to the owner of source_repo (or public members of that
    organization). Reservations have no source_repo; they belong to the account
    that added them (holder, from the file's git history). held is how many
    other reservations the author already holds.
    """
    name = f"apps/{new.path.name}"
    if old and old.reserved:
        if holder is None and not maintainer:
            report.error(name, f"could not determine who reserved {new.titleid}; a maintainer must review")
            return
        if holder and holder.casefold() != author.casefold():
            if maintainer:
                report.warning(name, f"changes {new.titleid}, which is reserved by @{holder}")
            else:
                report.error(name, f"{new.titleid} is reserved by @{holder}; only that account can "
                                   "update or release it")
                return
    elif old and not maintainer and not new.reserved and is_bump(old, new, github, report, name):
        return
    elif old and new.reserved:
        if not maintainer:
            report.error(name, f"{new.titleid} is already released; it can't go back to a reservation")
            return
    elif old and old.owner.casefold() != new.owner.casefold():
        if maintainer:
            report.warning(name, f"moves {new.titleid} from {old.owner} to {new.owner}")
        else:
            report.error(name, f"{new.titleid} is registered to {old.owner}; ownership transfers "
                               "require a maintainer")
            return
    if new.reserved:
        if old is None and not maintainer and held >= MAX_RESERVATIONS_PER_ACCOUNT:
            report.error(name, f"@{author} already holds {MAX_RESERVATIONS_PER_ACCOUNT} reservations; "
                               "release or remove one first")
        return
    if maintainer:
        return
    if author.casefold() == new.owner.casefold():
        return
    try:
        if github.account_type(new.owner) == "Organization" and github.is_public_member(new.owner, author):
            return
    except GitHubError as error:
        report.error(name, f"could not confirm the publisher: {error}")
        return
    report.error(name, f"@{author} does not own {new.owner}/{new.repo}; open the pull request from "
                       f"the {new.owner} account or make your membership of {new.owner} public")

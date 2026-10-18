"""Which pull requests are merged without a maintainer.

Two kinds are: a developer moving their own app to its newest release, and a developer who
already has an app in the catalog adding another one of their own.

Everything else waits for a maintainer, and so does anything this module is unsure about: a
removal, a change to what the app is called or where it comes from, a pull request from an
account that does not own the app's repository, or a check that failed.
"""

from __future__ import annotations

from .github import GitHub, GitHubError
from .policy import REGULAR_FILE_MODE, Change
from .records import RECORD_PATH, Record
from .updates import is_release_bump


def owns(author: str, record: Record, github: GitHub) -> bool:
    """True when the author is the owner of the app's repository, or a public member of the owning organization."""
    if author.casefold() == record.owner.casefold():
        return True
    return github.account_type(record.owner) == "Organization" and github.is_public_member(record.owner, author)


def has_listed_app(author: str, listed: list[Record], github: GitHub) -> bool:
    """True when the author owns, as owner or public organization member, an app that is already listed."""
    owners = {}
    for record in listed:
        if not record.reserved:
            owners.setdefault(record.owner.casefold(), record)
    if author.casefold() in owners:
        return True
    return any(owns(author, record, github) for record in owners.values())


def new_app_reasons(author: str, changes: list[Change], new: Record | None, listed: list[Record],
                    github: GitHub) -> list[str]:
    """Why a pull request that adds an app is left for a maintainer; an empty list means it may be merged.

    new is the proposed record, for a pull request whose only change is one added record; listed is
    the catalog on the base branch.
    """
    if len(changes) != 1:
        return [f"it changes {len(changes)} files; a new app is one record"]
    change = changes[0]
    if not RECORD_PATH.fullmatch(change.path):
        return [f"it changes {change.path}, which is not an app's record"]
    if change.status != "A":
        return ["it is not a new app"]
    if change.mode != REGULAR_FILE_MODE:
        return ["the record is not a regular file"]
    if new is None:
        return ["the proposed record could not be read"]
    if new.reserved:
        return ["it adds a reservation"]

    reasons = []
    try:
        if not owns(author, new, github):
            return [f"@{author} does not own {new.owner}/{new.repo}"]
        if not has_listed_app(author, listed, github):
            reasons.append(f"@{author} has no app in the catalog yet")
    except GitHubError as error:
        return [f"GitHub could not be asked: {error}"]
    if not new.data["artifact_url"].startswith(new.data["source_repo"].rstrip("/") + "/releases/download/"):
        reasons.append("the file is not a release file of the app's repository")
    icons = f"https://raw.githubusercontent.com/{new.owner}/{new.repo}/"
    if not new.data["icon_url"].casefold().startswith(icons.casefold()):
        reasons.append("the icon is at an address outside the app's repository")
    return reasons


def bump_reasons(author: str, changes: list[Change], old: Record | None, new: Record | None,
                 github: GitHub) -> list[str]:
    """Why this pull request is left for a maintainer; an empty list means it may be merged.

    old and new are the listed record and the proposed one, for a pull request whose only change
    is one modified record; they are None otherwise or when a record could not be read.
    """
    if len(changes) != 1:
        return [f"it changes {len(changes)} files; a release bump changes one record"]
    change = changes[0]
    if not RECORD_PATH.fullmatch(change.path):
        return [f"it changes {change.path}, which is not an app's record"]
    if change.status == "A":
        return ["it adds a new app"]
    if change.status != "M":
        return ["it removes an app"]
    if change.mode != REGULAR_FILE_MODE:
        return ["the record is not a regular file"]
    if old is None or new is None:
        return ["the listed or the proposed record could not be read"]
    if old.reserved or new.reserved:
        return ["it changes a reservation"]

    reasons = []
    try:
        if not is_release_bump(old, new, github):
            reasons.append("it changes more than the release (version, file, sha256, icon), "
                           f"or the release is not the newest of {new.owner}/{new.repo}")
        if not owns(author, new, github):
            reasons.append(f"@{author} does not own {new.owner}/{new.repo}")
    except GitHubError as error:
        return [f"GitHub could not be asked: {error}"]
    if old.data["sha256"] == new.data["sha256"] or old.data["artifact_url"] == new.data["artifact_url"]:
        reasons.append("it does not point at a new file")
    if not new.data["artifact_url"].startswith(new.data["source_repo"].rstrip("/") + "/releases/download/"):
        reasons.append("the file is not a release file of the app's repository")
    icons = f"https://raw.githubusercontent.com/{new.owner}/{new.repo}/"
    if new.data["icon_url"] != old.data["icon_url"] and not new.data["icon_url"].casefold().startswith(icons.casefold()):
        reasons.append("the icon moves to an address outside the app's repository")
    return reasons

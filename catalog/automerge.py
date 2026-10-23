"""Which pull requests are merged without a maintainer.

Four kinds are: a developer moving their own app to its newest release, a developer releasing
the title ID they reserved, a developer who already has an app in the catalog adding another one
of their own, and the catalog bot's own
pull request that moves apps to their newest release (every record in it checked like a
developer's own bump).

Everything else waits for a maintainer, and so does anything this module is unsure about: a
removal, a change to what the app is called or where it comes from, a pull request from an
account that does not own the app's repository, or a check that failed.
"""

from __future__ import annotations

from .github import GitHub, GitHubError
from .policy import REGULAR_FILE_MODE, Change
from .records import RECORD_PATH, Record
from .updates import is_release_bump, newest_release

# The account the catalog's GitHub App acts as, and the one branch it keeps its pending updates on
# (the withdrawals branch is never merged here).
UPDATE_BOT = "ps5-catalog-bot[bot]"
UPDATE_BRANCH = "catalog-update/all"


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
    # An icon inside the release file needs no address: the file itself is checked above.
    if new.data["icon_url"] and not new.data["icon_url"].casefold().startswith(icons.casefold()):
        reasons.append("the icon is at an address outside the app's repository")
    return reasons


def release_reservation_reasons(author: str, holder: str | None, new: Record, github: GitHub) -> list[str]:
    """Why a reservation's first release is not the holder's own, newest release of their repository."""
    if new.reserved:
        return ["it changes a reservation"]
    if holder is None:
        return ["could not determine who reserved the title ID"]
    if holder.casefold() != author.casefold():
        return [f"the title ID is reserved by @{holder}, not @{author}"]
    reasons = []
    try:
        if not owns(author, new, github):
            return [f"@{author} does not own {new.owner}/{new.repo}"]
        release = newest_release(github, new.owner, new.repo)
        if not release or release.get("tag_name") != new.tag:
            reasons.append(f"the release is not the newest of {new.owner}/{new.repo}")
    except GitHubError as error:
        return [f"GitHub could not be asked: {error}"]
    if not new.data["artifact_url"].startswith(new.data["source_repo"].rstrip("/") + "/releases/download/"):
        reasons.append("the file is not a release file of the app's repository")
    icons = f"https://raw.githubusercontent.com/{new.owner}/{new.repo}/"
    if new.data["icon_url"] and not new.data["icon_url"].casefold().startswith(icons.casefold()):
        reasons.append("the icon is at an address outside the app's repository")
    return reasons


def bump_reasons(author: str, changes: list[Change], old: Record | None, new: Record | None,
                 github: GitHub, holder: str | None = None) -> list[str]:
    """Why this pull request is left for a maintainer; an empty list means it may be merged.

    old and new are the listed record and the proposed one, for a pull request whose only change
    is one modified record; they are None otherwise or when a record could not be read. holder is
    who reserved the title ID, when old is a reservation.
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
    if old.reserved:
        return release_reservation_reasons(author, holder, new, github)
    if new.reserved:
        return ["it changes a reservation"]
    return release_bump_reasons(old, new, github, author)


def update_pull_reasons(author: str, head_ref: str, from_fork: bool, changes: list[Change],
                        pairs: list[tuple[Record | None, Record | None]], github: GitHub) -> list[str]:
    """Why the catalog bot's pull request of pending updates is left for a maintainer.

    It is merged only when it comes from the bot, from its own branch of this repository, and every
    change is a release bump that passes the same checks as a developer's own bump."""
    if author != UPDATE_BOT:
        return [f"@{author} is not the catalog bot"]
    if head_ref != UPDATE_BRANCH or from_fork:
        return [f"it is not the bot's {UPDATE_BRANCH} branch of this repository"]
    if not changes or len(changes) != len(pairs):
        return ["it changes no app's record"]
    reasons = []
    for change, (old, new) in zip(changes, pairs):
        if not RECORD_PATH.fullmatch(change.path):
            reasons.append(f"it changes {change.path}, which is not an app's record")
        elif change.status != "M":
            reasons.append(f"{change.path}: it adds or removes an app")
        elif change.mode != REGULAR_FILE_MODE:
            reasons.append(f"{change.path}: the record is not a regular file")
        elif old is None or new is None:
            reasons.append(f"{change.path}: the listed or the proposed record could not be read")
        elif old.reserved or new.reserved:
            reasons.append(f"{change.path}: it changes a reservation")
        else:
            reasons += [f"{change.path}: {reason}" for reason in release_bump_reasons(old, new, github)]
    return reasons


def release_bump_reasons(old: Record, new: Record, github: GitHub, author: str | None = None) -> list[str]:
    """Why one record's change is not a plain move to its repository's newest release.

    With an author, it must also be the app's developer; the bot's pull request passes none."""
    reasons = []
    try:
        # The description may change only with an author, who must also own the repository.
        if not is_release_bump(old, new, github, ("description",) if author is not None else ()):
            reasons.append("it changes more than the release (version, file, sha256, icon, description), "
                           f"or the release is not the newest of {new.owner}/{new.repo}")
        if author is not None and not owns(author, new, github):
            reasons.append(f"@{author} does not own {new.owner}/{new.repo}")
    except GitHubError as error:
        return [f"GitHub could not be asked: {error}"]
    if old.data["sha256"] == new.data["sha256"] or old.data["artifact_url"] == new.data["artifact_url"]:
        reasons.append("it does not point at a new file")
    if not new.data["artifact_url"].startswith(new.data["source_repo"].rstrip("/") + "/releases/download/"):
        reasons.append("the file is not a release file of the app's repository")
    icons = f"https://raw.githubusercontent.com/{new.owner}/{new.repo}/"
    if (new.data["icon_url"] and new.data["icon_url"] != old.data["icon_url"]
            and not new.data["icon_url"].casefold().startswith(icons.casefold())):
        reasons.append("the icon moves to an address outside the app's repository")
    return reasons

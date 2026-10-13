"""Comments and likes: one GitHub Discussion per listed app, and the JSON that clients read.

GitHub holds the state. A listed app's discussion carries its title ID in a hidden marker; the
replies are the app's comments and the discussion's upvotes are its likes. This
module decides what to create, rename, lock or bring back, and turns the discussions into the two
kinds of file the website and the store show: v1/index.json and v1/apps/<TITLEID>.json.

Everything people write is untrusted: it leaves here as short plain text, and whoever shows it
must still treat it as such.
"""

from __future__ import annotations

import re
import time
import unicodedata
from dataclasses import dataclass, field

from .github import GitHub, GitHubError
from .records import Record

SCHEMA = 1
ACTIVE = "App comments"      # the category the discussions of listed apps are in
WITHDRAWN = "Withdrawn"      # where a discussion goes, locked, when its app leaves the catalog
LATEST = 10                  # comments kept per app
MAX_TEXT = 500               # characters kept per comment
SITE = "https://homebrew.page"
MARKER = re.compile(r"<!-- titleid: ([A-Z]{4}[0-9]{5}) -->")
PAUSE = 3.0                  # seconds between two discussions created in a row (GitHub's content limit)

_URL = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)

SETUP = """query($owner: String!, $name: String!) {
  repository(owner: $owner, name: $name) {
    id hasDiscussionsEnabled
    discussionCategories(first: 25) { nodes { id name } }
  }
}"""

LIST = """query($owner: String!, $name: String!, $after: String) {
  repository(owner: $owner, name: $name) {
    discussions(first: 50, after: $after) {
      pageInfo { hasNextPage endCursor }
      nodes {
        id number title body url locked
        category { name }
        upvoteCount
        comments(last: %d) {
          totalCount
          nodes { author { login } createdAt bodyText isMinimized }
        }
      }
    }
  }
}""" % LATEST

CREATE = """mutation($repository: ID!, $category: ID!, $title: String!, $body: String!) {
  createDiscussion(input: {repositoryId: $repository, categoryId: $category, title: $title, body: $body}) {
    discussion { number }
  }
}"""

UPDATE = """mutation($id: ID!, $title: String, $category: ID) {
  updateDiscussion(input: {discussionId: $id, title: $title, categoryId: $category}) { discussion { number } }
}"""

LOCK = "mutation($id: ID!) { lockLockable(input: {lockableId: $id}) { clientMutationId } }"
UNLOCK = "mutation($id: ID!) { unlockLockable(input: {lockableId: $id}) { clientMutationId } }"


@dataclass
class Thread:
    """One app's discussion, as far as this module needs it."""
    id: str
    number: int
    url: str
    title: str
    titleid: str
    category: str
    locked: bool = False
    likes: int = 0
    comments: int = 0
    latest: list[dict] = field(default_factory=list)


def read_scope(value: str) -> set[str]:
    """Logins from COMMENTS_SCOPE whose comments are left out: names separated by commas or white space."""
    return {name.strip().lstrip("@").casefold() for name in value.replace(",", " ").split() if name.strip()}


def clean(text: str) -> str:
    """A comment as one line of plain text: no addresses, no control or formatting characters, capped."""
    text = _URL.sub("", text or "")
    text = "".join(" " if c.isspace() else c for c in text if c.isspace() or not unicodedata.category(c).startswith("C"))
    text = " ".join(text.split())
    return text if len(text) <= MAX_TEXT else text[:MAX_TEXT - 1].rstrip() + "…"


def thread_title(record: Record) -> str:
    return f"{record.data['name']} ({record.titleid})"


def thread_body(record: Record) -> str:
    return "\n".join([
        f"Comments and likes for **{record.data['name']}**, listed at {SITE}/app/{record.titleid}/.",
        "",
        "Upvote this discussion (the arrow beside its title) to like the app, and reply below to comment.",
        "",
        f"The catalog only lists this app; its developer maintains it at {record.data['source_repo']}. "
        "Bug reports belong there.",
        "",
        f"<!-- titleid: {record.titleid} -->",
    ])


def read_threads(nodes: list[dict], out_of_scope: frozenset[str] | set[str] = frozenset()) -> dict[str, Thread]:
    """The discussions that carry a title ID marker, by title ID. Of two with the same one, the older counts."""
    threads: dict[str, Thread] = {}
    for node in sorted(nodes, key=lambda n: n["number"]):
        marker = MARKER.search(node.get("body") or "")
        if not marker or marker.group(1) in threads:
            continue
        latest = []
        for comment in reversed(node["comments"]["nodes"]):      # newest first
            author = (comment.get("author") or {}).get("login") or "ghost"
            text = clean(comment.get("bodyText") or "")
            if comment.get("isMinimized") or author.casefold() in out_of_scope or not text:
                continue
            latest.append({"author": author, "date": comment["createdAt"], "text": text})
        threads[marker.group(1)] = Thread(
            id=node["id"], number=node["number"], url=node["url"], title=node["title"],
            titleid=marker.group(1), category=(node.get("category") or {}).get("name", ""),
            locked=bool(node.get("locked")), likes=node.get("upvoteCount") or 0,
            comments=node["comments"]["totalCount"], latest=latest)
    return threads


def plan(records: list[Record], threads: dict[str, Thread]) -> list[tuple]:
    """What has to change so that every listed app, and no other, has an open discussion.

    ("create", record), ("restore", thread), ("rename", thread, title) or ("withdraw", thread).
    A discussion a maintainer locked by hand stays locked: only the Withdrawn category is undone.
    """
    listed = {r.titleid: r for r in records if not r.reserved}
    actions: list[tuple] = []
    for titleid, record in sorted(listed.items()):
        thread = threads.get(titleid)
        if thread is None:
            actions.append(("create", record))
            continue
        if thread.category == WITHDRAWN:
            actions.append(("restore", thread))
        if thread.title != thread_title(record):
            actions.append(("rename", thread, thread_title(record)))
    for titleid, thread in sorted(threads.items()):
        if titleid not in listed and thread.category != WITHDRAWN:
            actions.append(("withdraw", thread))
    return actions


def describe(action: tuple) -> str:
    kind, subject = action[0], action[1]
    if kind == "create":
        return f"create the discussion of {thread_title(subject)}"
    if kind == "rename":
        return f"rename discussion #{subject.number} to {action[2]}"
    if kind == "restore":
        return f"unlock discussion #{subject.number}: {subject.titleid} is listed again"
    return f"lock discussion #{subject.number}: {subject.titleid} is no longer listed"


def payload(records: list[Record], threads: dict[str, Thread]) -> dict[str, dict]:
    """The files to publish, by path: the index, and one file per listed app that has a discussion."""
    listed = sorted(r.titleid for r in records if not r.reserved)
    files: dict[str, dict] = {}
    index: dict[str, dict] = {}
    for titleid in listed:
        thread = threads.get(titleid)
        if thread is None or thread.category == WITHDRAWN:
            continue
        index[titleid] = {"discussion": thread.number, "url": thread.url,
                          "likes": thread.likes, "comments": thread.comments}
        files[f"v1/apps/{titleid}.json"] = {"schema": SCHEMA, "titleid": titleid, **index[titleid],
                                            "latest": thread.latest}
    files["v1/index.json"] = {"schema": SCHEMA, "apps": index}
    return files


def setup(github: GitHub, owner: str, name: str) -> tuple[str, dict[str, str]] | None:
    """(repository ID, category IDs by name), or None while Discussions aren't on."""
    repository = github.graphql(SETUP, {"owner": owner, "name": name}).get("repository")
    if not repository or not repository["hasDiscussionsEnabled"]:
        return None
    return repository["id"], {c["name"]: c["id"] for c in repository["discussionCategories"]["nodes"]}


def list_nodes(github: GitHub, owner: str, name: str) -> list[dict]:
    nodes, after = [], None
    while True:
        page = github.graphql(LIST, {"owner": owner, "name": name, "after": after})["repository"]["discussions"]
        nodes += page["nodes"]
        if not page["pageInfo"]["hasNextPage"]:
            return nodes
        after = page["pageInfo"]["endCursor"]


def apply(actions: list[tuple], github: GitHub, repository: str, categories: dict[str, str]) -> None:
    """Carry the plan out. A failure raises GitHubError and leaves the rest for the next run."""
    created = False
    for action in actions:
        kind, subject = action[0], action[1]
        if kind == "create":
            if created:
                time.sleep(PAUSE)
            github.graphql(CREATE, {"repository": repository, "category": categories[ACTIVE],
                                    "title": thread_title(subject), "body": thread_body(subject)})
            created = True
        elif kind == "rename":
            github.graphql(UPDATE, {"id": subject.id, "title": action[2]})
        elif kind == "restore":
            github.graphql(UPDATE, {"id": subject.id, "category": categories[ACTIVE]})
            if subject.locked:
                github.graphql(UNLOCK, {"id": subject.id})
        elif kind == "withdraw":
            if WITHDRAWN in categories:
                github.graphql(UPDATE, {"id": subject.id, "category": categories[WITHDRAWN]})
            if not subject.locked:
                github.graphql(LOCK, {"id": subject.id})
        else:
            raise GitHubError(f"unknown action {kind}")

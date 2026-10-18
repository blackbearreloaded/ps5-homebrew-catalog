"""Find native PS5 apps on public GitHub that the catalog doesn't list yet.

Runs daily in CI (.github/workflows/discovery.yml). Every candidate that passes
all automated checks becomes a listing pull request (one per app, branch
listing/<TITLEID>) that a maintainer reviews with
docs/maintainers/listing-runbook.md and merges by hand; the job never merges or
pushes to main. Candidates that need a person first are summarised in one
tracking issue that the job rewrites. It only reads other repositories: no
downloads, no contact with developers.

A repository becomes a candidate through a search hit or because its owner
already has a listed or strongly signalled app. It is then checked cheapest
first: already listed or ignored, then a published release with a .zip, .ffpkg
or .ffpfsc file, then the full `draft` checks (param.json, title ID, digest,
icon, license). The judgment fields `draft` leaves open are filled with
labelled guesses (kind from keywords, description from the repository's About
text or README) for the reviewer to confirm.
"""

from __future__ import annotations

import json
import re
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .draft import ARTIFACT_EXTENSIONS, Draft, draft_record
from .github import GitHub, GitHubError
from .records import BAD_CATEGORIES, MAX_LENGTH, load_catalog, record_problems
from .report import Report

# (query, signal shown in the report, strong: the hit itself is evidence of a native title)
CODE_QUERIES = (
    ("filename:param.json path:sce_sys PPSA", "sce_sys/param.json", True),
    ("filename:param.json titleId PPSA", "param.json titleId", True),
    ('"/data/homebrew/" PPSA extension:md', "README install path", False),   # payload loaders mention it too
    ("TITLE_ID PPSA extension:sh", "build script title ID", True),
    ("ShadowMountPlus extension:md", "mentions ShadowMountPlus", False),
    ("ffpfsc extension:md", "mentions .ffpfsc", False),
    ("ffpkg extension:md", "mentions .ffpkg", False),
)
REPO_QUERIES = (
    ("ps5 homebrew", "search: ps5 homebrew"),
    ("topic:ps5-homebrew", "topic: ps5-homebrew"),
    ("topic:ps5", "topic: ps5"),
    ("prospero in:name", "name: prospero"),
)
CODE_PAGES = 2            # 200 hits per code query; none comes close today
CODE_SEARCH_PAUSE = 7     # code search allows 10 requests a minute
MAX_OWNERS = 40
OWNER_ACTIVE_DAYS = 400
MAX_REPOS = 600           # release lookups per run, strongest candidates first
LABEL = "discovery"
TITLE = "Discovery: native PS5 apps not listed yet"
CATALOG_REPO = "darkxex/ps5-homebrew-catalog"
STATE = re.compile(r"<!-- discovery-state: (\[.*?\]) -->")
PPSA = re.compile(r"PPSA\d{5}")
REJECTED = "rejected: a listing pull request was closed without merging"
MAX_BODY = 60000
MAX_NEW_PULLS = 10         # new listing pull requests per run
# Kind guesses, checked in this order: players and emulators are apps even when they mention games.
KIND_WORDS = (
    ("app", re.compile(r"\b(emulat\w*|player|media|video|music|browser|client|retroarch|kodi|pcsx2)\b", re.I)),
    ("tool", re.compile(r"\b(tools?|toolkit|manager|explorer|installer|backup|utilit\w*|dumper|ftp|file browser)\b",
                        re.I)),
    ("game", re.compile(r"\b(games?|puzzles?|chess|arcade|platformer|shooter|doom|quake|half-life)\b", re.I)),
)
# A category from the same words; the first match wins, so the narrow ones come first.
CATEGORY_WORDS = (
    ("ai", re.compile(r"\b(llm|llama|gguf|language models?|chatbot)\b", re.I)),
    ("emulators", re.compile(r"\b(emulat\w*|retroarch|libretro|pcsx2|dolphin|ppsspp)\b", re.I)),
    ("streaming", re.compile(r"\b(remote play|moonlight|chiaki|cloud gaming|game streaming|geforce now)\b", re.I)),
    ("console-ports", re.compile(r"\b(decomp\w*|recomp\w*|n64|gamecube|wii u|your own rom|disc image)\b", re.I)),
    ("music", re.compile(r"\b(music|radio|spotify|navidrome|audio player)\b", re.I)),
    ("video", re.compile(r"\b(video|iptv|jellyfin|plex|emby|kodi|stremio|youtube|twitch|media player|movies)\b", re.I)),
    ("tools", re.compile(r"\b(tester|test patterns?|calibrat\w*|diagnos\w*|benchmark)\b", re.I)),
    ("utilities", re.compile(r"\b(file manager|explorer|ftp|backup|installer|launcher|manager|utilit\w*)\b", re.I)),
    ("pc-ports", re.compile(r"\b(source port|doom|quake|half-life|xash)\b", re.I)),
)
DEFAULT_CATEGORY = {"app": "utilities", "game": "homebrew-games", "tool": "utilities"}
MARKDOWN_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
# Release files built for a desktop OS or CPU are tools or libraries, not console titles.
DESKTOP_BUILD = re.compile(r"(?<![a-z])(linux|windows|win(32|64)|macos|osx|darwin|mac|x86_64|x64|amd64|arm64|"
                           r"aarch64|x86|i686|portable|setup)(?![a-z])", re.I)
# A param.json in one of these folders belongs to an example, not to the repository's app.
SAMPLE_FOLDER = re.compile(r"(^|/)(samples?|examples?|tests?|demos?|templates?|[\w-]*test[\w-]*)/", re.I)


@dataclass
class Candidate:
    repo: str
    signals: set[str] = field(default_factory=set)
    strong: bool = False
    pushed: str = ""
    status: str = ""          # ready, review, unreleased or a skip reason
    release: dict | None = None
    draft: Draft | None = None
    record: dict | None = None      # complete record for a listing pull request
    guesses: list[str] = field(default_factory=list)
    note: str = ""                  # pull request link or why none was opened


@dataclass
class Result:
    candidates: list[Candidate]
    warnings: list[str]
    examined: int
    started: str


def read_ignore(path: Path) -> set[str]:
    """owner/repository per line; '#' starts a comment (use it for the reason)."""
    if not path.is_file():
        return set()
    names = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        name = line.split("#", 1)[0].strip()
        if name:
            names.add(name.casefold())
    return names


def read_scope(value: str) -> set[str]:
    """The scan scope setting from DISCOVERY_SCOPE: names separated by commas or white space."""
    return {name.strip().lstrip("@").casefold() for name in value.replace(",", " ").split() if name.strip()}


def _add(found: dict[str, Candidate], repo: dict, signal: str, strong: bool,
         out_of_scope: frozenset[str] | set[str] = frozenset()) -> None:
    name = repo.get("full_name")
    if not name or repo.get("private"):
        return
    # Scope is settled first, so nothing outside it costs a lookup.
    if name.split("/")[0].casefold() in out_of_scope:
        return
    candidate = found.setdefault(name.casefold(), Candidate(name))
    candidate.signals.add(signal)
    candidate.strong = candidate.strong or strong
    candidate.pushed = max(candidate.pushed, repo.get("pushed_at") or "")
    if repo.get("fork"):
        candidate.signals.add("fork")


def collect(github: GitHub, listed_owners: set[str], warnings: list[str], sleep=time.sleep,
            out_of_scope: frozenset[str] | set[str] = frozenset()) -> dict[str, Candidate]:
    found: dict[str, Candidate] = {}
    for index, (query, signal, strong) in enumerate(CODE_QUERIES):
        for page in range(1, CODE_PAGES + 1):
            if index or page > 1:
                sleep(CODE_SEARCH_PAUSE)
            try:
                result = github.search("code", query, page)
            except GitHubError as error:
                warnings.append(f"code search `{query}` failed: {error}")
                break
            items = result.get("items", [])
            for item in items:
                _add(found, item.get("repository") or {}, signal, strong, out_of_scope)
            if len(items) < 100:
                break
    for query, signal in REPO_QUERIES:
        try:
            items = github.search("repositories", query, sort="updated").get("items", [])
        except GitHubError as error:
            warnings.append(f"repository search `{query}` failed: {error}")
            continue
        for item in items:
            if not item.get("archived"):
                _add(found, item, signal, False, out_of_scope)

    # Developers with a listed or strongly signalled app often publish more than one.
    owners = sorted((listed_owners | {c.repo.split("/")[0].casefold() for c in found.values() if c.strong})
                    - set(out_of_scope))
    cutoff = datetime.now(timezone.utc).timestamp() - OWNER_ACTIVE_DAYS * 86400
    for owner in owners[:MAX_OWNERS]:
        try:
            repos = github.owner_repos(owner)
        except GitHubError as error:
            warnings.append(f"listing {owner}'s repositories failed: {error}")
            continue
        for repo in repos:
            pushed = repo.get("pushed_at") or ""
            if repo.get("fork") or repo.get("archived") or not pushed or _timestamp(pushed) < cutoff:
                continue
            signal = "developer has a listed app" if owner in listed_owners else "developer of a candidate"
            _add(found, repo, signal, False, out_of_scope)
    if len(owners) > MAX_OWNERS:
        warnings.append(f"only the first {MAX_OWNERS} of {len(owners)} developers were scanned")
    return found


def _timestamp(value: str) -> float:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def assess(candidate: Candidate, github: GitHub, apps_dir: Path) -> None:
    owner, name = candidate.repo.split("/")
    release = next((r for r in github.releases(owner, name) if not r.get("draft")), None)
    files = [a for a in (release or {}).get("assets", []) if a["name"].lower().endswith(ARTIFACT_EXTENSIONS)]
    if not files:
        candidate.status = "unreleased" if candidate.strong else "no installable release"
        return
    candidate.release = release
    candidate.draft = draft_record(candidate.repo, github, apps_dir)
    blockers = candidate.draft.blockers
    evidence = PPSA.search(" ".join(a["name"] for a in files) + " " + (release.get("body") or ""))
    if not blockers:
        problem = complete(candidate, github)
        candidate.status = "ready" if problem is None else "review"
        if problem:
            candidate.draft.blockers.append(problem)
    elif any("already listed" in b for b in blockers):
        candidate.status = "title ID already listed"
        candidate.note = blockers[0]
    elif candidate.strong or evidence:
        candidate.status = "review"
        if evidence and not candidate.strong:
            candidate.signals.add(f"{evidence.group(0)} in the release")
    else:
        candidate.status = "not a native title"


def clean_text(value: str) -> str:
    """One line of plain text: markdown links and emphasis removed, no control or emoji characters."""
    value = MARKDOWN_LINK.sub(r"\1", unicodedata.normalize("NFC", value))
    value = value.replace("**", "").replace("__", "").replace("`", "")
    value = "".join(ch for ch in value if unicodedata.category(ch) not in BAD_CATEGORIES | {"So"})
    return " ".join(value.split())


def first_paragraph(readme: str) -> str:
    """The README's first paragraph of prose, skipping headings, badges, images, quotes and lists."""
    block: list[str] = []
    in_code = False
    for line in readme.splitlines():
        text = line.strip()
        if text.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        if not text or text.startswith(("#", "<", "![", "[![", ">", "|", "- ", "* ", "---", "===")):
            if block:
                break
            continue
        block.append(text)
    return " ".join(block)


def shorten(text: str, limit: int) -> str:
    """Whole sentences when they fit, otherwise whole words and an ellipsis."""
    if len(text) <= limit:
        return text
    cut = text[:limit]
    end = cut.rfind(". ")
    if end >= limit // 3:
        return cut[:end + 1]
    return text[:limit - 1].rsplit(" ", 1)[0].rstrip(",;:-") + "…"


def complete(candidate: Candidate, github: GitHub) -> str | None:
    """Fill kind and description with labelled guesses; return why no pull request can be opened, or None."""
    record = dict(candidate.draft.record)
    file_name = record["artifact_url"].rsplit("/", 1)[-1]
    if candidate.draft.alternatives:
        return "the release has several installable files; pick the app's own file by hand"
    if DESKTOP_BUILD.search(file_name):
        return f"`{file_name}` looks like a desktop build, not a console title"
    if SAMPLE_FOLDER.search(candidate.draft.param_path):
        return f"`{candidate.draft.param_path}` is in a sample or test folder; it may not be the repository's app"
    if not record["license"]:
        return "GitHub detects no license; set it from the README or LICENSE file by hand"
    if not record["icon_url"]:
        return "no usable icon next to param.json; pick the app's icon by hand"
    owner, name = candidate.repo.split("/")
    meta = github.repo(owner, name) or {}
    readme = github.file_text(owner, name, "README.md", candidate.release["tag_name"]) or ""
    description = source = ""
    for text, where in ((meta.get("description") or "", "the repository's About text"),
                        (first_paragraph(readme), "the README's first paragraph")):
        text = clean_text(text)
        if len(text) >= 20:
            description, source = shorten(text, MAX_LENGTH["description"]), where
            break
    if not description:
        return "no repository description or README paragraph to draft a description from"
    haystack = " ".join([record["name"], description, " ".join(meta.get("topics") or [])])
    kind, word = "app", ""
    for option, pattern in KIND_WORDS:
        match = pattern.search(haystack)
        if match:
            kind, word = option, match.group(0)
            break
    category, clue = DEFAULT_CATEGORY[kind], ""
    for option, pattern in CATEGORY_WORDS:
        match = pattern.search(haystack)
        if match:
            category, clue = option, match.group(0)
            break
    record["kind"], record["category"], record["description"] = kind, category, description
    problems = record_problems(record)
    if problems:
        return "the drafted record is invalid: " + "; ".join(problems)
    candidate.record = record
    candidate.guesses = [
        f"kind `{kind}`: " + (f"guessed from the word \"{_text(word, 30)}\"" if word else "the default; no keyword matched"),
        f"category `{category}`: " + (f"guessed from the word \"{_text(clue, 30)}\"" if clue
                                     else f"the default for a {kind}; no keyword matched"),
        f"description: taken from {source}",
        f"author `{_text(record['author'], 64)}`: the GitHub profile name",
    ]
    return None


def discover(github: GitHub, apps_dir: Path, ignore: set[str], own_repo: str = "",
             max_repos: int = MAX_REPOS, sleep=time.sleep,
             out_of_scope: frozenset[str] | set[str] = frozenset()) -> Result:
    started = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    records = [r for r in load_catalog(apps_dir, Report()) if not r.reserved]
    listed = {r.data["source_repo"].removeprefix("https://github.com/").casefold() for r in records}
    listed_owners = {r.owner.casefold() for r in records}
    warnings: list[str] = []
    found = collect(github, listed_owners, warnings, sleep, out_of_scope)

    candidates = []
    for key, candidate in found.items():
        if key in listed:
            candidate.status = "listed"
        elif key in ignore or key == own_repo.casefold():
            candidate.status = "ignored"
        candidates.append(candidate)
    pending = sorted((c for c in candidates if not c.status),
                     key=lambda c: (not c.strong, -len(c.signals), _negated(c.pushed)))
    examined = 0
    for candidate in pending:
        if examined >= max_repos:
            candidate.status = "not examined (limit)"
            continue
        examined += 1
        try:
            assess(candidate, github, apps_dir)
        except GitHubError as error:
            candidate.status = "lookup failed"
            warnings.append(f"{candidate.repo}: {error}")
            if "rate limit" in str(error):
                for rest in pending:
                    rest.status = rest.status or "not examined (rate limit)"
                break
    return Result(candidates, warnings, examined, started)


def _negated(pushed: str) -> float:
    return -_timestamp(pushed) if pushed else 0.0


# Rendering. Values from other repositories (names, file names) are untrusted:
# they are kept on one line, table pipes are escaped and @mentions are broken.

def _text(value: str, limit: int = 80) -> str:
    value = " ".join(str(value).split())[:limit]
    return value.replace("|", "\\|").replace("@", "@​").replace("<", "&lt;").replace("`", "'")


def _link(repo: str) -> str:
    return f"[{repo}](https://github.com/{repo})"


def _release_line(candidate: Candidate) -> str:
    release = candidate.release or {}
    kind = "pre-release" if release.get("prerelease") else "release"
    date = (release.get("published_at") or "")[:10]
    return f"`{_text(release.get('tag_name', ''), 40)}` ({kind}, {date})"


def previous_state(body: str) -> set[str]:
    match = STATE.search(body or "")
    try:
        return {name.casefold() for name in json.loads(match.group(1))} if match else set()
    except ValueError:
        return set()


def render(result: Result, previous: set[str] | None = None, repository: str = CATALOG_REPO) -> str:
    seen_before = previous or set()
    first_run = previous is None

    def new(candidate: Candidate) -> str:
        return "" if first_run or candidate.repo.casefold() in seen_before else "🆕 "

    def signals(candidate: Candidate) -> str:
        return ", ".join(_text(s, 40) for s in sorted(candidate.signals))

    by_status: dict[str, list[Candidate]] = {}
    for candidate in sorted(result.candidates, key=lambda c: c.repo.casefold()):
        by_status.setdefault(candidate.status, []).append(candidate)
    ready, review, unreleased = (by_status.get(s, []) for s in ("ready", "review", "unreleased"))
    # A ready app whose pull request was closed without merging was rejected; it isn't shown again.
    ready = [c for c in ready if c.note != REJECTED]
    blob = f"https://github.com/{repository}/blob/main"

    lines = [
        f"Daily scan of public GitHub for native PS5 apps the catalog doesn't list yet. "
        f"Updated {result.started} by the [discovery workflow]({blob}/.github/workflows/discovery.yml); "
        "edits to this issue are overwritten.",
        "",
        "Apps that pass every automated check get a listing pull request to review with the "
        f"[listing runbook]({blob}/docs/maintainers/listing-runbook.md); nothing is merged automatically. "
        "Closing a listing pull request without merging stops the job from proposing that app again. "
        "The other sections need a person first. To stop seeing a repository, add it to "
        f"[`discovery/ignore.txt`]({blob}/discovery/ignore.txt) with a reason. "
        "🆕 marks repositories that weren't in the previous report.",
        "",
        f"## Listing pull requests ({len(ready)})",
        "",
    ]
    if ready:
        lines += ["| Repository | Title ID | Name | Release | Pull request |", "| --- | --- | --- | --- | --- |"]
        for c in ready:
            record = c.record or c.draft.record
            lines.append(f"| {new(c)}{_link(c.repo)} | `{record['titleid']}` | {_text(record['name'], 40)} | "
                         f"{_release_line(c)} | {_text(c.note, 120) or 'not opened'} |")
        lines.append("")
    lines += [f"## Needs review ({len(review)})", "",
              "Native signals and an installable release, but `draft` reports a blocker (often a `param.json` "
              "generated at build time, so the title ID has to come from build scripts or release notes).", ""]
    for c in review:
        blockers = "; ".join(_text(b, 160) for b in c.draft.blockers)
        lines.append(f"- {new(c)}{_link(c.repo)}: {_release_line(c)}. Blocker: {blockers}. Signals: {signals(c)}.")
    lines += ["", f"## Native, but no release yet ({len(unreleased)})", "",
              "Strong native signals without a published release that has a .zip, .ffpkg or .ffpfsc file. "
              "Only the developer can publish one.", ""]
    for c in unreleased:
        lines.append(f"- {new(c)}{_link(c.repo)}: {signals(c)}")

    skipped = {status: len(items) for status, items in by_status.items()
               if status not in ("ready", "review", "unreleased")}
    lines += ["", "## Scan", "",
              f"- {len(result.candidates)} repositories found by {len(CODE_QUERIES)} code searches, "
              f"{len(REPO_QUERIES)} repository searches and the listed developers' other repositories; "
              f"{result.examined} checked for releases.",
              "- Not shown: " + (", ".join(f"{count} {status}" for status, count in sorted(skipped.items()))
                                 or "none") + "."]
    lines += [f"- Warning: {_text(w, 300)}" for w in result.warnings]
    rejected = sum(1 for c in by_status.get("ready", []) if c.note == REJECTED)
    if rejected:
        lines.insert(len(lines) - len(result.warnings), f"- {rejected} app(s) not shown again: their listing pull "
                     "request was closed without merging.")
    state = sorted(c.repo for c in ready + review + unreleased)
    body = "\n".join(lines)
    if len(body) > MAX_BODY:
        body = body[:MAX_BODY] + "\n\n…(truncated)"
    return body + f"\n\n<!-- discovery-state: {json.dumps(state)} -->\n"


def publish(issues: GitHub, repository: str, result: Result) -> str:
    """Create or rewrite the tracking issue; returns its URL."""
    issues.ensure_label(repository, LABEL, "5319e7", "Daily scan for native PS5 apps not listed yet")
    issue = issues.open_issue(repository, LABEL)
    if issue:
        body = render(result, previous_state(issue.get("body") or ""), repository)
        return issues.update_issue(repository, issue["number"], TITLE, body).get("html_url", "")
    return issues.create_issue(repository, TITLE, render(result, repository=repository), [LABEL]).get("html_url", "")


def pull_request_text(candidate: Candidate, repository: str = CATALOG_REPO) -> tuple[str, str]:
    """Title and body of a listing pull request, in the runbook's format."""
    record, release = candidate.record, candidate.release
    blob = f"https://github.com/{repository}/blob/main"
    file_name = record["artifact_url"].rsplit("/", 1)[-1]
    title = f"List {clean_text(record['name'])} by {clean_text(record['author'])}"
    param_fact = next((f for f in candidate.draft.facts if "param.json:" in f), "")
    body = [
        f"Proposed by the daily [discovery job]({blob}/.github/workflows/discovery.yml): adds "
        f"{_text(record['name'], 64)} (`{record['titleid']}`) from {record['source_repo']}. "
        "Nothing is merged automatically.",
        "",
        f"**Found by:** {', '.join(_text(s, 40) for s in sorted(candidate.signals))}.",
        "",
        f"**Native PS5 app:** {_text(param_fact, 300)}.",
        "",
        f"**Release:** {_release_line(candidate)}, file `{_text(file_name, 100)}`, "
        f"GitHub digest `sha256:{record['sha256']}` (the submission check verifies it).",
        "",
        "**Guessed by the job, please confirm or edit on this branch:**",
        *(f"- {guess}" for guess in candidate.guesses),
        f"- license `{record['license']}`: detected by GitHub",
        "",
        f"**Before merging, check with the [listing runbook]({blob}/docs/maintainers/listing-runbook.md):**",
        "- It's a native app people install, not a template, sample, SDK, driver or test project.",
        "- The listed file is the app itself; companion payloads or packs stay unlisted.",
        "- No commercial game data, not a repackage of someone else's app, not for piracy.",
        *(f"- {_text(item, 300)}" for item in candidate.draft.todo
          if not item.startswith(("confirm `author`", "write `description`", "set `kind`"))),
        "",
        "Merge to list it, or close without merging to stop the job from proposing it again.",
    ]
    return title, "\n".join(body)

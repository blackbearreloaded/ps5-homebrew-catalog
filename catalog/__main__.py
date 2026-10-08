"""Command-line entry point: python3 -m catalog <command>."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from .github import GitHub, GitHubError
from .policy import Change, check_changes, check_publisher, is_maintainer
from .records import MAX_FILE_BYTES, RECORD_PATH, Record, load_catalog, load_record, repo_parts
from .report import Report
from .verify import newer_release, verify_record

ROOT = Path(__file__).resolve().parents[1]
APPS = ROOT / "apps"
ZERO_SHA = "0" * 40


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=True).stdout


def git_bytes(*args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True).stdout


def diff_changes(base: str, head: str) -> list[Change]:
    fields = git("diff", "--name-status", "--no-renames", "-z", base, head).split("\0")
    changes = []
    for status, path in zip(fields[0::2], fields[1::2]):
        mode = None
        if status != "D":
            listing = git("ls-tree", "-z", head, "--", path).split("\0")[0]
            mode = listing.split(" ", 1)[0] if listing else None
        changes.append(Change(status[0], path, mode))
    return changes


def cmd_check(args) -> int:
    report = Report()
    records = load_catalog(Path(args.apps_dir), report)
    return report.emit("Catalog check", f"{len(records)} record(s) are valid.")


def cmd_verify(args) -> int:
    report = Report()
    records = load_catalog(APPS, report)
    wanted = {t.upper() for t in args.titleids}
    unknown = wanted - {r.titleid for r in records}
    for titleid in sorted(unknown):
        report.error(f"apps/{titleid}.json", "no valid record with this title ID")
    selected = [r for r in records if not wanted or r.titleid in wanted]
    github = GitHub()
    for record in selected:
        verify_record(record, github, report)
    return report.emit("Catalog verification", f"{len(selected)} record(s) verified.")


def _report_scan(scan, name: str, title: str, report: Report) -> None:
    """Put a scan's findings in the report (errors and warnings) and its full text in the job summary."""
    from .scan import markdown
    for level, text in scan.findings:
        if level != "notice":
            getattr(report, level)(name, text.replace("`", ""))
    report.notice(name, f"release scan: {scan.verdict}; the full report is in the job summary")
    text = markdown(scan, title)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write(text + "\n")
    else:
        print(text)


def cmd_scan(args) -> int:
    """Scan the release archive of listed apps, or a ZIP file on disk."""
    from .scan import check_helpers, load_approved, scan_archive, scan_release
    report = Report()
    approved = load_approved()
    if args.zip:
        if len(args.titleids) != 1:
            report.error("scan", "--zip needs exactly one title ID: the folder the archive should hold")
        else:
            titleid = args.titleids[0].upper()
            scan = scan_archive(Path(args.zip), titleid)
            check_helpers(scan, approved)
            _report_scan(scan, args.zip, titleid, report)
        return report.emit("Release scan", "Scanned.")
    records = [r for r in load_catalog(APPS, report) if not r.reserved]
    wanted = {t.upper() for t in args.titleids}
    for titleid in sorted(wanted - {r.titleid for r in records}):
        report.error(f"apps/{titleid}.json", "no listed app with this title ID")
    selected = [r for r in records if not wanted or r.titleid in wanted]
    rows = []       # one line per release, for the overview of a scan of several
    with tempfile.TemporaryDirectory(prefix="catalog-scan-") as tmp:
        for record in selected:
            name = f"apps/{record.path.name}"
            if not record.asset_name.lower().endswith(".zip"):
                report.notice(name, "not a ZIP archive; not scanned")
                rows.append((record, None, 0))
                continue
            scan = scan_release(record.data, Path(tmp), attest=True)
            if args.helpers:
                # Entries for helpers/approved.json, to paste after reading each helper's source.
                for info in scan.payloads:
                    if info.sha256 not in approved:
                        print(json.dumps({"sha256": info.sha256, "name": f"{record.data['name']}: "
                                          f"{info.path.rsplit('/', 1)[-1]}", "titleid": record.titleid,
                                          "version": record.data["version"], "source": record.data["source_repo"]}) + ",")
                continue
            unapproved = check_helpers(scan, approved)
            rows.append((record, scan, unapproved))
            _report_scan(scan, name, f"{record.data['name']} ({record.titleid}) {record.data['version']}", report)
    if len(rows) > 1 and not args.helpers:
        _scan_overview(rows)
    return report.emit("Release scan", f"{len(selected)} release(s) scanned.")


def _scan_overview(rows) -> None:
    """One table for a scan of several releases: where each app stands."""
    words = {"stays": "stays in the sandbox", "leaves": "leaves the sandbox", "unclear": "unclear",
             "unreadable": "not scanned"}
    lines = ["## Overview", "", "| App | Title ID | Version | Sandbox | How | Helpers | Not reviewed | Build attested |",
             "| --- | --- | --- | --- | --- | ---: | ---: | --- |"]
    counts: dict[str, int] = {}
    for record, scan, unapproved in rows:
        d = record.data
        if scan is None:
            verdict, how, helpers, attested = "not scanned (not a ZIP)", "", "", ""
        else:
            verdict, how = words[scan.sandbox], ", ".join(scan.routes)
            helpers = str(len(scan.payloads)) if scan.downloaded else ""
            attested = {True: "yes", False: "no", None: "not checked"}[scan.attested] if scan.downloaded else ""
        counts[verdict] = counts.get(verdict, 0) + 1
        lines.append(f"| {d['name'].replace('|', ' ')} | `{d['titleid']}` | {d['version']} | {verdict} | {how} | "
                     f"{helpers} | {unapproved if scan is not None and unapproved else ''} | {attested} |")
    lines += ["", "Totals: " + ", ".join(f"{n} {word}" for word, n in sorted(counts.items(), key=lambda c: -c[1])) + ".", ""]
    text = "\n".join(lines) + "\n"
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write(text)
    else:
        print(text)


def cmd_scan_all(args) -> int:
    """CI: a summary of every listed release's scan, for the website and the store API.

    A summary is kept by the file's sha256, so a release is downloaded and scanned once. The job
    that runs this handles unreviewed files and has no secrets; the build reads its output as data.
    """
    from .scan import SCANNER, read_summary, scan_release, summary
    report = Report()
    cache, out = Path(args.cache), Path(args.out)
    cache.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    records = [r for r in load_catalog(APPS, Report()) if not r.reserved and r.asset_name.lower().endswith(".zip")]
    scanned = 0
    with tempfile.TemporaryDirectory(prefix="catalog-scan-") as tmp:
        for record in records:
            sha256 = record.data["sha256"]
            kept = cache / f"{sha256}.json"
            data = None
            if kept.is_file():
                try:
                    data = read_summary(json.loads(kept.read_text(encoding="utf-8")), sha256)
                except (OSError, ValueError):
                    data = None
            if data is None:
                scan = scan_release(record.data, Path(tmp), attest=True)
                scanned += 1
                if not scan.downloaded or scan.sha256 != sha256:
                    report.warning(f"apps/{record.path.name}", "not scanned: " + scan.verdict
                                   if not scan.downloaded else "not scanned: the file is not the listed one")
                    continue
                data = summary(scan)
                kept.write_text(json.dumps(data), encoding="utf-8")
                report.notice(f"apps/{record.path.name}", f"scanned: {scan.verdict}")
            (out / f"{sha256}.json").write_text(json.dumps(data), encoding="utf-8")
    wanted = {f"{r.data['sha256']}.json" for r in records}
    for entry in cache.glob("*.json"):
        if entry.name not in wanted:
            entry.unlink()
    return report.emit("Release scans", f"{len(records)} release(s), {scanned} scanned now (scanner {SCANNER}).")


def cmd_scan_pr(args) -> int:
    """CI: scan the releases a pull request lists. Base-branch code; PR files are read only as data.

    The job that runs this has no secrets and a read-only token: it downloads files nobody has
    reviewed. Only an archive that is unsafe to unpack fails the check; everything else is a report
    for the reviewer.
    """
    from .records import record_problems
    from .scan import check_helpers, compare, load_approved, scan_release
    approved = load_approved()
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
    pull = event["pull_request"]
    head = "refs/catalog/pr-head"
    git("fetch", "--no-tags", "--quiet", "origin", f"+refs/pull/{pull['number']}/head:{head}")
    base = git("merge-base", "HEAD", head).strip()
    report = Report()
    scanned = 0
    with tempfile.TemporaryDirectory(prefix="catalog-scan-") as tmp:
        for change in diff_changes(base, head):
            if change.status == "D" or not RECORD_PATH.fullmatch(change.path):
                continue
            if int(git("cat-file", "-s", f"{head}:{change.path}")) > MAX_FILE_BYTES:
                continue
            try:
                data = json.loads(git_bytes("show", f"{head}:{change.path}").decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                continue        # the submission check reports a record that can't be read
            if not isinstance(data, dict) or record_problems(data) or data.get("artifact_url") is None:
                continue
            if Path(change.path).stem != data["titleid"]:
                continue
            old_path = ROOT / change.path
            listed = None
            if old_path.is_file():
                try:
                    listed = json.loads(old_path.read_text(encoding="utf-8"))
                    if listed.get("sha256") == data["sha256"]:
                        continue        # the same file as listed: nothing new to scan
                except ValueError:
                    listed = None
            if not data["artifact_url"].lower().endswith(".zip"):
                report.notice(change.path, "not a ZIP archive; not scanned")
                continue
            scanned += 1
            scan = scan_release(data, Path(tmp), attest=True)
            check_helpers(scan, approved)
            if scan.attested is False:
                report.notice(change.path, "no verified build attestation: nothing ties this file to a workflow run")
            # An update: scan the listed release too and say what changed.
            if (scan.downloaded and isinstance(listed, dict) and not record_problems(listed)
                    and str(listed.get("artifact_url") or "").lower().endswith(".zip")):
                before = scan_release(listed, Path(tmp))
                if before.downloaded and not before.failed:
                    scan.compared_with = f"the listed release, {listed['version']}"
                    scan.comparison = compare(before, scan)
                    for line in scan.comparison:
                        if line.startswith("**") or line.startswith("New payload") or line.startswith("Payload"):
                            report.warning(change.path, "since the listed release: " + line.replace("*", "").replace("`", ""))
            _report_scan(scan, change.path, f"{data['name']} ({data['titleid']}) {data['version']}", report)
    return report.emit("Release scan", f"{scanned} release(s) scanned; the reports are above.")


HEALTH_SLICES = 7


def health_slice(titleid: str) -> int:
    """Stable day-of-week bucket (0 = Monday) for a record in the daily health rotation."""
    return int(hashlib.sha256(titleid.encode()).hexdigest(), 16) % HEALTH_SLICES


def cmd_health(args) -> int:
    from datetime import datetime, timedelta, timezone
    from .records import RESERVATION_STALE_DAYS
    from .site import last_updated

    report = Report()
    records = load_catalog(APPS, report)
    now = datetime.now(timezone.utc)
    if args.slice == "all":
        selected = records
    else:
        day = now.weekday() if args.slice == "today" else int(args.slice)
        selected = [r for r in records if health_slice(r.titleid) == day]
        report.notice("catalog", f"checking slice {day} of {HEALTH_SLICES}: {len(selected)} of "
                                 f"{len(records)} records (every record is checked once a week)")
    github = GitHub()
    updated = last_updated(APPS)
    cutoff = now - timedelta(days=RESERVATION_STALE_DAYS)
    for record in records:
        changed = updated.get(record.path.name)
        if record.reserved and changed and datetime.fromisoformat(changed) < cutoff:
            report.warning(f"apps/{record.path.name}", f"reservation unchanged for over "
                           f"{RESERVATION_STALE_DAYS} days (last update {changed[:10]}); it may be released")
    for record in selected:
        verify_record(record, github, report)
        try:
            tag = newer_release(record, github)
        except GitHubError as error:
            report.warning(f"apps/{record.path.name}", f"could not list releases: {error}")
            continue
        if tag:
            report.notice(f"apps/{record.path.name}", f"a newer release is published: {tag}")
    return report.emit("Catalog health", f"{len(selected)} checked record(s) are intact.")


def cmd_push(args) -> int:
    report = Report()
    records = load_catalog(APPS, report)
    if not args.before or args.before == ZERO_SHA:
        selected = records
    else:
        changed = {Path(c.path).name for c in diff_changes(args.before, args.after)
                   if c.status != "D" and RECORD_PATH.fullmatch(c.path)}
        selected = [r for r in records if r.path.name in changed]
    github = GitHub()
    for record in selected:
        verify_record(record, github, report)
    return report.emit("Catalog push check", f"{len(records)} record(s) valid; {len(selected)} verified.")


def reservation_holder(record_path: str, github: GitHub) -> str | None:
    """Login of the account whose commit added a reservation file (the latest addition)."""
    sha = git("log", "--diff-filter=A", "--format=%H", "-1", "--", record_path).strip()
    repository = os.environ.get("GITHUB_REPOSITORY")
    if not sha or not repository:
        return None
    try:
        return github.commit_author(repository, sha)
    except GitHubError:
        return None


def cmd_pr(args) -> int:
    """Validate a pull request using this (base-branch) code; PR files are read only as data."""
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
    pull = event["pull_request"]
    author = pull["user"]["login"]
    # A branch in this repository (not a fork) can only be pushed by an account or app with write access,
    # such as the catalog bot's discovery and update pull requests.
    head_repo = ((pull.get("head") or {}).get("repo") or {}).get("full_name")
    same_repository = bool(head_repo) and head_repo == ((pull.get("base") or {}).get("repo") or {}).get("full_name")
    maintainer = is_maintainer(pull["author_association"]) or same_repository
    report = Report()
    if maintainer:
        report.notice("pull request", f"@{author} is a maintainer; community-only rules are relaxed")

    head = "refs/catalog/pr-head"
    git("fetch", "--no-tags", "--quiet", "origin", f"+refs/pull/{pull['number']}/head:{head}")
    base = git("merge-base", "HEAD", head).strip()
    record_changes = check_changes(diff_changes(base, head), maintainer, report)

    github = GitHub()
    with tempfile.TemporaryDirectory(prefix="catalog-pr-") as tmp:
        candidate = Path(tmp) / "apps"
        shutil.copytree(APPS, candidate)
        for change in record_changes:
            target = candidate / Path(change.path).name
            target.unlink(missing_ok=True)
            if change.status == "D":
                continue
            if int(git("cat-file", "-s", f"{head}:{change.path}")) > MAX_FILE_BYTES:
                report.error(change.path, f"is larger than {MAX_FILE_BYTES} bytes")
                continue
            target.write_bytes(git_bytes("show", f"{head}:{change.path}"))

        records = {r.path.name: r for r in load_catalog(candidate, report)}
        holders: dict[str, str | None] = {}

        def holder_of(filename: str) -> str | None:
            if filename not in holders:
                holders[filename] = reservation_holder(f"apps/{filename}", github)
            return holders[filename]

        if any(r.reserved for r in records.values()):
            base_reserved = [r for r in load_catalog(APPS, Report()) if r.reserved]
        else:
            base_reserved = []
        for change in record_changes:
            new = records.get(Path(change.path).name)
            if change.status == "D" or new is None:
                continue
            old_path = ROOT / change.path
            old = load_record(old_path, Report()) if old_path.is_file() else None
            before = report.count("error")
            held = sum(1 for r in base_reserved if r.path.name != new.path.name
                       and (holder_of(r.path.name) or "").casefold() == author.casefold())
            check_publisher(author, maintainer, old, new, github, report,
                            holder=holder_of(new.path.name) if old and old.reserved else None, held=held)
            if report.count("error") == before:
                verify_record(new, github, report, previous=old)
    return report.emit("Pull request check", "The submission meets every automated requirement; "
                                             "a maintainer will review it.")


UPDATE_BRANCH = "catalog-update/all"
# The pull request body records which release it proposes for each app, so a later run can tell what was rejected.
UPDATE_STATE = re.compile(r"<!-- catalog-updates: (\{.*?\}) -->")


def update_section(update) -> str:
    from .records import release_parts
    old, new = update.record.data, update.data
    old_tag, old_asset = release_parts(old)
    new_tag, new_asset = release_parts(new)
    repo = old["source_repo"]
    rows = [
        ("Version", old["version"], new["version"]),
        ("Release", f"[{old_tag}]({repo}/releases/tag/{old_tag})", f"[{new_tag}]({repo}/releases/tag/{new_tag})"
         + (" (pre-release)" if update.prerelease else "")),
        ("File", f"`{old_asset}`", f"`{new_asset}`"),
        ("sha256", f"`{old['sha256']}`", f"`{new['sha256']}` (GitHub's digest)"),
        ("Icon", old["icon_url"], new["icon_url"] if new["icon_url"] != old["icon_url"] else "unchanged"),
    ]
    return "\n".join([
        f"### {new['name']} (`{new['titleid']}`): {old['version']} → {new['version']}",
        "",
        f"From {repo}.",
        "",
        "| | Listed | Proposed |",
        "| --- | --- | --- |",
        *[f"| {label} | {a} | {b} |" for label, a, b in rows],
        *([""] + [f"- {note}" for note in update.notes] if update.notes else []),
    ])


def updates_pr_text(updates: list) -> tuple[str, str]:
    """Title and body of the one pull request that carries every pending update."""
    names = [f"{u.data['name']} to {u.data['version']}" for u in updates]
    if len(names) == 1:
        title = f"Update {names[0]}"
    else:
        shown = ", ".join(names[:3]) + (f" and {len(names) - 3} more" if len(names) > 3 else "")
        title = f"Update {len(names)} apps: {shown}"
    state = json.dumps({u.record.titleid: u.tag for u in updates}, sort_keys=True)
    body = "\n".join([
        f"Automated updates from the daily release check: {len(updates)} app(s) have a newer release.",
        "",
        *[update_section(u) + "\n" for u in updates],
        "The submission check verifies every record in this pull request. Merge it to publish the updates. "
        "Closing it without merging skips these versions: none of them is proposed again, and each app "
        "comes back with its next release.",
        "",
        f"<!-- catalog-updates: {state} -->",
    ])
    return title, body


def rejected_updates(repository: str, github: GitHub) -> set[tuple[str, str]]:
    """(title ID, tag) pairs of update pull requests that were closed without merging."""
    rejected = set()
    for body in github.closed_pull_bodies(repository, UPDATE_BRANCH):
        match = UPDATE_STATE.search(body)
        if not match:
            continue
        try:
            rejected.update(json.loads(match.group(1)).items())
        except ValueError:
            continue
    return rejected


def open_updates_pr(updates: list, repository: str, github: GitHub, report: Report) -> None:
    """Keep one pull request, on one branch, with every pending update; rebuild it when the set changes."""
    from .updates import render
    rejected = rejected_updates(repository, github)
    kept = []
    for update in updates:
        if (update.record.titleid, update.tag) in rejected:
            report.notice(f"apps/{update.record.path.name}",
                          f"skipped: an update to {update.tag} was closed without merging")
        else:
            kept.append(update)
    existing = github.open_pull(repository, UPDATE_BRANCH)
    if not kept:
        if existing:
            # Its updates reached main some other way. The marker is dropped so closing it rejects nothing.
            github.update_pull(repository, existing["number"], existing.get("title", "Update apps"),
                               "Closed by the release check: there is nothing left to update.")
            github.close_pull(repository, existing["number"])
            report.notice("updates", f"closed pull request #{existing['number']}: nothing left to update")
        return

    title, body = updates_pr_text(kept)
    contents = {f"apps/{u.record.path.name}": render(u.data) for u in kept}
    git("fetch", "--quiet", "origin", "main")
    if existing:
        git("fetch", "--quiet", "origin", f"+refs/heads/{UPDATE_BRANCH}:refs/remotes/origin/{UPDATE_BRANCH}")
        changed = git("diff", "--name-only", "origin/main", f"origin/{UPDATE_BRANCH}").split()
        try:
            same = sorted(changed) == sorted(contents) and all(
                git("show", f"origin/{UPDATE_BRANCH}:{path}") == content for path, content in contents.items())
        except subprocess.CalledProcessError:
            same = False
        if same:
            report.notice("updates", f"pull request #{existing['number']} already proposes these updates")
            return
    git("checkout", "--quiet", "-B", UPDATE_BRANCH, "origin/main")
    try:
        for path, content in contents.items():
            (ROOT / path).write_text(content, encoding="utf-8", newline="\n")
            git("add", path)
        git("commit", "--quiet", "-m", title)
        git("push", "--quiet", "--force", "origin", f"{UPDATE_BRANCH}:{UPDATE_BRANCH}")
    finally:
        git("checkout", "--quiet", "--detach", "origin/main")
    if existing:
        github.update_pull(repository, existing["number"], title, body)
        report.notice("updates", f"updated pull request #{existing['number']}: {title}")
    else:
        pull = github.create_pull(repository, UPDATE_BRANCH, "main", title, body)
        report.notice("updates", f"opened pull request #{pull.get('number')}: {title}")


def cmd_updates(args) -> int:
    from .updates import find_update
    report = Report()
    records = load_catalog(APPS, report)
    wanted = {t.upper() for t in args.titleids}
    github = GitHub()
    found = []
    for record in records:
        if wanted and record.titleid not in wanted:
            continue
        name = f"apps/{record.path.name}"
        try:
            update, reason = find_update(record, github)
        except GitHubError as error:
            report.warning(name, f"could not check releases: {error}")
            continue
        if update:
            found.append(update)
            report.notice(name, f"{record.tag} -> {update.tag}" + (" (pre-release)" if update.prerelease else ""))
        elif reason not in ("up to date", "reservation"):
            report.warning(name, reason)
    if args.open_prs:
        from . import facts
        repository = os.environ["GITHUB_REPOSITORY"]
        for update in found:
            try:
                old_version, _ = facts.find_content_version(update.record, github)
                new_version, _ = facts.find_content_version(Record(update.record.path, update.data), github)
            except GitHubError:
                continue
            update.notes.append(facts.update_note(facts.Facts(content_version=old_version),
                                                  facts.Facts(content_version=new_version)))
        try:
            open_updates_pr(found, repository, github, report)
        except (GitHubError, subprocess.CalledProcessError) as error:
            report.error("updates", f"could not open the pull request: {error}")
    return report.emit("Update check", f"{len(found)} update(s) found.")


LISTING_BRANCH = "listing/{titleid}"


def open_listing_pr(candidate, repository: str, github: GitHub, open_files: dict[str, int]) -> str:
    """Open a listing pull request for a discovered app; returns what happened, for the report."""
    from .discover import REJECTED, pull_request_text
    from .updates import render
    titleid = candidate.record["titleid"]
    path = f"apps/{titleid}.json"
    branch = LISTING_BRANCH.format(titleid=titleid)
    if path in open_files:
        return f"#{open_files[path]} already proposes {titleid}"
    if github.closed_pull_titles(repository, branch):
        return REJECTED
    title, body = pull_request_text(candidate, repository)
    git("fetch", "--quiet", "origin", "main")
    git("checkout", "--quiet", "-B", branch, "origin/main")
    try:
        (APPS / f"{titleid}.json").write_text(render(candidate.record), encoding="utf-8", newline="\n")
        git("add", path)
        git("commit", "--quiet", "-m", title)
        git("push", "--quiet", "--force", "origin", f"{branch}:{branch}")
    finally:
        git("checkout", "--quiet", "--detach", "origin/main")
    pull = github.create_pull(repository, branch, "main", title, body)
    open_files[path] = pull.get("number")
    return f"#{pull.get('number')} opened"


def cmd_discover(args) -> int:
    from .discover import MAX_NEW_PULLS, discover, publish, read_ignore, read_scope, render
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    github = GitHub()
    result = discover(github, APPS, read_ignore(ROOT / "discovery" / "ignore.txt"), own_repo=repository,
                      max_repos=args.max_repos,
                      out_of_scope=read_scope(os.environ.get("DISCOVERY_SCOPE", "")))
    ready = sorted((c for c in result.candidates if c.status == "ready"), key=lambda c: c.repo.casefold())
    if args.open_prs:
        open_files = github.open_pull_files(repository)
        opened = 0
        for candidate in ready:
            if opened >= MAX_NEW_PULLS:
                candidate.note = "waiting: this run's pull request limit was reached"
                continue
            try:
                candidate.note = open_listing_pr(candidate, repository, github, open_files)
            except (GitHubError, subprocess.CalledProcessError) as error:
                candidate.note = "could not open the pull request"
                result.warnings.append(f"{candidate.repo}: could not open the pull request: {error}")
                continue
            opened += candidate.note.endswith(" opened")
    if args.issue:
        print("Discovery report:", publish(GitHub(os.environ["ISSUE_TOKEN"]), repository, result))
    else:
        print(render(result, repository=repository or "blackbearreloaded/ps5-homebrew-catalog"))
    for candidate in ready:
        print(f"ready: {candidate.repo} {candidate.record['titleid']} {candidate.note}")
    return 0


def cmd_draft(args) -> int:
    from .draft import draft_record, render_draft
    from .updates import render
    try:
        draft = draft_record(args.repository, GitHub(), APPS, tag=args.tag, asset_name=args.asset)
    except (ValueError, GitHubError) as error:
        print(f"draft failed: {error}", file=sys.stderr)
        return 1
    print(render_draft(draft))
    if args.write and not draft.blockers and draft.record["titleid"]:
        target = APPS / f"{draft.record['titleid']}.json"
        if target.exists():
            print(f"not written: {target.relative_to(ROOT)} already exists", file=sys.stderr)
            return 1
        target.write_text(render(draft.record), encoding="utf-8", newline="\n")
        print(f"written: {target.relative_to(ROOT)} (fill the empty fields, then run check and verify)")
    return 1 if draft.blockers else 0


def cmd_build(args) -> int:
    from .site import build_site
    report = Report()
    count = build_site(Path(args.out), APPS, report, base=args.base, site_url=args.site_url,
                       fetch_icons=not args.no_icons, theme=args.theme,
                       icon_cache=Path(args.icon_cache) if args.icon_cache else None,
                       github=None if args.no_icons else GitHub(),
                       scans=Path(args.scans) if args.scans else None)
    return report.emit("Site build", f"Built {count} app page(s) into {args.out}.")


def cmd_sign(args) -> int:
    """Sign the built API's manifest with CATALOG_SIGNING_KEY (a deployment secret)."""
    from . import signing
    from .site import API_VERSION, normalize_base
    base = normalize_base(args.base).strip("/")
    api_root = Path(args.out) / base / "api" / API_VERSION if base else Path(args.out) / "api" / API_VERSION
    key = signing.signing_key_from_environment()
    if key is None:
        if args.require:
            print("CATALOG_SIGNING_KEY is not set; refusing to publish an unsigned catalog", file=sys.stderr)
            return 1
        print("CATALOG_SIGNING_KEY is not set; the API is left unsigned.")
        return 0
    try:
        identifier = signing.sign(api_root, key)
    except signing.SigningError as error:
        print(f"signing failed: {error}", file=sys.stderr)
        return 1
    manifest = json.loads((api_root / signing.MANIFEST).read_text(encoding="utf-8"))
    print(f"Signed the API manifest: sequence {manifest['sequence']}, {len(manifest['files'])} file(s), key {identifier}.")
    return 0


def cmd_digest(args) -> int:
    """Print the sha256 GitHub reports for a release asset URL."""
    marker = "/releases/download/"
    if marker not in args.artifact_url:
        print("expected a https://github.com/<owner>/<repo>/releases/download/<tag>/<asset> URL", file=sys.stderr)
        return 2
    source_repo, suffix = args.artifact_url.split(marker, 1)
    probe = Record(Path("probe.json"), {"source_repo": source_repo, "artifact_url": args.artifact_url})
    try:
        owner, repo = repo_parts(source_repo)
        tag, asset_name = probe.tag, probe.asset_name
        release = GitHub().release_by_tag(owner, repo, tag)
    except (ValueError, GitHubError) as error:
        print(f"could not look up the release: {error}", file=sys.stderr)
        return 1
    asset = next((a for a in (release or {}).get("assets", []) if a.get("name") == asset_name), None)
    if not asset:
        print("release or asset not found", file=sys.stderr)
        return 1
    digest = asset.get("digest") or ""
    if not digest.startswith("sha256:"):
        print("GitHub has no digest for this asset; run sha256sum on the downloaded file", file=sys.stderr)
        return 1
    print(digest.removeprefix("sha256:"))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python3 -m catalog", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    check = commands.add_parser("check", help="offline validation of every record (no network)")
    check.add_argument("--apps-dir", default=str(APPS))
    check.set_defaults(func=cmd_check)

    verify = commands.add_parser("verify", help="check records against GitHub and their downloads")
    verify.add_argument("titleids", nargs="*", help="title IDs to verify (default: all)")
    verify.set_defaults(func=cmd_verify)

    digest = commands.add_parser("digest", help="print the sha256 of a GitHub release asset URL")
    digest.add_argument("artifact_url")
    digest.set_defaults(func=cmd_digest)

    from .site import DEFAULT_BASE, DEFAULT_SITE_URL, DEFAULT_THEME, THEMES
    build = commands.add_parser("build", help="build the static website and JSON feed")
    build.add_argument("--out", default=str(ROOT / "dist"))
    build.add_argument("--base", default=DEFAULT_BASE, help="URL path the site is served under")
    build.add_argument("--site-url", default=DEFAULT_SITE_URL, help="origin used for absolute URLs")
    build.add_argument("--theme", default=DEFAULT_THEME, choices=sorted(THEMES))
    build.add_argument("--no-icons", action="store_true", help="offline build: no icons (placeholders) and no release facts in the API")
    build.add_argument("--icon-cache", help="directory that keeps fetched icons and release facts between builds")
    build.add_argument("--scans", help="directory of release scan summaries (catalog scan-all --out), for the safety labels")
    build.set_defaults(func=cmd_build)

    sign = commands.add_parser("sign", help="CI: sign the built API's manifest with CATALOG_SIGNING_KEY")
    sign.add_argument("--out", default=str(ROOT / "dist"))
    sign.add_argument("--base", default=DEFAULT_BASE)
    sign.add_argument("--require", action="store_true", help="fail when the key is not set")
    sign.set_defaults(func=cmd_sign)

    draft = commands.add_parser("draft", help="draft a record for a repository (no downloads, no writes to GitHub)")
    draft.add_argument("repository", help="owner/repository or GitHub URL")
    draft.add_argument("--tag", help="release tag (default: newest release, pre-releases included)")
    draft.add_argument("--asset", help="release file to list when there are several")
    draft.add_argument("--write", action="store_true", help="write apps/<TITLEID>.json with the drafted values")
    draft.set_defaults(func=cmd_draft)

    updates = commands.add_parser("updates", help="find newer upstream releases (and open PRs in CI)")
    updates.add_argument("titleids", nargs="*", help="title IDs to check (default: all)")
    updates.add_argument("--open-prs", action="store_true", help="CI: open or refresh one pull request per update")
    updates.set_defaults(func=cmd_updates)

    discover = commands.add_parser("discover", help="find native PS5 apps on GitHub that aren't listed yet")
    discover.add_argument("--max-repos", type=int, default=600, help="release lookups per run")
    discover.add_argument("--open-prs", action="store_true", help="CI: open a listing pull request per ready app")
    discover.add_argument("--issue", action="store_true", help="CI: rewrite the discovery issue (needs ISSUE_TOKEN)")
    discover.set_defaults(func=cmd_discover)

    pr = commands.add_parser("pr", help="CI: validate the pull request in GITHUB_EVENT_PATH")
    pr.set_defaults(func=cmd_pr)

    scan = commands.add_parser("scan", help="download and statically scan release archives (needs requirements-scan.txt)")
    scan.add_argument("titleids", nargs="*", help="title IDs to scan (default: every listed app)")
    scan.add_argument("--zip", help="scan this ZIP file instead of downloading; give its title ID")
    scan.add_argument("--helpers", action="store_true",
                      help="print helpers/approved.json entries for the payloads that aren't on the list")
    scan.set_defaults(func=cmd_scan)

    scan_all = commands.add_parser("scan-all", help="CI: write a scan summary per listed release, scanning only new files")
    scan_all.add_argument("--cache", required=True, help="directory that keeps summaries between runs")
    scan_all.add_argument("--out", required=True, help="directory for the summaries of the listed releases")
    scan_all.set_defaults(func=cmd_scan_all)

    scan_pr = commands.add_parser("scan-pr", help="CI: scan the releases listed by the pull request in GITHUB_EVENT_PATH")
    scan_pr.set_defaults(func=cmd_scan_pr)

    push = commands.add_parser("push", help="CI: validate records changed by a push")
    push.add_argument("--before", default="")
    push.add_argument("--after", default="HEAD")
    push.set_defaults(func=cmd_push)

    health = commands.add_parser("health", help="CI: re-verify listed releases (daily slice or all)")
    health.add_argument("--slice", default="all", choices=["all", "today"] + [str(n) for n in range(HEALTH_SLICES)],
                        help="all records, today's weekday slice, or slice 0-6")
    health.set_defaults(func=cmd_health)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

# Runbook: list a developer's native PS5 app

For maintainers and AI agents acting for a maintainer. It turns a developer's
public GitHub repository into a pull request that adds one
`apps/<TITLEID>.json`. Follow it step by step; every value in the record must be
backed by evidence you can quote in the pull request.

The developer doesn't have to be involved: the listing points at their own
release, and they keep control of it (see [After the merge](#after-the-merge)).

## Rules for agents

- **Read the release scan.** The pull request's "Scan the release" job
  downloads the ZIP in an isolated job and reports whether the app can leave
  the sandbox and how ([Release scan](../automation.md#release-scan)). Say in
  the pull request what it found.
- **Never download or run release files.** Everything comes from the GitHub
  API: the file's SHA-256 is GitHub's digest, and "native" is judged from the
  repository's `sce_sys/param.json`.
- **Never contact the developer**, comment on their repository, or open issues
  there. Developers aren't notified: listed projects and releases are already
  public, and the developer stays responsible for their app's licensing and
  content (see the [README disclaimer](../../README.md#disclaimer)).
- **Never merge.** Open the pull request and stop; a maintainer reviews it.
- **One app per pull request**, on its own branch.
- **Stop and report** instead of guessing when a [stop condition](#stop-conditions)
  applies. A skipped app is fine; a wrong listing isn't.
- Work in a clone of this repository with `gh` logged in as a maintainer
  account (the account needs push access for the branch and pull request).

## 1. Find candidate apps

Start from what the maintainer gave you: a repository, an account, or a list.
The daily [discovery job](../automation.md#discovery) also finds candidates
on its own: apps that pass every automated check arrive as listing pull
requests (review them with steps 3 and 4), and the rest are listed in the open
`discovery` issue.

For an account, check every public, non-fork, non-archived repository for a
release and a `sce_sys/param.json`. Don't rely on GitHub code search: it often
misses repositories (it found none of SvenGDK's three native apps).

```sh
owner=<owner>
gh repo list "$owner" --visibility public --limit 200 --no-archived --source \
  --json nameWithOwner --jq '.[].nameWithOwner' |
while read -r repo; do
  release=$(gh api "repos/$repo/releases?per_page=5" \
    --jq '[.[] | select(.draft | not)][0] | if . == null then "none" else "\(.tag_name) files=\([.assets[].name] | join(","))" end')
  branch=$(gh api "repos/$repo" --jq .default_branch)
  params=$(gh api "repos/$repo/git/trees/$branch?recursive=1" \
    --jq '[.tree[].path | select(endswith("sce_sys/param.json"))] | join(",")')
  printf '%s\n  release: %s\n  param.json: %s\n' "$repo" "${release:-none}" "${params:-none}"
done
```

A repository is a candidate only when it has a published GitHub release **and**
a `sce_sys/param.json` at its root (or in the folder its README says is the
app). Skip templates, SDKs whose `param.json` files belong to samples,
libraries, drivers, payloads (`.elf` releases), desktop tools, research and
test projects: the catalog lists native apps people install on the console.

## 2. Draft the record

```sh
python3 -m catalog draft <owner>/<repository>            # newest release, pre-releases included
python3 -m catalog draft <owner>/<repository> --tag <tag> --asset <file>   # when needed
```

The draft prints the record with every fact GitHub can prove filled in, plus
three lists:

- **Blockers.** Don't submit. Report them to the maintainer.
- **To do.** Decisions you must make and justify (below).
- **Facts.** Evidence to copy into the pull request.

When there are no blockers, add `--write` to create `apps/<TITLEID>.json` with
the drafted values, then fill the empty fields in that file.

## 3. Confirm it is a native PS5 app

All of these must hold (see the [scope rule](../review-policy.md#maintainer-review)):

| Check | Evidence |
| --- | --- |
| Built for the PS5 and installed as its own title | `sce_sys/param.json` with a `PPSA…` `titleId` (the draft finds it) |
| The release file is the app itself | `.zip` of the title folder (the only format accepted at the moment; decline a listing or an update whose file is a `.ffpkg` or `.ffpfsc` image and ask for a `.zip`); install notes say to copy the title folder to `/data/homebrew/` |
| Not a payload, PS4 package, backport, ROM or web page | no `.elf`/`.bin` payload as the main file, no `CUSA` title ID, README describes a native title |
| It's the developer's own project | not a mirror or repackage of someone else's app; the README credits upstream work rather than claiming it |

Also note the app's `contentVersion` (the draft's facts and `verify` show it).
It doesn't decide the listing, but say in the pull request when it is missing
or looks never to have been raised (`01.000.000` on a later release): consoles
find updates by comparing it, so such an app can be installed from the catalog
but won't show updates ([App versions](../versioning.md)).

If the repository contains several `sce_sys/param.json` files (the draft says
so), use the one at the repository root or in the folder the README says is
the app, and ignore vendored examples.

## 4. Fill the judgment fields

| Field | How to decide |
| --- | --- |
| `name` | The `titleName` from `param.json` (drafted). Change it only to avoid a clash with an existing listing. |
| `kind` | `game` for games, `tool` for utilities and system tools, `app` for everything else (players, emulators, clients). |
| `description` | One factual sentence, at most 200 characters, from the README. No marketing, no claims the README doesn't make, no emoji. |
| `author` | How the developer credits themselves in the README or release notes (the draft suggests the GitHub profile name). |
| `license` | GitHub's detected SPDX identifier (drafted). If GitHub detects none, use the SPDX identifier the README or source headers state for the project's own code, and quote that text in the pull request. If no license is stated anywhere, stop. |

Leave `version` (the release tag, without a leading `v`), `source_repo`, `artifact_url`, `sha256` and `icon_url` as drafted.

## 5. Validate

```sh
python3 -m catalog check                     # format and catalog-wide rules
GITHUB_TOKEN=$(gh auth token) python3 -m catalog verify <TITLEID>   # GitHub release, digest, icon
python3 -m unittest discover -s tests
```

`verify` warns when GitHub detects no license; that's expected when you set the
license from the README. Any error is a stop condition.

## 6. Open the pull request

```sh
git switch -c listing/<TITLEID> origin/main
git add apps/<TITLEID>.json
git commit -m "List <name> by <author>"
git push -u origin listing/<TITLEID>
gh pr create --base main --title "List <name> by <author>" --body-file <body.md>
```

Use this body, filled from the draft's facts:

```markdown
Adds <name> (`<TITLEID>`) from <source_repo>.

**Native PS5 app:** `sce_sys/param.json` at `<tag>` has titleId `<TITLEID>` and
titleName `<titleName>`; the release notes/README say to install it by <quote>.

**Release:** <tag> (<release or pre-release>, published <date>), file `<file>`,
GitHub digest `<sha256>`.

**Judgment fields:**
- kind: <kind>, because <reason>
- description: from the README's <section>
- author: <author>, as credited in <where>
- license: <license>, <"detected by GitHub" or the README quote>

**Notes for the reviewer:** <anything unusual: pre-release only, mixed
third-party licenses, several param.json files, …>

Prepared with docs/maintainers/listing-runbook.md.
```

Then stop. The submission check runs automatically; a maintainer reviews and
merges.

## Stop conditions

Report these to the maintainer instead of opening a pull request:

| Situation | Why |
| --- | --- |
| The draft lists any blocker | The listing can't be verified. |
| The app is only published outside GitHub releases (repository files, CI artifacts, other sites), or the release tag isn't a version (`latest`, `nightly`) | The catalog needs a published release whose tag is the app's version. |
| No license stated anywhere | The catalog must show a license. |
| The main file is a payload (`.elf`, `.bin`, `.lua`) or a PS4 package | Out of scope: native apps only. |
| The title ID is already listed by a different project | Title IDs are first come, first served; a maintainer decides. |
| The repository is a fork or repackage of another developer's app | Provenance must be the original developer. |
| The app is obviously for piracy, contains commercial content, or the README asks not to be redistributed | Refused by the review policy. |
| The only file that would be listed ships emulators or files that look extracted from commercial games | Commercial content can't be linked. Backup managers themselves are in scope: list only the app's own file (use `--asset`), never a companion pack, and say so in the pull request. |
| The repository is archived with no recent release | Probably abandoned; a maintainer decides. |
| `check`, `verify` or the tests report errors | The record isn't valid. |

## After the merge

- The listing belongs to the owner of `source_repo`. The daily release-update
  job keeps it on their newest release automatically (see
  [Automation](../automation.md#release-updates)); the asset name must keep the
  same shape for that to work.
- The developer can update or correct their listing with their own pull
  request, or ask for withdrawal (see the [review policy](../review-policy.md#withdrawals)).

## Worked example: RetroArch by Mihawk

Input: `https://github.com/mihawk-99/PS5_RetroArch`.

```sh
python3 -m catalog draft mihawk-99/PS5_RetroArch
```

What the draft found:

- Release `v0.5.0-alpha.5` (pre-release), file `PS5_RetroArch-v0.5.0-alpha.5.zip`,
  GitHub digest `sha256:aa85d74e…69de`.
- `sce_sys/param.json`: titleId `PPSA99169`, titleName `RetroArch`,
  contentId `UP9000-PPSA99169_00-RETROARCH0000001`. A second `param.json` under
  `handoff/PPSA99002/` is a vendored example; the root one is the app.
- Icon `sce_sys/icon0.png` at the tag.
- **To do:** GitHub detects no license. The README's "License and third-party
  terms" section says port-authored code is GPL-3.0-or-later, with cores under
  their own licenses.

Decisions:

- Native: yes. The release notes say "Copy the complete `PPSA99169` folder to
  your homebrew title location, for example `/data/homebrew/PPSA99169/`".
- `kind`: `app` (an emulator frontend).
- `description`: "Native RetroArch port for PS5 with cores for NES, SNES, GBA,
  Genesis, arcade, PSP, GameCube/Wii and PS2." (from the README's core list; the
  repository description also mentions PS3 and N64, which the README doesn't
  list, so they're left out).
- `author`: `Mihawk` ("Maintained by Mihawk" in the README).
- `license`: `GPL-3.0-or-later`, quoted from the README. Reviewer note: some
  bundled cores (Snes9x, FBNeo, Genesis Plus GX) carry non-commercial terms.

Result: `apps/PPSA99169.json` on branch `listing/PPSA99169`, pull request
"List RetroArch by Mihawk".

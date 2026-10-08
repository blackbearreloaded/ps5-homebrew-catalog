# Automation

All checks are implemented in [`catalog/`](../catalog) with the Python standard
library and run by four workflows.

| Workflow | Trigger | Runs |
| --- | --- | --- |
| [Submission check](../.github/workflows/pull-request.yml) | Pull requests (`pull_request_target`) | `python3 -m catalog pr`, and in a second job the [release scan](#release-scan), `python3 -m catalog scan-pr` |
| [CI](../.github/workflows/ci.yml) | Pull requests and pushes to `main` | Tests, `catalog check` and a website build; on `main` also `catalog push`, then the [website deployment](website.md#deployment) |
| [Deploy fallback](../.github/workflows/deploy-fallback.yml) | Manual only, by the repository owner | The same deploy on the maintainer's own runner, for an Actions outage; see [Fallback deploy](website.md#fallback-deploy) |
| [Scan the catalog](../.github/workflows/scan-catalog.yml) | Manual only | `catalog scan`: one report on every listed app, or on the title IDs given; see [Release scan](#release-scan) |
| [Catalog health](../.github/workflows/health.yml) | Daily 06:17 UTC and manual | `catalog health --slice today` |
| [Release updates](../.github/workflows/updates.yml) | Daily 07:37 UTC and manual | `catalog updates --open-prs` |
| [Discovery](../.github/workflows/discovery.yml) | Daily 06:53 UTC and manual | `catalog discover --open-prs --issue` |

Results appear as annotations and in each run's job summary.

## Submission check

For a pull request the checker:

1. **Classifies the changed files.** Community pull requests may only add or
   modify exactly one `apps/<TITLEID>.json`, as a regular, non-executable file.
   Deletions and changes to any other file are reserved for maintainers
   (`OWNER`, `MEMBER` or `COLLABORATOR` of this repository). A pull request
   from a branch of this repository itself, rather than a fork, also counts as
   a maintainer's: only accounts and apps with write access can push one, such
   as the catalog bot's discovery and update pull requests.
2. **Validates the merged catalog.** It applies the PR's records on top of the
   current `main` and checks every record's format plus catalog-wide uniqueness
   of names, artifact URLs and digests. See [Metadata format](metadata.md).
3. **Confirms the publisher.** The PR author must own `source_repo`, or be a
   public member of the organization that owns it. A record's title ID can't be
   moved to a different repository owner by a community PR. One exception: a
   change that only moves a listed app to its repository's **newest release**
   (`version`, `artifact_url`, `sha256` and `icon_url`, same `source_repo`) is
   accepted from any account, because the repository's owner published that
   release. This is what lets the release-update bot's pull requests through.
4. **Verifies the release.** Through the GitHub API: the repository is public
   and the URL is canonical, the license agrees with GitHub's detection, the tag
   is a published release, and the asset exists and is at most 2 GiB.
5. **Verifies the bytes without downloading them.** GitHub computes a SHA-256
   digest for every release asset and reports it in the API. The check requires
   it to equal `sha256`. If the asset is ever replaced, GitHub's digest changes
   and the listing stops matching. This job never downloads, opens or
   executes an artifact (see [artifact formats](artifact-formats.md)); the
   separate [release scan](#release-scan) downloads and reads it. The format check
   still recognises `.ffpkg` and `.ffpfsc` names, so that a listing made before
   ZIP became the only accepted format keeps validating; that a new listing or
   a new release is a `.zip` is checked in review.
6. **Reads the content version.** It looks for the release's `contentVersion`
   in the repository's `sce_sys/param.json` at the release tag and reports it.
   It warns, without failing, when there is none or when it isn't higher than
   the listed release's, because consoles then can't see the release as an
   update ([App versions](versioning.md)).
7. **Checks the icon.** It fetches at most 2 MiB and requires PNG, JPEG or WebP
   content, warning when a PNG isn't square or is under 256×256.

### Why it is safe on untrusted pull requests

The workflow uses `pull_request_target`, so it runs the **base branch's**
workflow and checker, never the pull request's. It checks out `main`, fetches the
PR head as a git ref, and reads the changed records with `git show` as plain
data. PR code is never checked out or executed, so a submission can't alter the
rules it is judged by. The token is read-only, no secrets are used, this job
downloads no artifact, and the only file it fetches (the icon) is size-bounded. Actions are pinned to commit SHAs and kept current by
Dependabot.

The CI workflow does run PR code (tests), with the standard read-only
`pull_request` token and no secrets.

## Release scan

A second job of the submission check, **Scan the release**, downloads the ZIP a
pull request lists and reads it without running anything
(`python3 -m catalog scan-pr`, `catalog/scan.py`). It answers one question for
the reviewer: **can this app leave the PS5's sandbox, and how?** A title that
stays inside can crash itself; one that reaches the payload loader or ships a
payload can reach the kernel, and with it everything on the console.

The report is in the job's summary, with its warnings as annotations:

| It looks at | And reports |
| --- | --- |
| The archive | Entries that would unpack outside the app's folder, links and encrypted entries (these fail the check); where the app's folder is; Windows or macOS programs, scripts, and disk images it can't look inside |
| Every executable (`eboot.bin`, modules, payloads, libraries) | The system libraries it links to, and which functions on a watch list it imports: network, loading code at run time, making memory executable, processes, system state, installing titles, accounts. PS5 executables name imports by a hash (the NID), so the scan hashes the watch list and compares |
| Ways out of the sandbox | The payload loader's address (127.0.0.1, port 9021 or 9020) held as data or built in code; a request file for a resident jailbreak service (`elevate_proc`, `etahen_jailbreak`); payload files, with their SHA-256; executables hidden inside other files |
| Code | System call instructions the title makes itself, with their numbers (a full table of them is a statically linked system library and is reported as such); code that is packed or encrypted |
| Patterns ([`catalog/scan_rules.yar`](../catalog/scan_rules.yar)) | The payload SDK's kernel read and write routines, credential patching, raw memory, flash and disk devices, system folders, mounting |

How to read it:

- **"This app can leave the sandbox"** is common and not an accusation: half of
  the catalog elevates, usually to reach `/data`. It tells the reviewer where
  to look: the payload files and what they contain.
- **"It is unclear whether this app leaves the sandbox"** means only weak
  evidence was found, such as the loader's port number as a constant in code
  that can also connect to 127.0.0.1. Several apps share a library with such a
  constant; the source settles it.
- **"No sign that this app leaves the sandbox"** means none of the known routes
  was found. It is not proof. Code can build an address at run time or unpack a
  payload from data, and a scan of this kind won't see it.
- Only an archive that is unsafe to unpack, or unreadable, fails the check.
  Everything else is information.

### Approved helpers

A payload is the part of an app that runs outside the sandbox, so it is the
part worth reading. [`helpers/approved.json`](../helpers/approved.json) lists
the payloads a maintainer has read and accepted, each by its SHA-256. The scan
compares every payload in a release with that list:

- on the list: a note naming the entry;
- not on the list: a warning, with the payload's SHA-256.

A hash matches one exact file, and a helper is usually rebuilt for every
release, so a new release of an app that elevates is flagged until a
maintainer has looked at it. That is the intent: nothing reaches the kernel
unread. To approve, read the helper's source at the release tag, then add the
entries this prints to the list, on `main`:

```sh
python3 -m catalog scan --helpers PPSA12345
```

The pull request's check uses the list on `main`, so a pull request can't
approve its own helper.

### What changed since the listed release

When a pull request updates an app, the scan also downloads the release that
is listed now and reports the differences: a changed verdict, a new way out of
the sandbox, new or changed payloads, system functions and libraries the
executable did not use before, hosts it did not name before, and large changes
in size. A trusted app turning hostile shows up here first.

### Built by GitHub Actions?

The scan asks GitHub whether a workflow of the app's repository built exactly
this file (`gh attestation verify`, which checks the signature and the file's
digest). A developer gets this by building the release in GitHub Actions with
[`actions/attest-build-provenance`](https://github.com/actions/attest-build-provenance).
The result is one of:

- **attested**: a signed statement ties this file to a workflow run and a commit;
- **released by a workflow**: a workflow attached the file to the release, which
  shows less, since it may have been built elsewhere;
- **built by the developer**: uploaded by hand; nothing ties it to the source.

### Labels on the website and in the API

After each merge a second job, **Scan listed releases**, writes a small summary
per listed release (kept by the file's SHA-256, so a release is scanned once).
The site build reads those summaries as data and shows them on each app's page
under **Safety**, and publishes them in the store API as `safety`
([Store API](api.md#safety)). If that job fails, the site is built without the
labels rather than not at all.

### One report for the whole catalog

**Scan the catalog** is a manual workflow (Actions → Scan the catalog → Run
workflow). It scans every listed release again, or only the title IDs you give
it, and writes one report in the run's summary: an overview table (sandbox
verdict, how the app leaves it, helpers, helpers not reviewed, build
attestation) followed by the full findings for each app. It changes nothing.
Use it after changing the scanner or the approved helper list, or to see where
apps listed before the scan existed stand.

The labels on the site are refreshed by CI's **Scan listed releases** job, not
by this one; run CI by hand to refresh them without a merge.

### Isolation

The jobs are isolated because they handle files nobody has reviewed, with
libraries that parse them: no secrets, no credentials in the checkout, and a
read-only token used only to ask GitHub for build attestations.

Like the submission check, the pull request's scan runs the base branch's code,
so a pull request can't change the scanner that reads it. The deploy job, which
holds the signing key, never runs the scanner: it only reads the summaries, and
checks each field.

It uses three libraries, pinned in [`requirements-scan.txt`](../requirements-scan.txt)
and needed by nothing else: pyelftools (ELF files), Capstone (disassembly) and
yara-python (pattern rules). Without one of them, that part of the scan is
skipped and the report says so.

To scan by hand:

```sh
python3 -m pip install -r requirements-scan.txt
python3 -m catalog scan PPSA99000            # download and scan a listed release
python3 -m catalog scan                      # every listed release (about 2 GB of downloads)
python3 -m catalog scan --zip app.zip PPSA12345
```

## Push to `main`

Every push runs the tests and the offline check, then fully verifies the records
changed since the previous commit. This covers maintainer commits that don't go
through a pull request.

The deploy that follows builds the website and the [store API](api.md). For
each release it hasn't seen, the build asks GitHub for the download size and
release date and reads the content version from the repository's `param.json`;
the answers are cached with the icons, keyed by the file's sha256, so later
builds ask only about new releases. If GitHub can't be reached, the build
still succeeds: those fields are `null` for that app until the next build.

The deploy then **signs the catalog**. The build has written
`api/v1/manifest.json`, the hash of every JSON file of the API; a separate
step, the only one that sees the key, signs it with `openssl` and writes
`manifest.sig` (`python3 -m catalog sign --require`). The key is the
`CATALOG_SIGNING_KEY` secret of the `cloudflare-pages` environment, an Ed25519
private key in PEM form that is never in the repository. The step fails, and
nothing is deployed, if the key is missing or isn't one of the public keys in
[`keys/`](../keys): consoles would refuse such a catalog. A second key pair
exists as a spare; its private half is kept offline by the maintainer and its
public half is in `keys/` too. To switch to it, replace the secret with the
spare's private key. The keys don't expire. See
[Verifying the catalog](api.md#verifying-the-catalog).

## Daily health check

Every day it re-verifies one seventh of the catalog (release still published,
GitHub's digest still equal to `sha256`, icon reachable), so each record is
checked once a week. A record's day is fixed by a hash of its title ID. Nothing
is downloaded, and at 1,000 apps a day's run makes about 430 GitHub API calls,
well within CI's limits. It also reports projects that have published a newer
release than the one listed, and warns about reservations that haven't changed
in 180 days. Run it manually with **slice: all** to check everything at once.

A reservation has no repository, file or icon to verify. For those, the
submission check confirms who may change them instead: it looks up the commit
that added the file and only lets that account update or release the
reservation, and it enforces the limit of 5 reservations per account.
A failure notifies maintainers; see the [review policy](review-policy.md) for
how broken listings are handled.

## Release updates

Every day the [Release updates](../.github/workflows/updates.yml) workflow asks
GitHub for the newest release of every listed app, pre-releases included. All
the apps with a newer release go into **one pull request**, on the branch
`catalog-update/all`, authored by the catalog's GitHub App. While it is open,
each run rebuilds it from `main` with the current set of updates, so it never
goes stale. For each app:

- **File:** the release asset with the same file type that is the listed file's
  successor: the same name, the same name with the new version, or the only
  file of that type. If none matches unambiguously, the app is reported and
  skipped.
- **Version:** taken from the release tag, in the record's existing style
  (`v0.6.0` becomes `0.6.0` when the listed version has no `v`).
- **sha256:** GitHub's digest of that asset. Nothing is downloaded.
- **Icon:** a tag-pinned `icon_url` moves to the new tag if the icon exists
  there; otherwise it stays as it is.
- **Content version:** the pull request says how `contentVersion` changes
  between the listed and the new release, and points out a release that
  consoles won't see as an update because the developer didn't raise it.

The pull request shows each app's old and new values side by side, and the
normal submission check verifies every record in it. Merge it to publish the
updates. If you close it without merging, none of the versions in it is
proposed again; each app comes back with its next release. To publish some
updates and skip others, revert the unwanted record on the branch before
merging; that app is proposed again on the next run. Run
`python3 -m catalog updates` locally to see what would be proposed.

### Setting up the GitHub App (once)

Pull requests opened with the workflow's built-in token wouldn't trigger the
submission check, so the job acts as a small GitHub App instead.

1. **Create the app:** under **Settings → Developer settings → GitHub Apps →
   New GitHub App** on your account:
   - Name: anything, e.g. `ps5-catalog-bot`. Homepage URL: this repository.
   - Webhook: untick **Active**.
   - Repository permissions: **Contents: Read and write**, **Pull requests:
     Read and write** (Metadata: Read-only is added automatically). Nothing else.
   - Where can it be installed: **Only on this account**.
2. **Install it:** from the app's page, choose **Install App** → **Only select
   repositories** → this repository.
3. **Create a key:** on the app's settings page, choose **Generate a private
   key**. A `.pem` file downloads.
4. **Store the credentials in GitHub**, not in the repository files:
   - **Settings → Environments → New environment** `catalog-bot`, with
     deployment branches limited to `main`, and the environment secret
     `CATALOG_BOT_PRIVATE_KEY` holding the whole `.pem` file.
   - The variable `CATALOG_BOT_CLIENT_ID` holding the app's **Client ID**
     (shown on the app's settings page), either in the same environment or as
     a repository variable. The workflow does nothing while it is unset.
   - Then delete the downloaded `.pem` file.
5. **Test it:** **Actions → Release updates → Run workflow**.

If the `main` ruleset restricts who may create branches, allow the app to push
`catalog-update/all` branch.

## Discovery

Every day the [Discovery](../.github/workflows/discovery.yml) workflow searches
public GitHub for native PS5 apps the catalog doesn't list yet. It only reads
other repositories: nothing is downloaded and developers aren't contacted.

1. **Find.** Code searches for `sce_sys/param.json` files and build scripts
   with a `PPSA` title ID (strong signals), README install instructions and
   mentions of ShadowMountPlus, `.ffpfsc` or `.ffpkg`; repository searches
   (`ps5 homebrew`, the `ps5` and `ps5-homebrew` topics, `prospero` in the
   name); and the other repositories of developers who are listed or have a
   strong signal.
2. **Skip.** Repositories already listed, title IDs already in the catalog,
   repositories in [`discovery/ignore.txt`](../discovery/ignore.txt), and apps
   whose listing pull request is open or was closed without merging.
3. **Check,** strongest candidates first (600 per run): a published release
   with a `.zip`, `.ffpkg` or `.ffpfsc` file, then everything
   `catalog draft` checks. Only a `.zip` is accepted at the moment, so a
   proposal whose file is an image is closed in review.
4. **Propose.** An app with no blockers, a license GitHub detects and an icon
   next to its `param.json` gets a listing pull request on `listing/<TITLEID>`
   from the catalog's GitHub App (at most 10 new ones a run). The job guesses
   `kind` from keywords and `description` from the repository's About text or
   README, and says so in the pull request.
5. **Report.** The open issue labelled `discovery` is rewritten with the pull
   requests, apps that need review (for example a `param.json` generated at
   build time) and native projects without a release yet. 🆕 marks
   repositories new since the previous run.

Review a discovery pull request like any listing: steps 3 and 4 of the
[listing runbook](maintainers/listing-runbook.md), editing the record on the
branch if a guess is wrong. Merge it to list the app. Close it without merging
to reject it; the job won't propose that app again. To stop a repository from
appearing at all, add it to `discovery/ignore.txt` with a reason. Run
`python3 -m catalog discover` locally (with `GITHUB_TOKEN` set) to print the
report without opening anything.

## Recommended repository settings

Maintainers should protect `main` with a ruleset for pull requests that:

- requires the **Validate submission** and **Tests and offline check** status
  checks to pass,
- requires one approving review, and
- blocks force pushes and deletion.

Also allow only **squash merging** for pull requests. The squash commit is
authored by the pull request's author, which is how the submission check knows
who holds a reservation. If that commit can't be linked to a GitHub account, a
maintainer has to review changes to the reservation.

Maintainers can keep a bypass for direct pushes, which are still verified by the
push workflow.

## Running checks locally

```sh
python3 -m catalog check                   # offline format check of apps/
python3 -m catalog verify [TITLEID ...]    # online checks for some or all records
python3 -m catalog digest <artifact_url>   # sha256 as reported by GitHub
python3 -m catalog health [--slice today]  # what the daily job runs (default: all)
python3 -m catalog updates [TITLEID ...]   # newer releases that would be proposed
python3 -m catalog draft <owner>/<repo>     # draft a listing (see maintainers/listing-runbook.md)
python3 -m unittest discover -s tests
```

Set `GITHUB_TOKEN` (for example `GITHUB_TOKEN=$(gh auth token)`) to avoid the
anonymous API limit of 60 requests per hour.

# Automation

All checks are implemented in [`catalog/`](../catalog) with the Python standard
library and run by four workflows.

| Workflow | Trigger | Runs |
| --- | --- | --- |
| [Submission check](../.github/workflows/pull-request.yml) | Pull requests (`pull_request_target`) | `python3 -m catalog pr` |
| [CI](../.github/workflows/ci.yml) | Pull requests and pushes to `main` | Tests, `catalog check` and a website build; on `main` also `catalog push`, then the [website deployment](website.md#deployment) |
| [Catalog health](../.github/workflows/health.yml) | Daily 06:17 UTC and manual | `catalog health --slice today` |
| [Release updates](../.github/workflows/updates.yml) | Daily 07:37 UTC and manual | `catalog updates --open-prs` |

Results appear as annotations and in each run's job summary.

## Submission check

For a pull request the checker:

1. **Classifies the changed files.** Community pull requests may only add or
   modify exactly one `apps/<TITLEID>.json`, as a regular, non-executable file.
   Deletions and changes to any other file are reserved for maintainers
   (`OWNER`, `MEMBER` or `COLLABORATOR` of this repository).
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
   and the listing stops matching. Artifacts are never downloaded, opened or
   executed (see [artifact formats](artifact-formats.md)).
6. **Checks the icon.** It fetches at most 2 MiB and requires PNG, JPEG or WebP
   content, warning when a PNG isn't square or is under 256×256.

### Why it is safe on untrusted pull requests

The workflow uses `pull_request_target`, so it runs the **base branch's**
workflow and checker, never the pull request's. It checks out `main`, fetches the
PR head as a git ref, and reads the changed records with `git show` as plain
data. PR code is never checked out or executed, so a submission can't alter the
rules it is judged by. The token is read-only, no secrets are used, artifacts
are never downloaded, and the only file fetched (the icon) is size-bounded. Actions are pinned to commit SHAs and kept current by
Dependabot.

The CI workflow does run PR code (tests), with the standard read-only
`pull_request` token and no secrets.

## Push to `main`

Every push runs the tests and the offline check, then fully verifies the records
changed since the previous commit. This covers maintainer commits that don't go
through a pull request.

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
GitHub for the newest release of every listed app, pre-releases included. For
each app with a newer release it opens, or refreshes, one pull request on the
branch `catalog-update/<TITLEID>`, authored by the catalog's GitHub App:

- **File:** the release asset with the same file type that is the listed file's
  successor: the same name, the same name with the new version, or the only
  file of that type. If none matches unambiguously, the app is reported and
  skipped.
- **Version:** taken from the release tag, in the record's existing style
  (`v0.6.0` becomes `0.6.0` when the listed version has no `v`).
- **sha256:** GitHub's digest of that asset. Nothing is downloaded.
- **Icon:** a tag-pinned `icon_url` moves to the new tag if the icon exists
  there; otherwise it stays as it is.

The pull request shows the old and new values side by side, and the normal
submission check runs on it. Merge it to publish the update. If you close it
without merging, that version isn't proposed again; the next release is. Run
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
`catalog-update/*` branches.

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

# Submitting an app

This guide takes a PS5 homebrew app from a GitHub release to a catalog listing.
Everything is checked automatically when you open the pull request; a maintainer
then reviews and merges it.

## Requirements

- A **native PS5 app**: built for the PS5 and installed as a title with its own
  title ID (`eboot.bin` and `sce_sys/param.json`). ELF payloads, PS4 packages,
  backports, emulator ROMs and web pages aren't listed.
- A **public GitHub repository** for the app, with a license GitHub can detect.
- A **published GitHub release** in that repository, tagged with the app's
  version (for example `v1.2.0` or `01.000.005`), with a **release artifact**
  attached to it: a `.zip` of the app folder, the only format accepted at the
  moment (see [artifact formats](artifact-formats.md)). Pre-releases are accepted; files in the repository, drafts,
  CI artifacts and other download sites aren't. The release tag **is** the
  version the catalog shows.
- A **`contentVersion` you raise in every release**, in `sce_sys/param.json`
  in your repository, in the PlayStation format (`01.000.070`). It isn't
  required for a listing, but it is how a console knows an installed copy is
  outdated; see [App versions](versioning.md).
- **A distinct app.** A fork or derivative of a listed app must be
  substantially different for the user (a different core or engine, a
  different purpose, or features the original doesn't have and won't take),
  not only a new name, theme or icon; contribute those to the original
  project instead. Its name doesn't include the listed app's name. See the
  [review policy](review-policy.md#maintainer-review).
- A **category**: the shelf your app is shown on, one of the eleven in
  [Categories](metadata.md#categories). Pick the one people would look in
  first; the reviewer may suggest another.
- A **title ID** no other listed app uses.
- A **square icon** at a stable HTTPS URL: PNG, JPEG or WebP, **512×512
  recommended** (256×256 at least), at most 2 MiB. That is exactly the PS5's
  own `sce_sys/icon0.png` (512×512 PNG), so pointing at that file in your
  repository is the simplest choice. The site and the store show icons at up
  to 512 px; a larger image is scaled down, and one that isn't square is
  cropped to a square on the website.
- The pull request must come from the **account that owns the repository**. For
  an organization's repository, your membership of that organization must be
  [public](https://docs.github.com/en/account-and-profile/setting-up-and-managing-your-personal-account-on-github/managing-your-membership-in-organizations/publicizing-or-hiding-organization-membership).

## 1. Choose a title ID

Your title ID is the app's permanent identity: the record's filename, the
`titleId` in `sce_sys/param.json`, and the folder name on the console. It is
four uppercase letters followed by five digits.

- Check that `apps/<TITLEID>.json` does not already exist. Title IDs are
  first come, first served.
- Don't reuse a template default. `PPSA99999` (the native app boilerplate's
  default) is rejected.
- Keep it for the life of the app. Changing it makes the console treat the app
  as a different title with separate save data.

## 2. Publish the artifact

Build a `.zip` of the `<TITLEID>/` app folder, with that folder at the top of
the archive. It is the only [artifact format](artifact-formats.md) accepted at
the moment; `.ffpkg` and `.ffpfsc` images aren't.

Attach it to a [GitHub release](https://docs.github.com/en/repositories/releasing-projects-on-github/managing-releases-in-a-repository)
and publish the release (a draft isn't downloadable). Name the tag after the
app's version: the record's `version` must be that tag, or the tag without a
leading `v` (tag `v1.2.0` → version `1.2.0` or `v1.2.0`; tag `01.000.005` →
version `01.000.005`). Don't use generic or moving tags such as `latest`,
`nightly` or `release`.

Before you build, raise `contentVersion` in `sce_sys/param.json` and commit
it, so the tag points at the value the release ships. Tagging releases with
the content version itself (`01.000.005`) keeps everything in one number.
[App versions](versioning.md) has the rules and a release checklist.

Write the release's description with care: it becomes your app's release
notes on the website and in the store. Put what changed first, under short
headings with bullet lists; images, links and HTML aren't carried over. See
[Write release notes](../README.md#write-release-notes).

Use a new tag and a new asset for every version; never replace the asset of a
release that is already listed, because its sha256 would no longer match. Enabling GitHub's
[immutable releases](https://docs.github.com/en/code-security/supply-chain-security/understanding-your-software-supply-chain/immutable-releases)
for your repository makes that guarantee explicit.

## 3. Get the sha256

The catalog pins the exact bytes of your artifact. Any of these give the value:

```sh
python3 -m catalog digest https://github.com/<owner>/<repo>/releases/download/<tag>/<asset>.zip
sha256sum PPSA01234.zip          # Linux / WSL
shasum -a 256 PPSA01234.zip      # macOS
```

GitHub also shows the digest next to each asset on the release page. Use
lowercase hexadecimal, without a `sha256:` prefix.

## 4. Write the record

Fork this repository and add `apps/<TITLEID>.json`:

```json
{
  "titleid": "PPSA01234",
  "name": "Example App",
  "kind": "app",
  "category": "utilities",
  "description": "One short sentence about the app.",
  "license": "GPL-3.0",
  "author": "Example Dev",
  "version": "01.000.000",
  "source_repo": "https://github.com/example/example-app",
  "artifact_url": "https://github.com/example/example-app/releases/download/01.000.000/PPSA01234.zip",
  "sha256": "<64 lowercase hex characters>",
  "icon_url": "https://raw.githubusercontent.com/example/example-app/01.000.000/sce_sys/icon0.png"
}
```

Every field is described in [Metadata format](metadata.md). Pin `icon_url` to a
tag or commit so the icon can't change under the listing.

## 5. Check locally (optional)

```sh
python3 -m catalog check              # format only, no network
python3 -m catalog verify PPSA01234   # the same online checks CI runs
```

`verify` compares `sha256` with the digest GitHub reports for your release
asset; it doesn't download the file.

## 6. Open the pull request

Open it from the account that owns `source_repo`, changing only your one record.
The **Validate submission** check reports every problem it finds in the job
summary. Push fixes to the same branch; the check reruns automatically.

When it passes, a maintainer reviews the listing against the
[review policy](review-policy.md) and merges it. The website updates after the
merge.

## Reserving a title ID

Working on something that isn't released yet? Reserve its title ID so nobody
else takes it. The website shows it as **Coming soon**, with no download.

A reservation is a normal record with its links left empty: `source_repo`,
`artifact_url` and `icon_url` are `null`, and so is `sha256`.

```json
{
  "titleid": "PPSA01234",
  "name": "Example Game",
  "kind": "game",
  "description": "One short sentence about the game.",
  "license": null,
  "author": "Example Dev",
  "version": null,
  "source_repo": null,
  "artifact_url": null,
  "sha256": null,
  "icon_url": null
}
```

- `version` and `license` may be `null` or filled in.
- The reservation belongs to the GitHub account that opens the pull request
  that adds it. Only that account can later update it or release the app.
- Each account can hold up to 5 reservations at a time.
- Keep the reservation alive by updating it at least every 180 days. Stale
  reservations are flagged by the health check and may be released; see
  the [review policy](review-policy.md#reservations).

**To release it,** fill in every field (see [Metadata format](metadata.md)) in a
new pull request from the same account. That account must also own the
`source_repo` you add. The card becomes downloadable after the merge.

## Updating your app

Usually nothing to do: the catalog checks for new releases every day and opens
a pull request that moves your listing to the newest one (pre-releases
included). For that to work, keep your asset name stable, or change only the
version inside it (`example-0.5.0.zip` → `example-0.6.0.zip`), pin
`icon_url` to a tag, and raise `contentVersion` in every release so consoles
see it as an update ([App versions](versioning.md)). You can also update yourself: publish a new release, then
open a pull request that edits your record's `version`, `artifact_url`,
`sha256` and, if needed, `icon_url`. The same
ownership rule applies: only the owner of the listed repository can update it.
Moving an app to a different repository owner requires a maintainer; open an
[ownership transfer issue](https://github.com/darkxex/ps5-homebrew-catalog/issues/new/choose).

The catalog lists one current release per app. Older releases stay available in
your repository.

## Why isn't my app listed?

The daily [discovery job](automation.md#discovery) looks for native PS5 apps on
GitHub and reports the ones it can't list yet. Nobody is contacted: if your
project turns up there, the report names what blocks it. Fix it in your own
repository and publish a new release; the next scan picks it up, or you can
[open the pull request](#6-open-the-pull-request) yourself.

| What the report says | What to do |
| --- | --- |
| No published release | Publish a GitHub release (not a draft) with a `.zip` of the app folder attached. Files in the repository and CI artifacts aren't enough. |
| The release has several installable files | Attach one `.zip` of the app folder. Keep other files (`.elf` payloads, installers, source archives) out of the release, or name the app's file the way your README says. |
| No `sce_sys/param.json` at the release tag | Commit `sce_sys/param.json` with your `titleId` and `contentVersion`. If your build generates it, commit a copy where the catalog can read it, at the root or in the folder the README names as the app. |
| `param.json` is in a sample or test folder | Put the app's own `sce_sys/param.json` at the root, or point your README at the folder that holds the app. |
| The title ID isn't a PS5 (`PPSA`) title ID | Use a `PPSA` plus five digits title ID, such as `PPSA01234`. |
| GitHub detects no license | Add a `LICENSE` file GitHub recognizes (an SPDX license such as `GPL-3.0` or `MIT`). |
| No description to draft from | Add a repository description or a short README paragraph saying what the app does. |
| Native, but no release yet | Publish your first release as above. Only you can do that. |
| The name or title ID is already listed | Choose a distinct name or title ID; see [Common check failures](#common-check-failures). |

A `.ffpkg` or `.ffpfsc` image isn't accepted yet; use a `.zip`
([artifact formats](artifact-formats.md)).

## Common check failures

| Message contains | Fix |
| --- | --- |
| `does not own` | Open the PR from the repository owner's account, or make your organization membership public. |
| `sha256 does not match` | Recompute the digest of the exact asset in `artifact_url`. |
| `artifact_url must be` | Link a specific release asset ending in `.zip`. |
| `version must match the release tag` | Set `version` to the tag in `artifact_url`, optionally without its leading `v`. |
| `no contentVersion found` (warning) | Commit `sce_sys/param.json` with your `titleId` and a `contentVersion` like `01.000.070`, or tag releases with the content version. See [App versions](versioning.md). |
| `contentVersion … is not higher` (warning) | Raise `contentVersion` in every release; consoles compare it to find updates. |
| `license ... does not match` | Use the SPDX identifier GitHub shows for your repository. |
| `name duplicates` | Another app already uses that name; choose a distinct one. |
| `canonical URL` | Match the repository's exact owner/name capitalization. |
| `may change only apps/` | Remove changes to other files from the PR. |
| `must be null in a reservation` | With `artifact_url` null, `source_repo`, `icon_url` and `sha256` must be null too. |
| `must not be null` | Only reservations may use `null`, and only for the link, hash, version and license fields. |
| `reserved by @…` | Only the account that reserved the title ID can change it. |
| `already holds 5 reservations` | Release or remove one of your reservations first. |

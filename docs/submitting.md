# Submitting an app

This guide takes a PS5 homebrew app from a GitHub release to a catalog listing.
Everything is checked automatically when you open the pull request; a maintainer
then reviews and merges it.

## Requirements

- A **native PS5 app**: built for the PS5 and installed as a title with its own
  title ID (`eboot.bin` and `sce_sys/param.json`). ELF payloads, PS4 packages,
  backports, emulator ROMs and web pages aren't listed.
- A **public GitHub repository** for the app, with a license GitHub can detect.
- A **release artifact** (`.zip`, `.ffpfsc` or `.ffpkg`, see
  [artifact formats](artifact-formats.md)) attached to a published release of
  that repository. Pre-releases are accepted.
- A **title ID** no other listed app uses.
- A **square icon** (PNG, JPEG or WebP, 256×256 or larger, at most 2 MiB) at a
  stable HTTPS URL. Your `sce_sys/icon0.png` in the repository works well.
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

Build one of the supported [artifact formats](artifact-formats.md): a `.zip`
of the `<TITLEID>/` app folder, a `.ffpfsc` image, or a `.ffpkg`.

Attach it to a release. Use a new tag and a new asset for every version; never
replace the asset of a release that is already listed, because its sha256 would
no longer match. Enabling GitHub's
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
version inside it (`example-0.5.0.zip` → `example-0.6.0.zip`), and pin
`icon_url` to a tag. You can also update yourself: publish a new release, then
open a pull request that edits your record's `version`, `artifact_url`,
`sha256` and, if needed, `icon_url`. The same
ownership rule applies: only the owner of the listed repository can update it.
Moving an app to a different repository owner requires a maintainer; open an
[ownership transfer issue](https://github.com/blackbearreloaded/ps5-homebrew-catalog/issues/new/choose).

The catalog lists one current release per app. Older releases stay available in
your repository.

## Common check failures

| Message contains | Fix |
| --- | --- |
| `does not own` | Open the PR from the repository owner's account, or make your organization membership public. |
| `sha256 does not match` | Recompute the digest of the exact asset in `artifact_url`. |
| `artifact_url must be` | Link a specific release asset ending in `.zip`, `.ffpfsc` or `.ffpkg`. |
| `license ... does not match` | Use the SPDX identifier GitHub shows for your repository. |
| `name duplicates` | Another app already uses that name; choose a distinct one. |
| `canonical URL` | Match the repository's exact owner/name capitalization. |
| `may change only apps/` | Remove changes to other files from the PR. |
| `must be null in a reservation` | With `artifact_url` null, `source_repo`, `icon_url` and `sha256` must be null too. |
| `must not be null` | Only reservations may use `null`, and only for the link, hash, version and license fields. |
| `reserved by @…` | Only the account that reserved the title ID can change it. |
| `already holds 5 reservations` | Release or remove one of your reservations first. |

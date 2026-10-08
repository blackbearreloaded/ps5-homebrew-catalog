# Store API

The catalog publishes itself as static JSON under
`https://homebrew.page/api/v1/`, for a console store, for apps that check
whether they have an update, and for any other client. This page is the
specification: the files, every field, how to find updates, and what stays
stable.

The API is generated from the records in [`apps/`](../apps) on every merge to
`main`. The records are the single source of truth; nothing is edited in the
API itself, and there is no server behind it, only files on a CDN.

## Files

| Path | Holds | Size | Use it to |
| --- | --- | --- | --- |
| [`/api/v1/versions.json`](https://homebrew.page/api/v1/versions.json) | The current version of every available app | about 65 bytes per app | check many installed apps for updates in one request |
| [`/api/v1/index.json`](https://homebrew.page/api/v1/index.json) | One compact entry per app, reservations included | about 330 bytes per app | show the catalog as a list |
| `/api/v1/apps/<TITLEID>.json` | Everything about one app | about 1 KB | show one app, install it, or let an app check itself |
| [`/api/v1/manifest.json`](https://homebrew.page/api/v1/manifest.json) and `manifest.sig` | The hash of every JSON file above, the catalog's sequence number, and a signature over both | about 90 bytes per app | verify that the catalog is genuine before installing from it |
| `/api/v1/icons/<TITLEID>.png` | The app's icon as PNG, at most 512 px on its longer side | varies | show the icon without a WebP decoder |
| `/api/v1/icons/<TITLEID>-256.png` | The same, at most 256 px | varies | lists and grids |

Sizes are uncompressed and for planning only. All JSON is UTF-8 and minified.
An unknown title ID answers with HTTP 404 (and an HTML body, which clients
ignore).

The older [`/catalog/v1.json`](website.md#older-feed-catalogv1json) feed is
still published and unchanged; new clients should use the API.

## One app: `apps/<TITLEID>.json`

```json
{
  "schema": 3,
  "titleid": "PPSA99039",
  "name": "EVO Player",
  "kind": "app",
  "description": "Media player for PS5 that plays video from USB or internal storage, …",
  "license": "GPL-3.0",
  "author": "Sain Saji",
  "version": "0.10.0",
  "source_repo": "https://github.com/sainsaji/EVO-PLAYER-PS5",
  "artifact_url": "https://github.com/sainsaji/EVO-PLAYER-PS5/releases/download/v0.10.0/EVOPlayer-v0.10.0-PPSA99039.ffpfsc",
  "sha256": "a2b14616a2662a5e8401aad9012ba1c0d3df68211e5b70039eedfb9a0845a0be",
  "icon_url": "https://raw.githubusercontent.com/sainsaji/EVO-PLAYER-PS5/v0.10.0/projects/evoplayer/sce_sys/icon0.png",
  "status": "available",
  "content_version": "01.000.001",
  "format": "ffpfsc",
  "artifact_name": "EVOPlayer-v0.10.0-PPSA99039.ffpfsc",
  "size": 21561344,
  "tag": "v0.10.0",
  "released": "2026-09-22T18:23:50Z",
  "prerelease": false,
  "release_url": "https://github.com/sainsaji/EVO-PLAYER-PS5/releases/tag/v0.10.0",
  "release_notes": "EVO is a real PS5 app now. It runs as a game-category app module, …\n\nA Real Application\n- Game-category app module (PPSA99039). …",
  "release_notes_truncated": true,
  "safety": {"sandbox": "leaves", "routes": ["service"], "helpers": 0, "helpers_unapproved": 0, "network": true, "build": "developer", "build_workflow": null},
  "updated": "2026-09-29T17:20:37Z",
  "page": "https://homebrew.page/app/PPSA99039/",
  "icon": "https://homebrew.page/api/v1/icons/PPSA99039.png?v=5b0c1e7a9d3f4a26",
  "icon_small": "https://homebrew.page/api/v1/icons/PPSA99039-256.png?v=5b0c1e7a9d3f4a26",
  "icon_hash": "5b0c1e7a9d3f4a26"
}
```

The first eleven fields after `schema` are the app's record, exactly as in
[Metadata format](metadata.md). The build adds the rest:

| Field | Type | Meaning |
| --- | --- | --- |
| `schema` | integer | Schema revision of this file; see [Versioning of the API](#versioning-of-the-api). |
| `status` | string | `available`: the app has a release and can be installed. `coming_soon`: the title ID is [reserved](submitting.md#reserving-a-title-id) and nothing can be downloaded yet. |
| `content_version` | string or null | The release's `contentVersion` from its `sce_sys/param.json`, in the PlayStation format `NN.NNN.NNN` (`01.000.070`). **This is the value to compare with an installed copy**; see [Finding updates](#finding-updates). `null` when it isn't known. |
| `format` | string or null | `zip` for every app accepted now: the app folder in an archive. A listing made before ZIP became the only accepted format can still be `ffpkg` or `ffpfsc` (an image file); a client that installs only `zip` should show such an app as not installable. See [Artifact formats](artifact-formats.md). |
| `artifact_name` | string or null | File name of the download. |
| `size` | integer or null | Size of the download in bytes. |
| `tag` | string or null | The GitHub release tag. `version` is this tag, or this tag without a leading `v`. |
| `released` | string or null | When the developer published the release. |
| `prerelease` | boolean or null | Whether the developer marked the release as a pre-release. The catalog lists an app's newest release, pre-releases included. |
| `release_url` | string or null | The release's page on GitHub, with the developer's notes. |
| `release_notes` | string or null | What the developer wrote on the listed release, as plain text: at most 4,000 characters, lines separated by `\n`, list items starting with `- `, and a blank line before each heading or new paragraph. `null` when the release has no notes (empty, or only GitHub's generated changelog link) and for `coming_soon` apps. See [Release notes](#release-notes). |
| `safety` | object or null | What an automatic scan of the release file found; `null` when the release wasn't scanned. See [Safety](#safety). |
| `release_notes_truncated` | boolean or null | `true` when the notes were longer than the limit and were cut at the end of a block; the rest is at `release_url`. `null` when `release_notes` is. |
| `updated` | string or null | When the app's record last changed in the catalog. |
| `page` | string | The app's page on the website. |
| `icon` | string or null | PNG icon, at most 512 px on its longer side. |
| `icon_small` | string or null | PNG icon, at most 256 px. Falls back to `icon` when only one size exists. |
| `icon_hash` | string or null | Fingerprint of the app's icon: 16 hexadecimal characters that change when, and only when, the developer's image changes. `null` when there is no icon. See [Caching icons](#caching-icons). |

Rules that hold for every file:

- **Times** are ISO 8601 in UTC with a `Z`: `2026-09-22T18:23:50Z`.
- **`null` means unknown or not applicable**, never an empty string. In a
  reservation every release field is `null`. In an available app, `size`,
  `released`, `prerelease` and `content_version` can still be `null` for a
  while after a new release is listed, when GitHub couldn't be asked during
  that build; the next build fills them in. Clients must cope with both.
- **`artifact_url` and `sha256` are never `null` for an available app.** They
  are the reviewed part of the listing.
- **Icons are optional.** Use your own placeholder when `icon` is `null`.

### Installing from this file

1. Download `artifact_url`. It redirects to GitHub's file host; follow
   redirects.
2. Compute the SHA-256 of what you downloaded and compare it with `sha256`,
   taken from an app file you have [verified](#verifying-the-catalog).
   **Install nothing that doesn't match.** The developer replacing a release
   file changes its hash; the catalog's daily health check then flags the
   listing.
3. Install according to `format` ([Artifact formats](artifact-formats.md)):
   for `zip`, extract the app folder. Don't install a format you don't handle.

`size` lets a client show progress and check free space first; when it is
`null`, use the download's `Content-Length`.

### Release notes

`release_notes` answers "what is in this version?" for a store's app page or
update screen. It is only in this file, not in the index or the version map.

- **It is the developer's text, not the catalog's.** Nobody reviews it, and the
  developer can change it at any time; the catalog reads it again when the
  site is rebuilt, at most once a day. Show it as the developer's words. It is covered by the catalog's
  signature like the rest of the file, which proves only that the catalog
  published it.
- **It is plain text.** The build reads the release's GitHub Markdown and keeps
  headings, paragraphs and list items; images are dropped, links keep their
  text, tables become one line per row, and raw HTML keeps only what it
  encloses. A client needs no Markdown or HTML parser: split on `\n`, and
  treat a line that starts with `- ` as a list item if it wants bullets.
- **It can be any language** the developer wrote in, with any Unicode
  characters, emoji included; draw what the font has and skip the rest.
- **It is often more than a list of changes.** Many releases also carry install
  steps or requirements, and a first release usually describes the app.

### Safety

`safety` tells a store what it can say about an app before the user installs
it. It comes from a scan that reads the release file and never runs it
([Release scan](automation.md#release-scan)).

| Field | Type | Meaning |
| --- | --- | --- |
| `sandbox` | string | `stays`: no way out of the PS5's sandbox was found. `leaves`: the app can get full access to the console. `unclear`: weak signs only. |
| `routes` | array of strings | How it leaves: `loader` (connects to the payload loader), `service` (asks a resident jailbreak service), `payload` (ships a helper that runs outside the sandbox). Empty for `stays`. |
| `helpers` | integer | Helper programs in the release that run outside the sandbox. |
| `helpers_unapproved` | integer | How many of them the catalog's maintainers have not reviewed. |
| `network` | boolean | Whether any executable imports network functions. |
| `build` | string or null | `attested`: GitHub holds a verified statement that a workflow of the app's repository built this exact file. `workflow`: a workflow attached the file to the release. `developer`: uploaded by hand. `null`: unknown. |
| `build_workflow` | string or null | For `attested`, the workflow that built it. |

How to use it:

- **It is advice, not a guarantee.** The scan sees what honest code does; code
  can hide from it. Say "no way out of the sandbox was found", not "safe".
- **`leaves` is common and often fine.** Many apps elevate to read and write
  `/data`. It is the fact a user should know before trusting a developer.
- **Treat a missing object as unknown,** not as `stays`.

`index.json` carries `sandbox` alone (the same three values, or `null`), for a
badge in lists.

## The list: `index.json`

```json
{
  "schema": 3,
  "generated": "2026-10-02T18:26:14Z",
  "commit": "bbb7e4475b867c486a05d1639023df3f03edc28e",
  "count": 18,
  "apps": [
    {
      "titleid": "PPSA99002",
      "status": "available",
      "name": "ProsperoLight",
      "kind": "app",
      "author": "BlackBearReloaded",
      "version": "01.000.070",
      "content_version": "01.000.070",
      "format": "zip",
      "size": 36383357,
      "released": "2026-10-01T01:50:46Z",
      "updated": "2026-10-01T04:17:55Z",
      "icon_small": "https://homebrew.page/api/v1/icons/PPSA99002-256.png",
      "icon_hash": "9f2c4d7e1a6b3c58"
    }
  ]
}
```

`apps` is sorted by title ID and includes reservations (`status` tells them
apart). Each entry is a subset of the app's own file, with the same meanings;
fetch `apps/<TITLEID>.json` for the description, license, download and hash.
`icon_hash` is there so a list can keep its icons; see [Caching icons](#caching-icons).
`generated` and `commit` say which build of the catalog this is; `count` is the
length of `apps`.

## Versions: `versions.json`

```json
{
  "schema": 3,
  "apps": {
    "PPSA99002": { "content_version": "01.000.070", "version": "01.000.070" },
    "PPSA99039": { "content_version": "01.000.001", "version": "0.10.0" },
    "PPSA99420": { "content_version": null, "version": "0.9" }
  }
}
```

Every available app, keyed by title ID; reservations aren't in it. It changes
only when an app's version does.

## Finding updates

The console reports a `contentVersion` for every installed title, read from the
title's `sce_sys/param.json`. The catalog publishes the same value for the
listed release as `content_version`, so no client has to guess what a release
tag means.

**Format.** `NN.NNN.NNN`: two digits, three digits, three digits
(`01.000.070`). Compare two versions as three integers, left to right;
comparing the strings character by character gives the same order.

**The rule.** An update is available when the catalog's `content_version` is
**higher** than the installed `contentVersion`.

| Catalog `content_version` | Installed `contentVersion` | Result |
| --- | --- | --- |
| `01.000.070` | `01.000.060` | Update available |
| `01.000.070` | `01.000.070` | Up to date |
| `01.000.070` | `01.000.080` | Up to date: the installed copy is newer than the listing (a development build, or a release the catalog hasn't picked up yet) |
| `null` | anything | Unknown: say so, or say nothing. Don't offer an update. |
| anything | not in the format | Unknown |

`version` is for display. It is the developer's release tag (`0.10.0`,
`vk-285-117`), has no defined order, and must not be used to decide whether an
update exists.

When `content_version` is `null`, the developer hasn't given the catalog a way
to read it; [App versions](versioning.md) explains what they need to do.
Clients can still show the app and install it.

### An app checking itself

1. `GET https://homebrew.page/api/v1/apps/<your title ID>.json`.
2. If the answer isn't HTTP 200, `status` isn't `available`, or
   `content_version` is `null`, stop: there is nothing to report.
3. Compare `content_version` with the `contentVersion` of your own
   `param.json` using the rule above.
4. If there is an update, tell the user and point them at `page` or
   `release_url`. Show `version` as the name of the new release.

Do this in the background, at most once per launch, and never make the app
wait for it or fail because of it: the catalog may be unreachable, and the
user may be offline.

**Ready-made:** the [update check](https://github.com/blackbearreloaded/ps5-native-app-boilerplate/blob/main/docs/UPDATE_CHECK.md) in `ps5-native-app-boilerplate` is
these four steps as two files (`update_check.h` and `update_check.c`) that you
copy into your project. It uses the console's own HTTPS with certificate
verification, needs no elevation, and has been run on a PS5 against this API.

### A store checking what is installed

0. Verify the catalog first ([Verifying the catalog](#verifying-the-catalog)).
1. `GET https://homebrew.page/api/v1/versions.json`: one request, however many
   apps are installed, and the catalog never learns which ones they are.
2. For each installed title ID that is in `apps`, apply the rule.
3. Fetch `apps/<TITLEID>.json` only for the apps the user opens or updates.

Installed titles that aren't in `versions.json` aren't listed in the catalog.

## Verifying the catalog

HTTPS proves a client is talking to `homebrew.page`. The signature proves the
catalog was produced by this repository's build, even if the website or its
host were ever taken over. **A client that installs software should verify;**
one that only displays information (an app checking itself for an update) can
rely on HTTPS.

### `manifest.json` and `manifest.sig`

```json
{
  "commit": "2f516b1c0e4a7d9b3f6a8c5e1d2b4a6f8e0c1d3b",
  "files": {
    "apps/PPSA99002.json": "6b1f…64 hexadecimal characters…",
    "index.json": "c41d…",
    "versions.json": "9a3e…"
  },
  "schema": 3,
  "sequence": 72
}
```

| Field | Meaning |
| --- | --- |
| `files` | Every JSON file of the API except the manifest itself, by path under `/api/v1/`, with the SHA-256 of its exact bytes. Icons aren't in it. |
| `sequence` | The catalog's sequence number. It grows with every change to the catalog and never goes down. |
| `commit` | The catalog repository commit this build came from. |
| `schema` | As everywhere else. |

`manifest.sig` is the **Ed25519 signature of the exact bytes of
`manifest.json`**: 64 raw bytes, no encoding and no wrapper.

### What a client does

1. Fetch `manifest.json` and `manifest.sig`.
2. Verify the signature against the public keys below. It is valid if **either**
   key verifies it. If neither does, treat the catalog as unreachable: use
   nothing from it.
3. Compare `sequence` with the highest one you have ever accepted, which you
   keep on disk. Lower: refuse it, as in step 2. Equal or higher: accept, and
   remember it.
4. For every API file you then use, compute the SHA-256 of the bytes you
   downloaded and require it to equal the entry in `files`. A file that isn't
   listed, or doesn't match, is not used. A mismatch right after a catalog
   update usually means the manifest and the file come from two different
   builds; fetch the manifest again.

An app that is absent from a verified manifest is not in the catalog.

### The public keys

Two Ed25519 keys can sign the catalog: the one the build uses, and a spare
whose private half is kept offline and takes over if the first is ever lost or
exposed. Clients carry both. Neither expires.

| Key ID | Public key (32 bytes, hexadecimal) | File |
| --- | --- | --- |
| `da351006acb6e3c3` | `87391bf1698ecef101bf5e29dc8585ee5947d571e19470de7411c5d3b137b5cf` | [`keys/catalog-signing-1.pub.pem`](../keys/catalog-signing-1.pub.pem) |
| `eef399ea3007720a` | `509bcfab7edfb4e5ed23639488517c6ef2657c13b6b7f2bf699c8989d9b0dd7b` | [`keys/catalog-signing-2.pub.pem`](../keys/catalog-signing-2.pub.pem) |

The key ID is the first 16 hexadecimal characters of the SHA-256 of the 32 key
bytes. The files are the same keys in PEM form, for `openssl`:

```sh
curl -sO https://homebrew.page/api/v1/manifest.json -O https://homebrew.page/api/v1/manifest.sig
openssl pkeyutl -verify -pubin -inkey keys/catalog-signing-1.pub.pem -rawin -in manifest.json -sigfile manifest.sig
```

If a key is ever retired, this page says so, and the next store release drops
it.

## Caching icons

Icons are the largest files in the API, and they rarely change. A client
should download each one once and keep it:

1. Store every icon you download together with the `icon_hash` it came with.
2. When you read `index.json` (or an app's own file), compare each app's
   `icon_hash` with the one you stored.
3. Download the icon again only when they differ, or when you have none. When
   `icon_hash` is `null`, the app has no icon: show your placeholder.

Always download from the address in `icon` or `icon_small`, exactly as given.
It ends in `?v=` and the icon's fingerprint, so the address changes whenever
the picture does, and a cache between you and the site can't answer with the
previous picture. The plain addresses in [Files](#files) keep working, but a
cache may serve an older picture from them for a few hours after an icon
changes; don't build them yourself.

An unchanged icon then costs no request at all. `icon_hash` covers both sizes,
and it is independent of the app's version: a new release with the same image
keeps it, and an image the developer replaces changes it. Treat it as an
opaque string; only equality matters.

A client that keeps no fingerprints can still send `If-None-Match` for each
icon, as for any other file, at the cost of one request per icon.

## Mirror

The whole API is published a second time at

```
https://blackbearreloaded.github.io/ps5-homebrew-catalog/api/v1/
```

for consoles on networks that can't reach `homebrew.page`. It is rebuilt and
signed by the same deploy, a moment after the main site.

- **Same files, same meaning.** `index.json`, `versions.json`, `apps/<TITLEID>.json`,
  the icons, `manifest.json` and `manifest.sig` are all there, under the same paths.
- **Icon addresses name the mirror.** `icon` and `icon_small` point at the mirror,
  so a client that can only reach the mirror can still fetch icons. `page` still
  names the website. Everything else is identical.
- **Its own manifest and signature,** made with the same keys. Because the icon
  addresses differ, the mirror's files have different hashes: verify a mirror
  file against the mirror's manifest, never against the main site's. `sequence`
  is the same number on both.
- **Use it only as a fallback.** Ask `homebrew.page` first; use the mirror when
  that fails. A client must accept exactly this host and path prefix, not any
  `github.io` address.
- **Only the API is mirrored.** There are no app pages there.

GitHub Pages sets its own cache lifetime (about ten minutes) and ignores the
site's header rules, so the [Requests](#requests) notes on caching describe the
main site.

## Requests

- **HTTPS only**, `GET` only. No key, no account, no rate limit to negotiate;
  be considerate anyway.
- **Name your client.** Send a `User-Agent` such as `MyApp/01.000.000`. The
  CDN in front of the site refuses the default agents of some HTTP libraries
  (Python's `urllib`, for one) with `403`.
- **Caching.** Responses carry an `ETag` and
  `Cache-Control: public, max-age=300, must-revalidate`. Keep the `ETag` with
  your copy and send it back as `If-None-Match`; an unchanged file answers
  `304 Not Modified` with no body. A per-app file and `versions.json` keep
  their `ETag` across catalog builds until that app changes. `index.json`
  changes on every build.
- **Freshness.** A merged listing reaches the API within a few minutes, and
  caches may hold a file for five more. Checking more often than every few
  hours gains nothing.
- **Compression.** Send `Accept-Encoding: gzip` if your HTTP client can
  decompress; the files are small enough to work without it.
- **Browsers.** `Access-Control-Allow-Origin: *` is set on everything under
  `/api/`.
- **Failure.** Treat timeouts, non-200 answers and JSON that doesn't parse as
  "no information", and try again later.

## Versioning of the API

- **The path is the contract.** Everything under `/api/v1/` keeps its paths,
  field names, types and meanings.
- **Additions don't break it.** New fields and new files can appear at any
  time. `schema` is raised when they do, so a client can tell whether a field
  it wants exists yet. Clients must ignore fields they don't know.
- **A breaking change gets a new path**, `/api/v2/`: removing or renaming a
  field, changing its type or meaning, or changing the update rule. `/api/v1/`
  keeps being published next to it for at least six months after `v2` is
  announced in this document and in the repository's releases, so shipped apps
  keep working.
- **Don't build on anything else.** The website's pages, the hashed files under
  `/assets/`, and the repository's layout can change without notice.

| `schema` | Date | Change |
| --- | --- | --- |
| 1 | 2026-10-02 | First version: `versions.json`, `index.json`, `apps/<TITLEID>.json`, PNG icons. |
| 2 | 2026-10-02 | Added `icon_hash` to app files and index entries, so clients can cache icons without requests. |
| 3 | 2026-10-02 | Added `manifest.json` and `manifest.sig`: the catalog is signed. |
| 3 | 2026-10-07 | Added `safety` to app files and `sandbox` to index entries: what the release scan found. `schema` stays 3. |
| 3 | 2026-10-07 | `icon` and `icon_small` end in `?v=<icon_hash>`, so an icon's address changes with its picture. No field was added or renamed. |
| 3 | 2026-10-05 | Added `release_notes` and `release_notes_truncated` to app files. `schema` stays 3: a released store accepts only that exact number, so it is raised with the next change that store has been prepared for. Test for the field, not for the number. |

## Where the values come from

| Value | Source | Checked |
| --- | --- | --- |
| The eleven record fields | `apps/<TITLEID>.json`, reviewed and merged by a maintainer | On every pull request, push and in the daily health check |
| `sha256` | The record; it must equal the digest GitHub computes for the file | Same |
| `size`, `released`, `prerelease` | GitHub's API for the release | Read when the release is first built into the site, then again at a rebuild, at most once a day |
| `release_notes` | The release's notes in GitHub's API, reduced to plain text | Same |
| `content_version` | `sce_sys/param.json` in the app's repository at the release tag | Same; see [App versions](versioning.md) |
| `updated` | The record's history in this repository | Every build |
| Icons | `icon_url`, converted to PNG | Every build, cached |
| `manifest.json` | The hashes of the files this build produced; `sequence` is the number of commits in the catalog's history | Every build |
| `manifest.sig` | Signed by the deploy job with a key held as a deployment secret | Every deploy; the deploy fails rather than publish an unsigned or wrongly signed catalog |

No artifact is downloaded to produce any of it.

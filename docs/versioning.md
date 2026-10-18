# App versions

For developers. An app in the catalog has two versions, and consoles rely on
one of them to tell users that an update exists.

| | Release tag | Content version |
| --- | --- | --- |
| Where it lives | The tag of your GitHub release | `contentVersion` in your app's `sce_sys/param.json` |
| Looks like | Anything: `v0.10.0`, `0.9`, `vk-285-117`, `01.000.070` | Always `NN.NNN.NNN`: `01.000.070` |
| In the catalog | The record's `version` (the tag, or the tag without a leading `v`) | `content_version` in the [store API](api.md), read automatically |
| Used for | Display: the website, the store, update notices | Deciding whether an installed copy is outdated |

The content version is the PlayStation standard: it is the version the console
itself reports for an installed title. A store, or your own app, compares the
installed `contentVersion` with the catalog's `content_version`; an update
exists when the catalog's is higher. The release tag can't do that job: tags
have no common format and no defined order.

## The rules

1. **Use the format `NN.NNN.NNN`**: two digits, three digits, three digits,
   for example `01.000.070`. Anything else is treated as unknown.
2. **Raise it in every release.** A release whose `contentVersion` is the same
   as the previous one is invisible to consoles: they have nothing to compare.
   Many templates ship `01.000.000` and never change it.
3. **Never lower it and never reuse one.** Versions are compared as three
   numbers, left to right: `01.000.009` < `01.000.010` < `01.001.000` <
   `02.000.000`.
4. **Keep `param.json` in your repository**, with the value the release
   actually ships, in the commit your release tag points at. If you don't, the
   catalog falls back to the copy inside your release's `.zip` (see below), but
   a committed file is the reliable way.

```json
{
  "titleId": "PPSA01234",
  "contentVersion": "01.000.070",
  "masterVersion": "01.00"
}
```

## The simplest setup

Tag your releases with the content version itself:

| Release tag | Record `version` | `contentVersion` |
| --- | --- | --- |
| `01.000.070` | `01.000.070` | `01.000.070` |

One number everywhere, nothing to keep in sync, and the catalog knows the
content version from the tag alone. You can keep any tag scheme you like
instead; then rules 2 and 4 are what make updates work:

| Release tag | Record `version` | `contentVersion` |
| --- | --- | --- |
| `v0.10.0` | `0.10.0` | `01.000.010` |
| `v0.11.0` | `0.11.0` | `01.000.011` |

## How the catalog reads it

The release is never downloaded: the `sha256` is GitHub's own digest of the
file. When a release is listed, the catalog looks for a `sce_sys/param.json`
whose `titleId` is your app's, first in your repository **at the release tag**:

1. next to the icon, when `icon_url` points at `…/sce_sys/icon0.png` in the
   same repository;
2. otherwise anywhere in the repository, nearest the root first (other titles'
   `param.json` files, such as vendored samples, are skipped);
3. otherwise, inside the release's `.zip`, at `sce_sys/param.json` (nearest the
   top first). Only the ZIP's file list and that one small file are fetched,
   with HTTP range requests, never the whole archive. This also lets a
   submission whose repository holds no `sce_sys/` folder pass the `param.json`
   check; reviewers are told it was read from the ZIP;
4. otherwise, if the record's `version` is already in the `NN.NNN.NNN` format,
   that is used.

If none of these gives a well-formed value, `content_version` is `null` in the
API. The app is still listed and installable; clients just can't tell whether
an installed copy is current.

If your build generates `param.json` and ships it only in the ZIP, it is read
from there. Otherwise, do one of these: commit the generated
file, commit a `sce_sys/param.json` with the right `titleId` and
`contentVersion` and have the build start from it, or tag releases with the
content version.

## What the checks tell you

Neither of these blocks a listing; they are there so you notice.

| Where | Message | Meaning |
| --- | --- | --- |
| Submission check | `contentVersion 01.000.070 (from sce_sys/param.json)` | Read correctly. |
| Submission check | `no contentVersion found for this release …` | Rule 4: nothing to read at the tag. |
| Submission check | `contentVersion … is not higher than the listed release's …` | Rule 2 or 3: consoles won't see this release as an update. |
| Daily update pull request | `` `contentVersion`: `01.000.060` → `01.000.070` `` | The update will reach consoles. |
| Daily update pull request | `` `contentVersion` is still `01.000.000` `` | Listed, but consoles won't see it as an update. |

## Release checklist

1. Raise `contentVersion` in `sce_sys/param.json` and commit it.
2. Build from that commit, so the shipped `param.json` has the same value.
3. Tag that commit and publish the GitHub release with the artifact attached
   and a description of what changed: it is shown as the app's
   [release notes](../README.md#write-release-notes).
4. The catalog's daily update job proposes the new release; nothing else to do
   (see [Updating your app](submitting.md#updating-your-app)).

To have your app tell its own users about a new release, add the
[update check](https://github.com/blackbearreloaded/ps5-native-app-boilerplate/blob/main/docs/UPDATE_CHECK.md): two files that ask the catalog and compare content
versions.

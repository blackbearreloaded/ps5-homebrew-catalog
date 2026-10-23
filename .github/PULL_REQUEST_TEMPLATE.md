<!-- Listing or updating an app? Follow docs/submitting.md. One app per pull request. -->

**Title ID:** <!-- e.g. PPSA01234 -->
**New listing, update or reservation:** <!-- new / update / reservation -->
**What the app does:** <!-- one or two sentences for the reviewer -->
**Category:** <!-- the record's `category`: console-ports, pc-ports, homebrew-games, emulators, streaming, video, music, ai, utilities, tools or showcases -->
**Fork or derivative of an app in the catalog?** <!-- no / yes: which one, and what it does that the original doesn't -->

- [ ] The app is a native PS5 app (its own title with `eboot.bin` and `sce_sys/`), not a payload, PS4 package or backport.
- [ ] I am opening this PR from the account that owns `source_repo` (or I am a public member of the owning organization). If not, I understand a maintainer must approve it by hand.
- [ ] The artifact is a `.zip` of the app folder, the only format accepted at the moment ([artifact formats](https://github.com/darkxex/ps5-homebrew-catalog/blob/main/docs/artifact-formats.md)) whose app uses this title ID.
- [ ] For a release: the artifact is attached to a published GitHub release, and `version` is that release's tag (optionally without a leading `v`).
- [ ] For a release: `sha256` is the digest of the exact asset in `artifact_url`, and I won't replace that asset.
- [ ] For a release: `contentVersion` in my repository's `sce_sys/param.json` is in the `01.000.070` format and higher than my previous release's, so consoles see updates ([App versions](https://github.com/darkxex/ps5-homebrew-catalog/blob/main/docs/versioning.md)).
- [ ] The record's `category` is the shelf people would look in first ([categories](https://github.com/darkxex/ps5-homebrew-catalog/blob/main/docs/metadata.md#categories)).
- [ ] I have the right to distribute this build under the stated license.
- [ ] If it builds on an app in the catalog, it is a distinct app (not only a new name, theme or icon) and its name doesn't include that app's name.
- [ ] I have read the [review policy](https://github.com/darkxex/ps5-homebrew-catalog/blob/main/docs/review-policy.md).

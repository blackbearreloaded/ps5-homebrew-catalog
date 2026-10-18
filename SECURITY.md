# Security

## Reporting a malicious or compromised app

If a listed app contains malware, behaves maliciously, or its release appears to
have been tampered with, report it privately through
[GitHub private vulnerability reporting](https://github.com/darkxex/ps5-homebrew-catalog/security/advisories/new).
Include the title ID, what you observed, and how to reproduce it.

Don't post details publicly while a listing may still be installed from the
catalog. Maintainers withdraw a listing first and investigate afterwards; see the
[review policy](docs/review-policy.md#withdrawals).

## Reporting a problem with the catalog tooling

Vulnerabilities in the checker or workflows, such as a way for a pull request to
bypass the submission check, should be reported the same way.

## Scope

The catalog verifies, through the SHA-256 digest GitHub records for each release
asset, that downloads match the reviewed release byte for byte.
It does not audit app source code, and it can't vouch for an app's behavior on
the console. Vulnerabilities in a listed app itself belong in that app's own
repository.

# Contributing

## Listing or updating an app

Follow **[Submitting an app](docs/submitting.md)**. App pull requests may change
only `apps/<TITLEID>.json` (or `apps/<TITLEID>-<owner>.json` when another app has the title ID), one app at a time, and must come from the account
that owns the app's source repository. A pull request from another account is possible but
waits for a maintainer's manual approval; the bot never merges it.

## Reporting a problem with a listing

Use the [issue templates](https://github.com/darkxex/ps5-homebrew-catalog/issues/new/choose)
for broken downloads, wrong information, withdrawals and ownership transfers.
Report malicious or compromised apps privately; see [SECURITY.md](SECURITY.md).

## Changing the tooling or documentation

Open an issue first to discuss the change. Pull requests that touch anything
outside `apps/` fail the community submission check and are handled by
maintainers.

The checker in `catalog/` uses only the Python standard library (3.10+). Before
proposing a change, run:

```sh
python3 -m unittest discover -s tests
python3 -m catalog check
```

Keep checks deterministic, bounded and free of code execution: the submission
check runs on untrusted pull requests. See [Automation](docs/automation.md).

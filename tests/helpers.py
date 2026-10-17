"""Shared fixtures for the catalog tests."""

import json
from pathlib import Path

VALID = {
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
    "sha256": "a" * 64,
    "icon_url": "https://raw.githubusercontent.com/example/example-app/01.000.000/sce_sys/icon0.png",
}


RESERVATION = {
    "titleid": "PPSA05555",
    "name": "Future Game",
    "kind": "game",
    "category": "homebrew-games",
    "description": "A game that is not released yet.",
    "license": None,
    "author": "Example Dev",
    "version": None,
    "source_repo": None,
    "artifact_url": None,
    "sha256": None,
    "icon_url": None,
}


def reservation(**changes):
    data = dict(RESERVATION)
    data.update(changes)
    return data


def record(**changes):
    data = dict(VALID)
    data.update(changes)
    return data


def write_record(directory: Path, data: dict, filename: str | None = None) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (filename or f"{data.get('titleid', 'PPSA01234')}.json")
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path

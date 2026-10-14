"""Collect check results and print them for terminals and GitHub Actions."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field

LEVELS = ("error", "warning", "notice")


@dataclass
class Report:
    items: list[tuple[str, str, str]] = field(default_factory=list)

    def error(self, file: str, message: str) -> None:
        self.items.append(("error", file, message))

    def warning(self, file: str, message: str) -> None:
        self.items.append(("warning", file, message))

    def notice(self, file: str, message: str) -> None:
        self.items.append(("notice", file, message))

    @property
    def failed(self) -> bool:
        return any(level == "error" for level, _, _ in self.items)

    def count(self, level: str) -> int:
        return sum(1 for item_level, _, _ in self.items if item_level == level)

    def emit(self, title: str, passed_message: str) -> int:
        in_actions = os.environ.get("GITHUB_ACTIONS") == "true"
        for level, file, message in self.items:
            stream = sys.stderr if level == "error" else sys.stdout
            if in_actions:
                print(f"::{level} file={_escape(file, True)}::{_escape(message)}", file=stream)
            else:
                print(f"{level}: {file}: {message}", file=stream)
        verdict = "failed" if self.failed else "passed"
        counts = ", ".join(f"{self.count(level)} {level}(s)" for level in LEVELS)
        print(f"{title} {verdict} ({counts}).")
        if not self.failed:
            print(passed_message)
        summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary:
            with open(summary, "a", encoding="utf-8") as handle:
                handle.write(self.markdown(title, passed_message))
        return 1 if self.failed else 0

    def markdown(self, title: str, passed_message: str) -> str:
        icon = "❌" if self.failed else "✅"
        lines = [f"## {icon} {title}", ""]
        if not self.failed:
            lines += [passed_message, ""]
        if self.items:
            lines += ["| Level | File | Result |", "| --- | --- | --- |"]
            for level in LEVELS:
                for item_level, file, message in self.items:
                    if item_level == level:
                        lines.append(f"| {level} | `{file}` | {_cell(message)} |")
            lines.append("")
        return "\n".join(lines) + "\n"


def _escape(value: str, property_value: bool = False) -> str:
    value = value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    if property_value:
        value = value.replace(":", "%3A").replace(",", "%2C")
    return value


def _cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")

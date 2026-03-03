#!/usr/bin/env python3
"""Static checks for LinuxCNC INI/HAL config files."""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import DefaultDict


VAR_REF_RE = re.compile(r"\[([A-Za-z0-9_]+)\]([A-Za-z0-9_.-]+)")
ARROWS = {"<=", "=>", "<=>"}


@dataclass(frozen=True)
class Location:
    path: Path
    line: int

    def render(self, root: Path) -> str:
        try:
            rel = self.path.relative_to(root)
        except ValueError:
            rel = self.path
        return f"{rel}:{self.line}"


@dataclass
class IniEntry:
    key: str
    value: str
    line: int


@dataclass
class SignalStats:
    sources: list[Location] = field(default_factory=list)
    sinks: list[Location] = field(default_factory=list)
    unknown: list[Location] = field(default_factory=list)


def strip_comment(line: str) -> str:
    if "#" in line:
        line = line.split("#", 1)[0]
    return line.strip()


def parse_ini(path: Path) -> dict[str, list[IniEntry]]:
    sections: dict[str, list[IniEntry]] = {}
    current_section: str | None = None

    for line_no, raw_line in enumerate(path.read_text().splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith(("#", ";")):
            continue

        if line.startswith("[") and line.endswith("]"):
            current_section = line[1:-1].strip()
            sections.setdefault(current_section, [])
            continue

        if current_section is None or "=" not in line:
            continue

        key, value = line.split("=", 1)
        sections[current_section].append(
            IniEntry(key=key.strip(), value=value.strip(), line=line_no)
        )

    return sections


def ini_values(sections: dict[str, list[IniEntry]], section: str, key: str) -> list[str]:
    return [entry.value for entry in sections.get(section, []) if entry.key == key]


def ini_has_key(sections: dict[str, list[IniEntry]], section: str, key: str) -> bool:
    return any(entry.key == key for entry in sections.get(section, []))


def parse_hal(
    path: Path,
    signals: DefaultDict[str, SignalStats],
    pin_mentions: DefaultDict[str, list[Location]],
    alias_defs: dict[str, Location],
    variable_refs: list[tuple[str, str, Location]],
) -> None:
    for line_no, raw_line in enumerate(path.read_text().splitlines(), start=1):
        line = strip_comment(raw_line)
        if not line:
            continue

        location = Location(path=path, line=line_no)

        for section, key in VAR_REF_RE.findall(line):
            variable_refs.append((section, key, location))

        parts = line.split()
        if not parts:
            continue

        if len(parts) >= 4 and parts[0] == "alias" and parts[1] == "pin":
            alias_defs[parts[3]] = location
            continue

        if len(parts) >= 3 and parts[0] == "sets":
            signals[parts[1]].sources.append(location)
            continue

        if len(parts) < 2 or parts[0] != "net":
            continue

        signal_name = parts[1]
        current_arrow: str | None = None

        for token in parts[2:]:
            if token in ARROWS:
                current_arrow = token
                continue

            pin_mentions[token].append(location)
            stats = signals[signal_name]

            if current_arrow == "<=":
                stats.sources.append(location)
            elif current_arrow == "=>":
                stats.sinks.append(location)
            elif current_arrow == "<=>":
                stats.sources.append(location)
                stats.sinks.append(location)
            else:
                stats.unknown.append(location)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Lint LinuxCNC INI/HAL files for common static wiring errors."
    )
    parser.add_argument(
        "ini",
        nargs="?",
        default="mymill.ini",
        help="Path to the INI file to lint (default: mymill.ini)",
    )
    args = parser.parse_args()

    ini_path = Path(args.ini).resolve()
    root = ini_path.parent

    if not ini_path.exists():
        print(f"error: missing INI file: {ini_path}", file=sys.stderr)
        return 2

    sections = parse_ini(ini_path)
    hal_paths: list[Path] = []
    errors: list[str] = []
    warnings: list[str] = []

    for key in ("HALFILE", "POSTGUI_HALFILE"):
        for value in ini_values(sections, "HAL", key):
            hal_path = (root / value).resolve()
            if hal_path.exists():
                hal_paths.append(hal_path)
            else:
                errors.append(f"missing {key}: {value}")

    if not hal_paths:
        warnings.append("no HAL files were discovered from the [HAL] section")

    signals: DefaultDict[str, SignalStats] = defaultdict(SignalStats)
    pin_mentions: DefaultDict[str, list[Location]] = defaultdict(list)
    alias_defs: dict[str, Location] = {}
    variable_refs: list[tuple[str, str, Location]] = []

    for hal_path in hal_paths:
        parse_hal(hal_path, signals, pin_mentions, alias_defs, variable_refs)

    for section, key, location in variable_refs:
        if section not in sections:
            errors.append(
                f"{location.render(root)} references missing INI section [{section}]"
            )
            continue
        if not ini_has_key(sections, section, key):
            errors.append(
                f"{location.render(root)} references missing INI key [{section}]{key}"
            )

    for signal_name, stats in sorted(signals.items()):
        has_source = bool(stats.sources)
        has_sink = bool(stats.sinks)
        has_unknown = bool(stats.unknown)

        if has_sink and not has_source and not has_unknown:
            first = stats.sinks[0].render(root)
            if signal_name in alias_defs:
                errors.append(
                    f"{first} signal '{signal_name}' has sinks but no source and "
                    "shares a name with an alias pin"
                )
            else:
                warnings.append(
                    f"{first} signal '{signal_name}' has sinks but no source"
                )
        if has_source and not has_sink and not has_unknown:
            first = stats.sources[0].render(root)
            warnings.append(f"{first} signal '{signal_name}' has a source but no sink")

    for pin_name, locations in sorted(pin_mentions.items()):
        if len(locations) > 1:
            seen = ", ".join(location.render(root) for location in locations[:3])
            suffix = "" if len(locations) <= 3 else ", ..."
            warnings.append(
                f"pin '{pin_name}' is linked multiple times ({seen}{suffix})"
            )

    for alias_name, location in sorted(alias_defs.items()):
        if alias_name not in pin_mentions:
            warnings.append(
                f"{location.render(root)} alias pin '{alias_name}' is defined but unused"
            )

    if errors:
        for message in errors:
            print(f"ERROR: {message}", file=sys.stderr)
        for message in warnings:
            print(f"WARNING: {message}", file=sys.stderr)
        return 1

    for message in warnings:
        print(f"WARNING: {message}", file=sys.stderr)

    loaded = ", ".join(str(path.relative_to(root)) for path in hal_paths) or "<none>"
    print(f"OK: linted {ini_path.name} ({loaded})")
    if warnings:
        print(f"OK: completed with {len(warnings)} warning(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

from __future__ import annotations

import argparse
from pathlib import Path
import re
import tokenize
from typing import Iterable


FROM_IMPORT_RE = re.compile(r"^(?P<indent> *)from\s+(?P<module>\S+)\s+import\s+(?P<names>.+)$")
ASSIGNMENT_RE  = re.compile(r"^(?P<indent> *)(?P<target>(?:self\.)?[A-Za-z_]\w*)\s*=\s*(?P<value>.+)$")


def _bracket_depths(source: str) -> dict[int, int]:
    depths: dict[int, int] = {}
    depth                   = 0
    try:
        tokens = tokenize.generate_tokens(iter(source.splitlines(keepends=True)).__next__)
        for token in tokens:
            line = token.start[0]
            depths.setdefault(line, depth)
            if token.type == tokenize.OP:
                if token.string in "([{":
                    depth += 1
                elif token.string in ")]}":
                    depth = max(0, depth - 1)
    except (IndentationError, tokenize.TokenError):
        return {}
    return depths


def _align_groups(lines: list[str], pattern: re.Pattern[str], renderer) -> list[str]:
    output = list(lines)
    index  = 0
    while index < len(lines):
        match = pattern.match(lines[index])
        if not match:
            index += 1
            continue
        group  = [(index, match)]
        cursor = index + 1
        while cursor < len(lines):
            candidate = pattern.match(lines[cursor])
            if not candidate or candidate.group("indent") != match.group("indent"):
                break
            group.append((cursor, candidate))
            cursor += 1
        if len(group) >= 2:
            width = max(renderer.width(item) for _, item in group)
            for line_number, item in group:
                output[line_number] = renderer.render(item, width)
        index = cursor
    return output


class _ImportRenderer:
    @staticmethod
    def width(match: re.Match[str]) -> int:
        return len(match.group("module"))

    @staticmethod
    def render(match: re.Match[str], width: int) -> str:
        return f'{match.group("indent")}from {match.group("module"):<{width}} import {match.group("names")}'


class _AssignmentRenderer:
    @staticmethod
    def width(match: re.Match[str]) -> int:
        return len(match.group("target"))

    @staticmethod
    def render(match: re.Match[str], width: int) -> str:
        return f'{match.group("indent")}{match.group("target"):<{width}} = {match.group("value")}'


def format_source(source: str) -> str:
    had_final_newline = source.endswith("\n")
    lines             = [line.expandtabs(4).rstrip() for line in source.splitlines()]
    lines             = _align_groups(lines, FROM_IMPORT_RE, _ImportRenderer)
    depths            = _bracket_depths("\n".join(lines) + "\n")
    candidates        = []
    for number, line in enumerate(lines, start=1):
        match = ASSIGNMENT_RE.match(line)
        if match and depths.get(number, 0) == 0 and not match.group("value").startswith("="):
            candidates.append(line)
        else:
            candidates.append("")
    aligned = _align_groups(candidates, ASSIGNMENT_RE, _AssignmentRenderer)
    for index, line in enumerate(aligned):
        if line:
            lines[index] = line
    result = "\n".join(lines)
    return result + "\n" if had_final_newline or lines else result


def python_files(paths: Iterable[Path]) -> list[Path]:
    files: set[Path] = set()
    for path in paths:
        if path.is_file() and path.suffix == ".py":
            files.add(path)
        elif path.is_dir():
            files.update(path.rglob("*.py"))
    return sorted(files)


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply compact column-aligned Python formatting.")
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    changed   = []
    for path in python_files(arguments.paths):
        original  = path.read_text(encoding="utf-8")
        formatted = format_source(original)
        if formatted != original:
            changed.append(path)
            if not arguments.check:
                path.write_text(formatted, encoding="utf-8", newline="\n")
    for path in changed:
        print(path)
    return 1 if arguments.check and changed else 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Gates: the checkbox lines of a task.md.

Checkboxes inside HTML comments, fenced code blocks and blockquotes are
examples or instructions, not gates.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_BOX_RE = re.compile(r"^\s*[-*] \[( |x|X)\][ \t]?(.*)$")
_CHECKED_RE = re.compile(r"^\s*[-*] \[[xX]\]", re.MULTILINE)
_UNCHECKED_LINE_RE = re.compile(r"^\s*[-*] \[ \][ \t]?(.*)$", re.MULTILINE)
_CHECKED_LINE_RE = re.compile(r"^\s*[-*] \[[xX]\][ \t]?(.*)$", re.MULTILINE)


@dataclass(frozen=True)
class Gate:
    line: int        # 1-based
    checked: bool
    text: str
    section: str     # "3. Work Plan › Step 1: ..."


def parse(text: str) -> list[Gate]:
    gates: list[Gate] = []
    in_comment = in_fence = False
    section = step = ""
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if in_comment:
            if "-->" in line:
                in_comment = False
            continue
        if stripped.startswith(("```", "~~~")):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if "<!--" in line:
            if "-->" not in line.split("<!--", 1)[1]:
                in_comment = True
            continue
        if stripped.startswith(">"):
            continue
        if line.startswith("## "):
            section, step = line[3:].strip(), ""
            continue
        if line.startswith("### "):
            step = line[4:].strip()
            continue
        match = _BOX_RE.match(line)
        if match:
            label = f"{section} › {step}" if step else section
            gates.append(Gate(number, match.group(1) != " ", match.group(2).strip(), label))
    return gates


def first_open(gates: list[Gate]) -> Gate | None:
    return next((g for g in gates if not g.checked), None)


def progress(gates: list[Gate]) -> tuple[int, int]:
    return sum(g.checked for g in gates), len(gates)


def checked_count(fragment: str) -> int:
    """Checked boxes in an arbitrary fragment (an Edit's old or new string)."""
    return len(_CHECKED_RE.findall(fragment))


def bare_checks(old: str, new: str) -> list[str]:
    """Gates checked in `new` with nothing written after the original text."""
    unchecked_before = {m.group(1).strip() for m in _UNCHECKED_LINE_RE.finditer(old)}
    checked_before = {m.group(1).strip() for m in _CHECKED_LINE_RE.finditer(old)}
    return [
        text for m in _CHECKED_LINE_RE.finditer(new)
        if (text := m.group(1).strip()) in unchecked_before and text not in checked_before
    ]

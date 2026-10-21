"""Building the session-start context from MIND_MAP.md."""

from __future__ import annotations

from .project import MINDMAP_DIR, Project

# Claude Code caps each hook's additionalContext at 10,000 characters and
# replaces anything longer with a file path plus a short preview. Stay under it
# with room for the header, reminders and warnings.
CONTEXT_LIMIT = 10_000
MIND_MAP_BUDGET = 8_500

STUB_MARKER = "<!-- cplugin:stub"


def is_stub(text: str) -> bool:
    return STUB_MARKER in text


def _clip(text: str, budget: int) -> tuple[str, bool]:
    """Cut `text` at the last line break that fits `budget` characters."""
    if len(text) <= budget:
        return text, False
    cut = text.rfind("\n", 0, budget)
    return text[: cut if cut > 0 else budget], True


def session_context(project: Project, warnings: list[str] | None = None,
                    task_summary: str | None = None) -> str:
    parts = ["# cplugin: project memory"]
    if task_summary:
        parts.append(task_summary)
    path = project.mind_map
    if not path.is_file():
        parts.append(
            "MIND_MAP.md is missing. Tell the user and offer to run /cplugin:mindmap to build it."
        )
    else:
        text = path.read_text(encoding="utf-8", errors="replace").strip()
        if is_stub(text):
            parts.append(
                "MIND_MAP.md is still the empty template. Offer the user to run "
                "/cplugin:mindmap to build it from the codebase and their explanations."
            )
        else:
            body, clipped = _clip(text, MIND_MAP_BUDGET)
            parts.append(f"Contents of MIND_MAP.md:\n\n{body}")
            if clipped:
                parts.append(
                    f"[cplugin] MIND_MAP.md is {len(text):,} characters; only the first "
                    f"{len(body):,} were loaded. Read the rest with the Read tool before "
                    "relying on the map, and tell the user the map needs compressing "
                    f"(budget: {MIND_MAP_BUDGET:,} characters; move details into {MINDMAP_DIR}/)."
                )
    parts.append(
        "How to use the memory: MIND_MAP.md holds the big ideas only. Each module node "
        f"links its detail file ({MINDMAP_DIR}/<module>.md). Before working on a module, "
        "read its detail file. After changing behaviour, update the owning section of that "
        "file in place; touch MIND_MAP.md only when the big ideas change."
    )
    if warnings:
        parts.append("[cplugin] warnings:\n" + "\n".join(f"- {w}" for w in warnings))
    context = "\n\n".join(parts)
    if len(context) > CONTEXT_LIMIT:
        context, _ = _clip(context, CONTEXT_LIMIT)
    return context

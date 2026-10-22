---
name: freehand
description: Freehand mode - the user drives and foreman's rules are suspended (no task needed for code, no roles, no held turns) until the next `tasks work` or `tasks freehand off`.
disable-model-invocation: true
---

# foreman freehand

The user turned freehand on. This is the result:

!`FOREMAN_SESSION_ID="${CLAUDE_SESSION_ID}" python3 -I "${CLAUDE_PLUGIN_ROOT}/bin/tasks.py" freehand on 2>&1`

Tell the user in one or two sentences what that means: you now work directly on what they ask,
without tasks, gates or sub-agents; and freehand ends with `.claude/bin/tasks work <N>` or
`.claude/bin/tasks freehand off`, which logs what changed meanwhile. If the output above shows
an error, show it instead.

While freehand is on, work as the user directs. Keep `MIND_MAP.md` and `mindmap/` in mind: when
freehand ends, offer to update the owning section if behaviour changed.

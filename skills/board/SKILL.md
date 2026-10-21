---
name: board
description: Show the cplugin agent board once, in the chat - the active task, its gate, and what the main agent, the worker and the tester are doing.
disable-model-invocation: true
---

# cplugin board

Run this and show its output to the user exactly as printed, inside a code block:

```bash
python3 -I "${CLAUDE_PLUGIN_ROOT}/bin/board.py" --no-color --session "${CLAUDE_SESSION_ID}"
```

If it prints an error, show the error instead.

Then add one line: for a board that updates live, run `.claude/bin/board --watch` in a second
terminal, from the project's directory.

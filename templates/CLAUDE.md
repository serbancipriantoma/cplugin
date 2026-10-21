<!-- cplugin:begin — managed by /cplugin:init; edits inside this block are overwritten -->
## cplugin workflow

This project uses the cplugin workflow. When the user says "start", use the
`cplugin:start` skill: it shows what this session can use, then asks what to work on.

- **Project memory.** `MIND_MAP.md` holds the big ideas and is loaded at session
  start. Each module has a detail file, `mindmap/<module>.md`, linked from its
  node. Read the detail file before working on a module. After changing
  behaviour, update the owning section of that file in place; change
  `MIND_MAP.md` only when the big ideas change.
- **Every code change goes through a task.** Create it with the user's request
  verbatim on stdin, then activate it:

  ```bash
  .claude/bin/tasks new <type> <name> --module <module> --request - <<'EOF'
  <the user's request, verbatim>
  EOF
  .claude/bin/tasks work <N>
  ```

  Types: feature, bugfix, refactor, explore, test, docs. Questions, reading,
  docs and git need no task.
- **Work the gates in task.md top to bottom.** One gate at a time: do its work,
  check the box, append the outcome on the same line. Edit open gates when the
  plan changes. `tasks status` shows the next gate; `tasks done` closes the task.
- **The main agent coordinates; sub-agents write.** The main session never
  writes code or tests. For each Work Plan step it starts `cplugin:tester` to
  write the tests from the criteria, runs them to confirm they fail for the
  right reason (Red), starts `cplugin:worker` to implement until they pass
  (Green), and records each result on its gate. The `cplugin:workflow` skill
  has the details. Steps that cannot be tested automatically say
  `Verify: manual — <check>`.
- **Hooks enforce this.** Code edits are blocked without an active task; each
  role may write only what it owns; ending a turn with open gates is blocked
  unless sub-agents are still running. When you need the user (a decision, an
  answer, a manual check), run `.claude/bin/tasks pause "<what you need>"` and ask.
- **Build or refresh the map** with `/cplugin:mindmap`. Configuration lives in
  `.cplugin/config.toml`.
<!-- cplugin:end -->

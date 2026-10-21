---
name: workflow
description: How the main agent of a cplugin project works a task's Work Plan - delegating each step to the cplugin:tester and cplugin:worker sub-agents, tests first, and recording the results gate by gate. Use when a cplugin task is active and its Work Plan step needs code or tests.
---

# Working a cplugin step

In a cplugin project the main agent (you, MAIN) **coordinates and never writes code or
tests**. Hooks block it. For each Work Plan step you brief two sub-agents and record what they
did:

| Role | Agent tool call | Writes |
|---|---|---|
| tester | `subagent_type: "cplugin:tester"` | tests only |
| worker | `subagent_type: "cplugin:worker"` | production code only |

Before the first step, run `.claude/bin/tasks config show` to see each role's model and
paths. Pass that model on every Agent call (`model: "<roles.<role>.model>"`): the hook refuses
a cplugin agent started with another model. Never use `isolation` for them: in a separate
worktree they cannot see the active task. Run at most `roles.worker.max_parallel` workers at
a time.

## Briefing a sub-agent

Sub-agents do not see your conversation. Each prompt must stand on its own:

- the task number and the step's title;
- the step's **Criteria** and **Interface**, copied from task.md;
- where the files go: the test paths for the tester; the test files to satisfy for the worker;
- the test command (`tests.command` in the config, or what the project uses);
- for the worker, the relevant existing files; **for the tester, nothing about how the code
  will be written**: it works from the criteria alone.

## One step, tests first (`workflow.tests_first = true`, the default)

1. **Tests.** Start the tester. When it reports, check the `Tests (tester)` gate with the
   files and the behaviours covered.
2. **Red.** Run the test command yourself. The new tests must fail because the feature is
   missing. Check `Red` with the command and the failing count.
   - They fail for another reason (syntax, import, fixture): send the tester back with the
     output. A new Agent call is fine; include what went wrong.
   - They already pass: they test nothing new. Send the tester back.
3. **Implementation.** Start the worker with the criteria, the interface and the test
   files. When it reports, check `Implementation (worker)` with the files it changed.
4. **Green.** Run the tests yourself. Check `Green` with the command and the passing count.
   - If the worker says a test is wrong, decide who is right against the criteria. Write the
     decision and the reason on the gate, then send the fix to the tester (wrong test) or the
     worker (wrong code).
5. **Checkpoint.** What did you not expect? Does the rest of the plan still hold? Edit the
   open gates if not.

With `workflow.tests_first = false` the tester and the worker start together (two Agent
calls in one message) and there is no Red gate.

## Steps verified by hand

A step that says `Verify: manual — <check>` has no tester. Start the worker, then do the
check yourself if you can (run the app, take a screenshot). If only the user can, run
`.claude/bin/tasks pause "<the check to do>"` and ask them, then record their answer on the
`Manual check` gate.

## While sub-agents run

Sub-agents run in the background. You may end your turn while they work: the Stop hook
allows it as long as one is running, and their report arrives as a notification. Do not
check their gates before their report is in.

## If the hooks object

- **A role violation** (a sub-agent changed a file it does not own, through Bash): it is
  recorded in the task's Violations section. Look at the change; keep it or have the owner
  redo it, and say which on the current gate.
- **"matches neither roles.worker.paths nor roles.tester.paths"**: the file is code no role
  owns. If it should be writable, add it to the right role's `paths` in
  `.cplugin/config.toml` and tell the user you did.

# cplugin: specification

> Draft v0.1, 2026-10-21. `cplugin` is the working name; the final name also changes the commands (`/cplugin:...`) and the state folder (`.cplugin/`).
> It starts from the playbook plugin 1.4.7. Section 12 lists what we keep and what we change.

## 1. Purpose

A Claude Code plugin that:

1. keeps the **project memory** on two levels: the big ideas in `MIND_MAP.md`, and the details, per module, in small files;
2. makes every code change go through a **task** (`task.md`), worked through gates that are checked one at a time;
3. splits the work between agents with **strict roles**: MAIN coordinates, the worker writes code, the tester writes tests, and judges review;
4. has **judges from other providers** (Codex, Antigravity) check what Claude wrote;
5. shows live, on an **ASCII board**, which agent is working and on what;
6. enforces the rules through **hooks** that block deviations instead of only warning about them.

## 2. Project memory

### 2.1 Two levels

| File | Holds | When it is read |
|---|---|---|
| `MIND_MAP.md` | The big ideas: one numbered node per module, 3–6 lines each, linking its detail file | Automatically, at the start of every session (the SessionStart hook) |
| `mindmap/<module>.md` | What each part of the module does: rules, data, edge cases, where the code and tests are, decisions taken | On demand, when a task touches the module. It is the first Design gate |

`MIND_MAP.md` must stay under **8,500 characters**: it goes into context at every start, and Claude Code cuts the text a hook injects at 10,000 characters. If the map is longer, the hook loads only the beginning and asks Claude to read the rest and to tell the user the map needs compressing. Anything more detailed moves into `mindmap/`.

### 2.2 Example

`MIND_MAP.md`:

```markdown
# MIND_MAP — Portfolio

## [1] Overview
Presentation site for a designer: shows their work, says who they are and how to reach them. Modules: [2] Projects, [3] About, [4] Contact.

## [2] Projects → mindmap/projects.md
- Shows the work as a grid of project cards, filterable by category
- Each project has a case-study page: problem, process, result, images
- The home page features the 3 latest projects, each linking to Contact [4]
```

`mindmap/projects.md`:

```markdown
# Projects — details

Summary in MIND_MAP: [2]

## Project grid
- What it does: ...
- Rules: ...
- Code: src/projects/grid.tsx
- Tests: tests/projects/grid.test.ts
- Decisions: (task 012) filtering happens in the page, without a reload

## Project page
...

## Featured projects
...
```

### 2.3 Rules

- Every `MIND_MAP.md` node that has details points to their file (`→ mindmap/<module>.md`).
- A detail file has one `##` section per part of the module. Past ~400 lines it is split into `mindmap/<module>/<section>.md`.
- At the end of every task, **the detail file is updated in place**, in the section that owns the changed part. `MIND_MAP.md` changes only when the big ideas change. Tasks never add one node each (a lesson taken from playbook).
- `/cplugin:mindmap` builds the first version from the existing code. On a new project, the user and Claude fill it in together from conversation.

## 3. The task

### 3.1 Where it lives and how it is created

- `.cplugin/tasks/<NNN>-<type>-<name>/task.md`, plus a `judges/` folder for the judges' reports.
- It is created **only** with `tasks new <type> <name> --module <module> --request -` (the user's request, verbatim, on stdin). The hook blocks creating it by hand.
- Types: `feature`, `bugfix`, `refactor`, `explore`, `test`, `docs`.
- `tasks work <N>` activates the task; `tasks done` closes it and refuses while gates are open. `tasks stop` deactivates it without closing it. `tasks list` and `tasks status` show where things stand.
- `tasks pause "<reason>"` lets MAIN end its turn with open gates when it needs the user.
- The state lives on disk, not in the conversation. That is why a task survives context compaction and can be resumed in another session.

### 3.2 The stages

| # | Stage | Who | What happens |
|---|---|---|---|
| 1 | **Design** | MAIN | Reads the module's details. States in its own words what was asked, what "done" looks like (verifiable criteria), and what is in and out of scope |
| 2 | **Plan Review** | judges, then MAIN | Judges review the plan without seeing the conversation and without being able to change anything. MAIN accepts, parks or rejects each finding, with a reason |
| 3 | **Work Plan** | MAIN, tester, worker | For each step: tests → Red → implementation → Green (section 4.3) |
| 4 | **Implementation Review** | judges, then MAIN | Judges review the code (the task's diff). MAIN triages the findings as in stage 2 |
| 5 | **Final Review** | MAIN | Tests pass, no debug leftovers remain, and `mindmap/<module>.md` (plus `MIND_MAP.md` when needed) is updated |

### 3.3 The `task.md` template

```markdown
# 007 — feature — project-filter

## Status
active

## Request
(the user's text, copied verbatim by `tasks new`)

## Context
- MIND_MAP [2] Projects → `mindmap/projects.md`

## 1. Design
- [ ] Read the affected sections of the detail files listed in Context: ...
- [ ] The request in my own words: ...
- [ ] Done means (verifiable criteria): ...
- [ ] In scope: ...
- [ ] Out of scope: ...
- [ ] Wrote the Work Plan: one group per step, each with criteria, interface and how it is verified

## 2. Plan Review
- [ ] Run `.claude/bin/tasks plan-review 7` and wait for it to finish
- [ ] Triage: every finding → accepted / parked / rejected, with the reason

## 3. Work Plan
### Step 1: <what gets built>
Criteria: ...
Interface: ...
Verify: tests            (or: manual — <the concrete check>)
- [ ] Tests (tester): ...
- [ ] Red: the tests fail for the right reason (command + failing count)
- [ ] Implementation (worker): ...
- [ ] Green: command + passing count
- [ ] Checkpoint: what did I not expect? Is the plan still right?

## 4. Implementation Review
- [ ] Run `.claude/bin/tasks impl-review 7` and wait for it to finish
- [ ] Triage: every finding → accepted / parked / rejected, with the reason

## 5. Final Review
- [ ] All tests pass (command + count)
- [ ] No debug leftovers
- [ ] Updated the owning sections of the detail files in place; MIND_MAP.md only if the big ideas changed

## Parked
(what came up and is out of scope, with enough context for a future task)
```

The checking rule: a checked gate gets a short outcome on the same line, and the original text is never replaced. The plan may change along the way, but only through unchecked gates.

## 4. The agents

### 4.1 Roles

| Role | What it is | Model (default) | Writes to | May not |
|---|---|---|---|---|
| **MAIN** | The main session, the one the user talks to | whatever the user runs | the active `task.md`, `MIND_MAP.md`, `mindmap/**` | write code or tests: it delegates |
| **worker** | Claude sub-agent (`agents/worker.md`) | `opus` | code files under `roles.worker.paths` | write tests, check gates, start other agents, run `tasks` |
| **tester** | Claude sub-agent (`agents/tester.md`) | `sonnet` | test files under `roles.tester.paths` | write code, check gates, start other agents, run `tasks` |
| **judge** | External CLI: `codex`, `agy` | the CLI's default model | nothing: runs in a read-only sandbox | change anything |

- Sub-agents **do not see the conversation**: they get only what MAIN puts in their prompt (the step, the criteria, the relevant files), plus `CLAUDE.md`.
- The worker and the tester do not have the `Agent` tool (`disallowedTools` in their frontmatter), so they cannot start other agents.
- Only MAIN checks gates. The worker and the tester return a report, and MAIN summarizes it in `task.md`.
- Files that are not code (`.md`, `.json`, `.yaml`, images) are not restricted by role. "Code" is defined as in playbook: by extension, plus `bin/`, `scripts/` and files that start with a shebang. The list is configurable.

### 4.2 How the roles are enforced

The PreToolUse hook receives `agent_type` when the call comes from a sub-agent; when it is missing, the call is MAIN's. For every Edit/Write/NotebookEdit it:

1. finds the role from `agent_type` (`cplugin:worker`, `cplugin:tester`, or missing = MAIN);
2. compares the file's path with the paths the role may write in `config.toml`;
3. if the path is not allowed, stops the call with `permissionDecision: "deny"` and a message saying which role owns the file.

Bash cannot be checked by path before it runs (`echo > x.py` gets through). So after every Bash call, PostToolUse compares `git status` with the previous snapshot. If the role changed files it does not own, the agent is told at once and the violation is recorded in the "Violations" section of `task.md`. This requires the project to be a git repository.

### 4.3 One Work Plan step

**Tests before code** (the default, decided 2026-10-21):

```
MAIN: Step 3. Criteria: "a knight hits an archer: 6–9 damage, reduced by defense"
      Interface: damage(attacker, defender, rng) -> int
  └─► tester  gets ONLY the criteria + the interface and writes the tests
MAIN: runs the tests → they must FAIL (Red)
  ├─ fail for the right reason (the feature is missing) → go on
  ├─ fail for another reason (syntax error, wrong import) → back to the tester
  └─ already pass → they test nothing new → back to the tester
  └─► worker  gets the criteria + the interface + the tests' path; implements until they pass
MAIN: runs the tests → Green
  └─ if the worker says a test is wrong: MAIN decides who is right
     and records why in task.md (wrong test → tester; wrong code → worker)
MAIN: Checkpoint
```

- The tester works **blind** by construction, because the code does not exist yet. The tests check what was asked, not what was written.
- **Red** proves the tests really test something new. Running tester and worker in parallel could not prove that.
- The worker cannot change tests and the tester cannot change code, so neither can "fix" a failure by weakening the other's side.
- MAIN fixes the interface during Design, not the tester. Otherwise the tester would decide alone what the API looks like.
- The risk of code written "for the tests" (exactly what passes them, not what was asked) is caught by Implementation Review, where judges compare the code with the request.
- **Steps that cannot be tested automatically** (graphics, animation, game feel) say `Verify: manual — <the concrete check>`. Instead of the Tests/Red/Green gates they have one "Manual check" gate, with its result.
- With `workflow.tests_first = false`, the tester and the worker start in parallel, as in the original design, and the Red gate goes away.

### 4.4 Configuration: one file

`.cplugin/config.toml` is committed and can be edited by hand. TOML was chosen because it allows comments and Python reads it without dependencies (`tomllib`).

```toml
[workflow]
tests_first = true                  # false = tester and worker in parallel, no Red gate

[files]
extra_code_extensions = []          # added to the built-in list of code extensions
code_dirs = ["bin", "scripts"]      # everything in these directories counts as code

[roles.worker]
model = "opus"                      # opus | sonnet | haiku | fable | full model ID
paths = ["src/**", "app/**"]        # where it may write code
max_parallel = 1                    # how many workers may run at once

[roles.tester]
model = "sonnet"
paths = ["tests/**", "**/test_*.py", "**/*.test.*", "**/*.spec.*"]

[roles.main]
paths = ["MIND_MAP.md", "mindmap/**"]   # the active task.md is always allowed

[judges]
mode = "panel"          # single = first available seat; panel = every seat, in parallel
timeout_min = 15
fallback = "claude"     # when no external CLI works: read-only Claude sub-agent; "none" = fail

[[judges.seat]]
provider = "codex"
model = ""              # empty = the CLI's default model

[[judges.seat]]
provider = "agy"
model = ""

[tests]
command = "npm test"

[review]
debug_patterns = ["print(", "console.log(", "debugger", "breakpoint()"]
```

- MAIN reads each role's model from the config and passes it when it starts the sub-agent. Changing a model never means editing the plugin.
- Role prompts live in the plugin (`agents/*.md`). For project-specific rules, add `.cplugin/roles/<role>.md`; MAIN includes it in the sub-agent's prompt.
- `tasks config check` validates the file: tester and worker paths do not overlap, the judges' CLIs exist, the test command exists.

## 5. Judges

- `tasks plan-review <N>` or `tasks impl-review <N>`, run by MAIN, starts them.
- Each judge gets `task.md` (without the triage), `MIND_MAP.md`, the module's detail file and read access to the repository. For impl-review it also gets the task's diff. It never gets the conversation.
- They run **read-only**: Codex in its own read-only sandbox, any other CLI under `sandbox-exec` (macOS) with a profile that forbids writing to the project. On top of that, the CLI runs a tamper check: it compares `git status` and the hash of `task.md` before and after. If a judge changed anything, its report is marked TAMPER and not used, and the command exits with an error (an idea taken from playbook).
- Each judge's report goes to `judges/<stage>-<provider>.md`, and the summary into `task.md`. The CLI writes them, not the judge.
- The Codex and Antigravity adapters start from playbook's (`provider/adapters/codex.py`, `antigravity.py`). The development machine has `codex` 0.156.1 and `agy` 1.2.9.

## 6. Hooks

| Event | What it does |
|---|---|
| **SessionStart** (`startup`, `resume`, `clear`, `compact`) | Registers the session (the ID from the payload, the Claude process running it, and `CPLUGIN_SESSION_ID` through `CLAUDE_ENV_FILE`). Writes `.claude/bin/` (`tasks`, `board`, `sandbox`). Removes dead sessions. After `/clear`, if the ID changed, takes over the active task of the previous session of the same process. **Loads `MIND_MAP.md` and the active task's state** (the current gate) into context |
| **PreToolUse** (`Edit\|Write\|NotebookEdit\|Bash\|Agent`) | Blocks code without an active task. Enforces the roles (4.2). Blocks creating tasks by hand. Blocks checking 3+ gates at once and warns at 2. Blocks `tasks …` run from sub-agents. Records the action on the board |
| **PostToolUse** (all tools) | For MAIN only: shows the current gate (`file:line`) and a check question that depends on what it just did ("Is this the simplest change that works?", "Did it pass for the right reason?"). For sub-agents it only runs the Bash check (4.2) and updates the board |
| **SubagentStart** | Marks the agent active on the board. Adds the role's rules and the current step to its context |
| **SubagentStop** | Marks the agent finished on the board |
| **Stop** | Does not let MAIN end its turn while gates are open. Exceptions: a conversational turn (no writes and fewer than 5 tool calls since the last Stop), MAIN ran `tasks pause "<reason>"` because it needs the user (a decision, an answer, a manual check), freehand mode, or `stop_hook_active` (so it never loops) |
| **SessionEnd** | Records that the session closed but **does not delete its state**. `claude --continue` keeps the same session ID (verified), so the active task must survive the restart. Sessions are removed only when their process is gone and they have been idle for 7 days |

Principles, learned from playbook's problems:

- a hook must never take the session down: on an internal error it blocks nothing, with one exception, the "no active task" rule, which also blocks when the hook cannot tell for sure;
- hooks are written in Python (stdlib, ≥3.11) with a single entry point (`hooks/run.py <event>`), not in bash that calls Python five times per call;
- session cleanup never follows symbolic links.

## 7. The ASCII board

```
┌ TASK 007 · project-filter ─ gate 9/18 ────────────────────┐
│ Step 2: category filter                                   │
├─────────┬───────────┬─────────────────────────────────────┤
│ MAIN    │ ● waiting │ worker, tester                      │
│ worker  │ ● Edit    │ src/projects/filter.ts         0:42 │
│ tester  │ ● Write   │ tests/projects/filter.test.ts  0:38 │
│ judge   │ ○ —       │                                     │
└─────────┴───────────┴─────────────────────────────────────┘
```

- The hooks (SubagentStart/Stop, PreToolUse) and the CLI (running judges, with elapsed time) write the state to `.cplugin/sessions/<id>/board.json`.
- `.claude/bin/board --watch` runs in a second terminal and refreshes about once a second. Without arguments it shows the project's active session; `--session` picks one.
- One row per running agent: two workers in parallel show as two rows.
- `/cplugin:board` prints the same board once, in the chat.

## 8. Freehand and sandbox

- **`/cplugin:freehand`** suspends the blocks (no task, roles, Stop) until the next `tasks work`. The board shows "FREEHAND". What changed is recorded on reactivation, so it is not lost.
- **`.claude/bin/sandbox`** starts `claude --dangerously-skip-permissions` under `sandbox-exec`. It can write only inside the project, `.git` is read-only, and the rest of the system is blocked. When `sandbox-exec` is missing it **refuses to start** instead of running unconfined (playbook only warned).

## 9. Plugin layout

```
cplugin/
├── .claude-plugin/
│   ├── plugin.json
│   └── marketplace.json        # marketplace manifest, for installing
├── agents/
│   ├── worker.md
│   ├── tester.md
│   └── judge.md                # Claude fallback, Read/Grep/Glob only
├── skills/                     # /cplugin:<name>. Skills, not commands/ (the current recommendation)
│   ├── init/  mindmap/  freehand/  board/
│   └── workflow/SKILL.md       # how MAIN coordinates a task
├── hooks/
│   ├── hooks.json
│   └── run.py                  # single entry point for every hook
├── cplugin/                    # the Python package: tasks CLI, config, roles, board, judges
├── templates/                  # task.md, step shapes, MIND_MAP.md, mindmap-module.md, CLAUDE.md, config.toml
├── bin/                        # tasks.py, board.py, sandbox: entry points
└── tests/                      # stdlib unittest; hooks tested with JSON payloads
```

## 10. A project after `/cplugin:init`

```
project/
├── CLAUDE.md                   # a short section: workflow + commands
├── MIND_MAP.md
├── mindmap/
├── .cplugin/
│   ├── config.toml             # committed
│   ├── roles/                  # optional: project-specific role rules
│   ├── tasks/                  # committed: the history of decisions
│   └── sessions/               # runtime state, gitignored
└── .claude/
    ├── bin/                    # tasks, board, sandbox
    └── settings.json           # deny: TodoWrite, EnterPlanMode; playbook disabled here
```

`init` is idempotent: run again, it updates the plugin's sections and leaves everything else alone. If the project is not a git repository, it suggests `git init`.

## 11. Known limits and things to verify in the prototype

- **Same `session_id` in sub-agents?** The documentation does not say. Verify before tying state to it; otherwise tie it to the process ID, as playbook does.
- ~~The exact form of `agent_type`~~ Confirmed in the documentation: `cplugin:worker`, `cplugin:tester`.
- **`CLAUDE_PLUGIN_ROOT` does not exist in the model's Bash commands.** It is substituted only in skill text and in hooks. That is why the project gets launchers in `.claude/bin/`, rewritten at every session start (the path changes on upgrade).
- **Plugin agents ignore `hooks` and `permissionMode` in their frontmatter.** All enforcement goes through `hooks/hooks.json`, which was the plan anyway.
- **A plugin cannot ship `permissions.deny` or a status line through its settings.** That is why `init` writes into the project's `.claude/settings.json`.
- **Bash cannot be stopped beforehand**, only detected afterwards (4.2).
- **Coexisting with playbook**: playbook activates when it finds `.agent/tasks/`. We use `.cplugin/`, so it stays inactive. `init` disables it in the project anyway (`enabledPlugins`), so Claude does not use its skills by mistake.
- **We do not deny the `Agent` tool** (playbook denied `Task`, its former name). That would stop the sub-agents.

## 12. Compared with playbook

| We keep | We change | We drop |
|---|---|---|
| task.md as plan + log, checked one gate at a time | Two-level memory (MIND_MAP + `mindmap/`) | The chat log (UserPromptSubmit). The request is copied into task.md instead |
| Judges that do not see the conversation; the TAMPER check | Strict roles enforced by hooks (MAIN / worker / tester) | The Codex/Grok/Pi launchers for *writing* code. Other providers only judge |
| The SessionStart, PreToolUse, PostToolUse, Stop, SessionEnd hooks | Hooks in Python, with a single entry point | The monitor (a second agent watching) |
| Freehand, sandbox | Agent configuration in a single `config.toml` | The multi-user merge skill and per-user lanes |
| Session cleanup by process liveness | A live ASCII board; the sandbox refuses to run unconfined | |

## 13. Open decisions

1. **The plugin's final name.** For now it stays `cplugin`.
2. ~~Language~~ **Decided (2026-10-21): English** for templates, role prompts, hook messages, CLI output and all documentation, this specification included.
3. **How many workers in parallel** by default. For now 1, configurable.
4. **Git required?** For now yes: `init` warns when the project is not a git repository. Without git, the Bash check, the impl-review diff and the TAMPER check do not work.

## 14. Implementation order

Each milestone comes with tests and is usable on its own.

1. ✅ **Skeleton** (2026-10-21). Manifest, marketplace, `init`, templates, SessionStart loading `MIND_MAP.md`, `/cplugin:mindmap`. 28 tests; also verified with `claude -p --plugin-dir`.
2. ✅ **Tasks** (2026-10-21). The `tasks` CLI (new/work/stop/done/status/list/pause) + PreToolUse (no task, manual creation, 3+ checks, check without an outcome) + PostToolUse (current gate + questions) + Stop + SessionEnd. Tests first (Red/Green) in the template. 86 tests; verified with `claude -p`: a full task worked end to end, the no-task block and the open-gates Stop block. `plan-review` and `impl-review` only print a notice until milestone 5.
3. **Agents and roles.** `agents/worker.md`, `tester.md`, role rules in PreToolUse, the Bash check, SubagentStart/Stop, `config.toml` + `tasks config check`.
4. **Board.** `board.json` + `board --watch` + `/cplugin:board`.
5. **Judges.** Codex and agy adapters, read-only sandbox, TAMPER, panel, Claude fallback.
6. **Freehand and sandbox.**

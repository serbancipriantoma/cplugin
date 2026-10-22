# foreman: specification

> Draft v0.1, 2026-10-21. Named **foreman** on 2026-10-22 (the working name was `cplugin`): like a foreman, the main agent assigns the work, checks each stage and signs off, but does not lay the bricks itself. Projects set up under the old name move from `.cplugin/` to `.foreman/` on the next `/foreman:init`.
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
- `/foreman:mindmap` builds the first version from the existing code. On a new project, the user and Claude fill it in together from conversation.

## 3. The task

### 3.1 Where it lives and how it is created

- `.foreman/tasks/<NNN>-<type>-<name>/task.md`, plus a `judges/` folder for the judges' reports.
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

1. finds the role from `agent_type` (`foreman:worker`, `foreman:tester`, or missing = MAIN);
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

`.foreman/config.toml` is committed and can be edited by hand. TOML was chosen because it allows comments and Python reads it without dependencies (`tomllib`).

```toml
[workflow]
tests_first = true                  # false = tester and worker in parallel, no Red gate

[files]
extra_code_extensions = []          # added to the built-in list of code extensions
code_dirs = ["bin", "scripts"]      # everything in these directories counts as code

[roles.worker]
model = "opus"                      # opus | sonnet | haiku | fable
paths = ["**"]                      # any code that is not a test; narrow it to fence the worker in
max_parallel = 1                    # workers at once; the hook refuses one more

[roles.tester]
model = "sonnet"
paths = ["tests/**", "test/**", "**/__tests__/**", "**/test_*.py", "**/*_test.*",
         "**/*.test.*", "**/*.spec.*"]

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

- A code file matching the tester's paths is a test; any other code file matching the worker's paths is production code. Code that matches neither belongs to no role, and the hook says to add it to a role's paths. Settings left out of the file fall back to these defaults, so older configs keep working.
- `roles.worker.max_parallel` (default 1) caps the workers running at once: the PreToolUse hook refuses one more, counting the starts it approved a moment ago whose agents are not recorded yet (two Agent calls in one message), under a file lock. Raise it only for steps that touch different files.
- MAIN reads each role's model from the config (`tasks config show`) and passes it when it starts the sub-agent; the hook refuses a foreman agent started with another model. Changing a model never means editing the plugin. The Agent tool takes only the aliases, so a full model ID cannot be enforced.
- Role prompts live in the plugin (`agents/*.md`). For project-specific rules, add `.foreman/roles/<role>.md`; MAIN includes it in the sub-agent's prompt.
- `tasks config check` validates the file: types, empty role paths, models that cannot be enforced, the test command and the judges' CLIs being on PATH.

## 5. Judges

- `tasks plan-review <N>` or `tasks impl-review <N>`, run by MAIN in the background (they take minutes), starts them. `--seat codex|agy|claude[:model]` replaces the configured seats for one run; `--timeout-min` overrides `judges.timeout_min` (default 8, under the 10 minutes a Claude Code command may run).
- `judges.mode = "panel"` runs every configured seat in parallel; `"single"` the first one installed. Seats whose CLI is not on PATH are skipped with a note. When none is left, `fallback = "claude"` runs `claude -p` limited to Read, Grep and Glob; `"none"` fails.
- Each judge gets one prompt (`templates/judge-prompt.md`): what to look for at that stage, the answer format (Verdict: ACCEPT / ACCEPT WITH CHANGES / REJECT, then numbered findings with severity and file:line), `task.md` without its review sections (earlier findings and their triage would anchor it), `MIND_MAP.md`, the detail files the task names, and read access to the repository. For impl-review it also gets the diff since the task started (`tasks new` records the base commit in the task's `meta.json`; committed and uncommitted changes count, new files included, `.foreman/` excluded). It never gets the conversation.
- How each runs: `codex exec -s read-only` (Codex's own sandbox, on macOS and Linux; prompt on stdin, last message to a temp file); `agy --print` and the `claude` fallback under `sandbox-exec` (macOS) or bubblewrap (Linux, `docs/linux.md`): every write denied except the temp folders and the state the CLIs keep under the home folder, and the project and its `.git` denied explicitly, even when the project sits inside a temp folder (`foreman/containment.py`). When no containment can be applied (already inside another sandbox, which macOS cannot nest; bubblewrap missing or its namespaces blocked), they run without OS protection and the command says so. Judge processes get `FOREMAN_JUDGE=1`, so foreman's own hooks stand down inside them.
- On top of that, a **tamper check** compares the working tree (git status with mtimes), the hash of `task.md` and `HEAD` before and after. If anything changed, every review of that run is marked TAMPER and not used, and the command exits 1 (an idea taken from playbook). It exits 2 when every judge failed.
- Each judge's full report goes to `judges/<stage>-<seat>-<time>.md`; a summary (verdicts, report paths, and each judge's findings) is appended to the stage's section of `task.md` as a quote, so no finding can ever pass for a gate. The CLI writes them, not the judges. MAIN then triages each finding: accepted, parked or rejected, with the reason.
- While they run, the judges are on the board, one row per seat, and the Stop hook lets MAIN wait for them.
- The development machine has `codex` 0.156.1 and `agy` 1.2.9 (`agy models` lists its models, Gemini and others).

## 6. Hooks

| Event | What it does |
|---|---|
| **SessionStart** (`startup`, `resume`, `clear`, `compact`) | Registers the session (the ID from the payload, the Claude process running it, and `FOREMAN_SESSION_ID` through `CLAUDE_ENV_FILE`). Writes `.claude/bin/` (`tasks`, `board`, `sandbox`). Removes dead sessions. After `/clear`, if the ID changed, takes over the active task of the previous session of the same process. **Loads `MIND_MAP.md` and the active task's state** (the current gate) into context |
| **PreToolUse** (`Edit\|Write\|MultiEdit\|NotebookEdit\|Bash\|Agent`) | Blocks code without an active task. Enforces the roles (4.2); sub-agents also stay out of task.md and `.foreman/`. Blocks creating tasks by hand. Blocks checking 3+ gates at once and warns at 2. Blocks `tasks …` commands that change state when a sub-agent runs them. Starts foreman agents only for an active task, with the configured model and without worktree isolation. Snapshots `git status` before Bash. Records the action for the board |
| **PostToolUse** (all tools) | For MAIN: shows the current gate (`file:line`) and a check question that depends on what it just did ("Is this the simplest change that works?", "Did it pass for the right reason?"). For every agent: the Bash check (4.2) and the board record |
| **SubagentStart** | Records the agent as running. For the worker and the tester, adds the role's rules and the current step to its context; for any other sub-agent, a note that only those two write code and tests |
| **SubagentStop** | Records the agent as finished |
| **Stop** | Does not let MAIN end its turn while gates are open. Exceptions: a conversational turn (no writes and fewer than 5 tool calls since the last Stop), sub-agents still running (they run in the background, and MAIN ends its turn to wait for them; verified), MAIN ran `tasks pause "<reason>"` because it needs the user (a decision, an answer, a manual check), freehand mode, or `stop_hook_active` (so it never loops) |
| **SessionEnd** | Records that the session closed but **does not delete its state**. `claude --continue` keeps the same session ID (verified), so the active task must survive the restart. Sessions are removed only when their process is gone and they have been idle for 7 days |

### Starting a session

Nothing has to be typed to "start" foreman: in a project with `.foreman/config.toml`, the SessionStart hook loads the memory and the active task on its own. It also shows the user a short banner (a hook `systemMessage`) and puts the same lines into the main agent's context:

```
foreman 0.1.0 · task 003 shout active, gate 7/18 · MIND_MAP.md 6,054 / 8,500 characters, 14 detail file(s) in mindmap/
agents: worker opus · tester sonnet
judges: codex ✓, agy ✗ not installed  (say "start" for details)
```

A judge whose CLI is not on PATH is marked ✗; with none installed, the banner names the fallback; when judges cannot be sandboxed, a warning line is added. Saying **"start"** (or `/foreman:start`), as in playbook, runs `tasks start`: the plugin's location, each role's model and agent file, each judge seat with the path of its CLI and its model, the fallback, the containment available, the memory, the active and open tasks and the test command. Claude then points out only what needs attention and asks what to work on, without picking a task itself.

Principles, learned from playbook's problems:

- a hook must never take the session down: on an internal error it blocks nothing, with one exception, the "no active task" rule, which also blocks when the hook cannot tell for sure;
- hooks are written in Python (stdlib, ≥3.11) with a single entry point (`hooks/run.py <event>`), not in bash that calls Python five times per call;
- session cleanup never follows symbolic links.

## 7. The ASCII board

```
┌ TASK 007 · project-filter ─ gate 9/18 ───────────────────────┐
│ 3. Work Plan › Step 2: category filter — Red: the tests fai… │
├─────────┬────────────┬───────────────────────────────────────┤
│ MAIN    │ ● waiting  │ for worker, tester                    │
│ worker  │ ● Edit     │ src/projects/filter.ts           0:42 │
│ tester  │ ● Bash     │ node --test tests/projects       0:38 │
│ judge   │ ○ —        │                                       │
└─────────┴────────────┴───────────────────────────────────────┘
```

- The hooks keep one record per agent in `.foreman/sessions/<id>/agents/<agent>.json` (MAIN is `main.json`): role, running or done, start time, last tool and its target. The board only reads them; the CLI will add the judges' rows in milestone 5.
- `.claude/bin/board --watch` runs in a second terminal and redraws every second (`--interval` changes it). Without arguments it shows the session worth watching: a live one first, then one with an active task, then the most recent. `--session` picks one by ID or prefix.
- The header shows the task, the gate number and the current gate; a `tasks pause` replaces the gate with what MAIN is waiting for, and freehand mode is marked.
- MAIN shows **waiting** while sub-agents run and it has done nothing since starting them, its last tool while it is busy, and **idle** after a minute without tool calls.
- One row per running sub-agent, with its last tool, target and running time: two workers in parallel show as two rows. A finished worker or tester stays on the board for 30 minutes as **done**; a record with no activity for 2 hours no longer counts as running. Other sub-agents (Explore, general-purpose) get a row while they run.
- The width follows the terminal (50 to 100 columns); colors only on a terminal, never with `--no-color` or `NO_COLOR`.
- `/foreman:board` prints the same board once, in the chat.

## 8. Freehand and sandbox

- **`/foreman:freehand`** suspends the rules (no task needed for code, no roles, no Bash check, no held turns) until `tasks work <N>` or `tasks freehand off`. An active task is paused meanwhile. **Only the user turns it on**: the skill runs the CLI itself (a `!` command, which no hook intercepts; verified), and the PreToolUse hook refuses `tasks freehand` from every agent, the main one included. Ending it is allowed to anyone. When it ends, the commits made and the files changed since it began are appended to `.foreman/freehand.md` and summarized for the main agent, with a reminder to update the mind map. The banner, the main agent's context and the board show it while it is on. What stays enforced: tasks are created only by `tasks new`, session state belongs to the CLI, and sub-agents keep out of `.foreman/`.
- **`.claude/bin/sandbox [claude arguments]`** starts `claude --dangerously-skip-permissions` under `sandbox-exec` on macOS or bubblewrap on Linux, from the project's root, adding `--plugin-dir` when the plugin is a checkout rather than an installed copy. The profile denies every write except: the project (but not `.git`, so history cannot be rewritten), the temp folders and `/dev`, and what Claude Code and its tools keep under the home folder (`~/.claude`, `~/.claude.json`, `~/.codex`, `~/.gemini`, `~/.cache`, `~/.local`, `~/.npm`, `~/.config`, `~/Library`). Reads and the network stay open. On Linux, bubblewrap mounts everything read-only, then the same places writable (those that exist), the project writable and its `.git` read-only again; `/proc` is fresh when the system allows it. It **refuses to start** instead of running unconfined (playbook only warned): on other systems, without the tool, where the OS refuses it (inside another sandbox; on Linux, blocked user namespaces or a container), or inside itself. `docs/linux.md` covers the Linux setup and has a test checklist. The banner says "sandboxed". `--dry-run` prints the command (and the macOS profile). Verified on macOS: Claude Code started and signed in inside it; a write in the project worked, writes to the home folder and to `.git` were denied. The Linux path is covered by unit tests of the bubblewrap command and awaits a run on a Linux machine. Judges started from inside the sandbox cannot get a sandbox of their own (it cannot be nested), so the tamper check guards them there.

## 9. Plugin layout

```
foreman/
├── .claude-plugin/
│   ├── plugin.json
│   └── marketplace.json        # marketplace manifest, for installing
├── agents/
│   ├── worker.md
│   └── tester.md               # judges are external CLIs, not agents (section 5)
├── skills/                     # /foreman:<name>. Skills, not commands/ (the current recommendation)
│   ├── init/  start/  mindmap/  freehand/  board/
│   └── workflow/SKILL.md       # how MAIN coordinates a task
├── hooks/
│   ├── hooks.json
│   └── run.py                  # single entry point for every hook
├── foreman/                    # the Python package: tasks CLI, config, roles, board, judges
├── templates/                  # task.md, step shapes, MIND_MAP.md, mindmap-module.md, CLAUDE.md, config.toml
├── bin/                        # tasks.py, board.py, sandbox: entry points
└── tests/                      # stdlib unittest; hooks tested with JSON payloads
```

## 10. A project after `/foreman:init`

```
project/
├── CLAUDE.md                   # a short section: workflow + commands
├── MIND_MAP.md
├── mindmap/
├── .foreman/
│   ├── config.toml             # committed
│   ├── roles/                  # optional: project-specific role rules
│   ├── tasks/                  # committed: the history of decisions
│   └── sessions/               # runtime state, gitignored
└── .claude/
    ├── bin/                    # tasks, board, sandbox
    └── settings.json           # deny: TodoWrite, EnterPlanMode; playbook disabled here
```

`init` is idempotent: run again, it updates the plugin's sections and leaves everything else alone. In `config.toml` it changes only settings that still hold a default an older version wrote and a newer one replaced (for example the worker's paths); values the user changed are never touched. If the project is not a git repository, it suggests `git init`.

## 11. Known limits and things to verify in the prototype

- ~~Same `session_id` in sub-agents?~~ Verified: a sub-agent's tool calls carry the main session's `session_id`, plus `agent_id` and `agent_type`, so sub-agents find the active task directly.
- **Debugging hooks:** set `FOREMAN_HOOK_LOG=<file>` before starting Claude Code and every hook payload and reply is appended to that file.
- ~~The exact form of `agent_type`~~ Confirmed in the documentation: `foreman:worker`, `foreman:tester`.
- **`CLAUDE_PLUGIN_ROOT` does not exist in the model's Bash commands.** It is substituted only in skill text and in hooks. That is why the project gets launchers in `.claude/bin/`, rewritten at every session start (the path changes on upgrade).
- **Plugin agents ignore `hooks` and `permissionMode` in their frontmatter.** All enforcement goes through `hooks/hooks.json`, which was the plan anyway.
- **A plugin cannot ship `permissions.deny` or a status line through its settings.** That is why `init` writes into the project's `.claude/settings.json`.
- **Bash cannot be stopped beforehand**, only detected afterwards (4.2).
- **Coexisting with playbook**: playbook activates when it finds `.agent/tasks/`. We use `.foreman/`, so it stays inactive. `init` disables it in the project anyway (`enabledPlugins`), so Claude does not use its skills by mistake.
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

1. ~~The plugin's final name~~ **Decided (2026-10-22): foreman.** The GitHub repository keeps its old name (`serbancipriantoma/cplugin`) until it is renamed.
2. ~~Language~~ **Decided (2026-10-21): English** for templates, role prompts, hook messages, CLI output and all documentation, this specification included.
3. **How many workers in parallel** by default. For now 1, configurable.
4. **Git required?** For now yes: `init` warns when the project is not a git repository. Without git, the Bash check, the impl-review diff and the TAMPER check do not work.

## 14. Implementation order

Each milestone comes with tests and is usable on its own.

1. ✅ **Skeleton** (2026-10-21). Manifest, marketplace, `init`, templates, SessionStart loading `MIND_MAP.md`, `/foreman:mindmap`. 28 tests; also verified with `claude -p --plugin-dir`.
2. ✅ **Tasks** (2026-10-21). The `tasks` CLI (new/work/stop/done/status/list/pause) + PreToolUse (no task, manual creation, 3+ checks, check without an outcome) + PostToolUse (current gate + questions) + Stop + SessionEnd. Tests first (Red/Green) in the template. 86 tests; verified with `claude -p`: a full task worked end to end, the no-task block and the open-gates Stop block. `plan-review` and `impl-review` only print a notice until milestone 5.
3. ✅ **Agents and roles** (2026-10-21). `agents/worker.md`, `tester.md`, the `foreman:workflow` skill, role rules in PreToolUse, the Bash check with a Violations section in task.md, SubagentStart/Stop with a per-agent record (the board's data), Stop waiting for running sub-agents, `tasks config show|check`. 112 tests; verified with `claude -p`: MAIN delegated tests and code to the two sub-agents, Red caught tests failing for the wrong reason, and the task closed with every file written by its owner. `max_parallel` was advice in the skill until 2026-10-22, when the hook started enforcing it.
4. ✅ **Board** (2026-10-21). `.claude/bin/board` (once, or `--watch`), `/foreman:board`, reading the per-agent records. 128 tests; verified live: frames captured every 3 seconds during a `claude -p` run showed MAIN creating the task, waiting for the tester, running Red, then waiting for the worker, and the task closing.
5. ✅ **Judges** (2026-10-22). Codex and agy seats, read-only containment, the tamper check, panel and single modes, the `claude -p` fallback, reports and quoted summaries, judges on the board. 142 tests, with stand-in CLIs (a guard makes the real ones unreachable from tests); verified with the real CLIs: on a plan with a planted mistake (a CommonJS interface in an ES-module project), Codex and Antigravity both flagged it as high, with file:line evidence, and found two real gaps besides, in 39 seconds in parallel.
6. ✅ **Freehand and sandbox** (2026-10-22). `/foreman:freehand` (user only) and `tasks freehand off`, the freehand log, `.claude/bin/sandbox`. 158 tests; verified with `claude -p`: the skill turned freehand on, and Claude Code ran inside the sandbox with home and `.git` writes denied.

After the plan (2026-10-22): the plugin was renamed from `cplugin` to **foreman** (projects move from `.cplugin/` to `.foreman/` on the next `/foreman:init`); `max_parallel` is enforced; containment works on Linux through bubblewrap, pending a run on a Linux machine with `docs/linux.md`.

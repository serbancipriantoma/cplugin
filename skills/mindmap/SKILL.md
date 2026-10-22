---
name: mindmap
description: Build or refresh the two-level project memory of a foreman project - MIND_MAP.md (big ideas) and mindmap/<module>.md (details per module) - from the codebase and the user's explanations.
argument-hint: "[module to focus on]"
---

# foreman mind map

The project memory has two levels:

| File | Holds | Loaded |
|---|---|---|
| `MIND_MAP.md` | The big ideas: one numbered node per module, 3-6 bullets each, linking its detail file | Automatically at every session start. Hard budget: **8,500 characters** |
| `mindmap/<module>.md` | What each part of the module does: rules, data, edge cases, where the code and tests are, decisions taken | On demand, when work touches the module |

Focus: $ARGUMENTS (when empty, cover the whole project)

## 0. Preconditions

If `.foreman/config.toml` does not exist, tell the user to run `/foreman:init` first and stop.

Decide the mode:
- **Build**: `MIND_MAP.md` is missing or still contains the `<!-- foreman:stub` line.
- **Refresh**: it has real content. Keep what the user wrote, update nodes in place,
  fix what is stale, and never append one node per task or per change.

## 1. Learn the project

- Read the README, docs and manifests (package.json, pyproject.toml, ...). Map the
  top-level directories, entry points and test layout.
- If the project is a git repository, skim `git log --oneline -50` for the main phases.
- If there is little or no code yet, interview the user instead: what the project
  is, who uses it, which modules it has, and what each module must do.

## 2. Agree on the modules with the user

Propose the module list, one line each. Prefer what the product does (Projects,
About, Contact) over how the code is split; add technical subsystems
(data model, integrations, auth) only where they matter on their own. Ask the user
to correct the list and to add goals and constraints that are not visible in the code.
Wait for the answer before writing.

## 3. Write `MIND_MAP.md`

- Open `MIND_MAP.md` with the Read tool first, even if you already saw it through
  Bash: the Write tool refuses to overwrite a file this session has not Read.
- Delete the `<!-- foreman:stub ... -->` line.
- `[1] Overview` first: what the project is, who uses it, the module list with node numbers.
- One node per module, titled `## [N] <Module> → mindmap/<file>.md`, with 3-6 bullets
  stating what the module does, linking related nodes as `[N]`.
- Then cross-cutting nodes if needed: data model, integrations, conventions, stack.
- Big ideas only. Anything longer than a bullet belongs in the detail file.

Example:

```markdown
## [2] Projects → mindmap/projects.md
- Shows the work as a grid of project cards, filterable by category
- Each project has a case-study page: problem, process, result, images
- The home page features the 3 latest projects, each linking to Contact [4]
```

## 4. Write one `mindmap/<module>.md` per module

File names are lowercase kebab-case (`projects.md`, `case-studies.md`). Start from this
shape, with one `##` section per part of the module:

```markdown
# Projects — details

Summary in MIND_MAP: [2]

## Project grid
- What it does:
- Rules:
- Data:
- Edge cases:
- Code:
- Tests:
- Decisions: (why things are the way they are)
```

Fill in what you actually found or were told; write "unknown" rather than guessing.
If a detail file grows past ~400 lines, split it into `mindmap/<module>/<section>.md`
and link the parts from the module file.

## 5. Verify

- `MIND_MAP.md` no longer contains the `<!-- foreman:stub` line. If it does, the write
  failed: Read the file and write it again before going on.
- Every module node links a detail file that exists, and each detail file names its node.
- `wc -c MIND_MAP.md` is under 8,500. If not, move detail down into `mindmap/`.
- Show the user what the next session will load:

  ```bash
  python3 -I "${CLAUDE_PLUGIN_ROOT}/bin/tasks.py" context
  ```

Write the map in English unless the user asks for another language.

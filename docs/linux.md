# foreman on Linux

On Linux, foreman contains writes with **bubblewrap** (`bwrap`), where macOS uses
`sandbox-exec`. Two features depend on it:

- `.claude/bin/sandbox`, which runs Claude Code without permission prompts;
- the `agy` and `claude` judges, which must not be able to change the project.

The `codex` judge uses Codex's own sandbox and needs nothing extra.

Without a working bubblewrap, the sandbox refuses to start, and the agy and claude
judges run with only the tamper check. The session banner and `tasks start` say so.

## Requirements

- Python 3.11 or newer, git, and Claude Code (`claude`).
- bubblewrap:

  | System | Command |
  |---|---|
  | Debian, Ubuntu | `sudo apt install bubblewrap` |
  | Fedora | `sudo dnf install bubblewrap` |
  | Arch | `sudo pacman -S bubblewrap` |

- Unprivileged user namespaces must be allowed. Check with:

  ```bash
  bwrap --ro-bind / / --dev /dev true && echo ok
  ```

  If that fails:

  - **Ubuntu 23.10 and newer** (24.04 included) restrict them through AppArmor. The
    narrow fix is an AppArmor profile that lets only bwrap create them:

    ```bash
    sudo tee /etc/apparmor.d/bwrap > /dev/null <<'EOF'
    abi <abi/4.0>,
    include <tunables/global>

    profile bwrap /usr/bin/bwrap flags=(unconfined) {
      userns,
      include if exists <local/bwrap>
    }
    EOF
    sudo systemctl reload apparmor
    ```

    The system-wide alternative is `sudo sysctl kernel.apparmor_restrict_unprivileged_userns=0`.
  - **Older Debian**: `sudo sysctl kernel.unprivileged_userns_clone=1`.
  - **Inside a Docker or Podman container**, bwrap usually cannot create namespaces at
    all. Run foreman on the host or in a virtual machine.

## What is contained

Everything is mounted read-only (`--ro-bind / /`), then these are mounted writable again:

- `/tmp`, `/var/tmp`, `$TMPDIR` and `$XDG_RUNTIME_DIR`;
- whichever of these exist under the home folder: `~/.claude`, `~/.claude.json`, `~/.codex`,
  `~/.gemini`, `~/.cache`, `~/.local`, `~/.npm` and `~/.config`;
- for the sandbox launcher, the project itself, with its `.git` mounted read-only on top.

For judges the project stays read-only, even when it sits inside `/tmp`. Reads and the
network stay open. A fresh `/proc` is mounted when the system allows it; otherwise the
host's `/proc` is used.

## Test checklist

Please run these on the Linux machine and send back the output of each step.

1. **The system.** Send the output of these commands:

   ```bash
   cat /etc/os-release; uname -r; bwrap --version; python3 --version; claude --version
   ```

2. **The test suite.**

   ```bash
   git clone https://github.com/serbancipriantoma/cplugin.git foreman
   cd foreman/tests && python3 -m unittest -v 2>&1 | tail -40
   ```

   Everything should pass. `RealContainmentTest` should run, not be skipped, wherever the
   `bwrap ... && echo ok` check above printed `ok`.

3. **A scratch project.** Use one under the home folder, not under `/tmp`: `/tmp` is
   writable anyway, so the next steps would prove nothing there.

   ```bash
   mkdir ~/foreman-test && cd ~/foreman-test && git init
   claude --plugin-dir ~/path/to/foreman
   ```

   In Claude Code, run `/foreman:init`, then type `start`. The Judges part should say
   `containment: bwrap works here`.

4. **The sandbox command.** Back in the shell:

   ```bash
   .claude/bin/sandbox --dry-run
   ```

   Send the command it prints.

5. **The sandbox itself.** Run `.claude/bin/sandbox`, and ask the Claude Code it starts to
   run these three commands and report each result:

   ```bash
   touch ./inside.txt
   touch ~/foreman-probe.txt
   touch .git/probe
   ```

   The first should work. The other two should fail with "Read-only file system".

   Then check that Claude Code itself still works inside the sandbox:
   - send a normal message;
   - change any setting with `/config`, which writes `~/.claude.json`;
   - exit, then start it again with `.claude/bin/sandbox --continue`.

6. **Judges.** In the scratch project, outside the sandbox:

   ```bash
   .claude/bin/tasks new feature probe --request "Add a hello() function"
   .claude/bin/tasks plan-review 1 --seat claude
   ```

   If `codex` or `agy` are installed, repeat with `--seat codex` and `--seat agy`. Each
   run should end with a verdict and no TAMPER. The `Containment:` line of each report in
   `.foreman/tasks/001-feature-probe/judges/` should mention bwrap; for codex, its own
   sandbox.

7. **If something fails,** send the full error. If the hooks misbehave, start Claude Code
   with `FOREMAN_HOOK_LOG=/tmp/foreman-hooks.jsonl claude --plugin-dir ...`, repeat the
   step, and send that file.

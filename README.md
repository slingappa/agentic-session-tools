# agentic-session-tools

`agentic-session-tools` is a small, relocatable helper for browsing and resuming
Codex and Claude Code sessions without modifying either tool's session files.

It provides:

- `agentic-sessions list` — list recent Codex or Claude sessions with time, CWD, and prompt preview
- `agentic-sessions rename` — add fallback human-friendly titles when no native provider title exists
- `agentic-sessions delete` — move session JSONL files to a recoverable trash folder
- `agentic-sessions resume` — resume by UUID, UUID prefix, or unique text fragment
- `agentic-sessions tmux` — tmux two-pane workspace with a session sidebar

The tool is intentionally dependency-light: Python 3 stdlib plus `tmux` for sidebar mode.


## Screenshots

The screenshots below use representative session data and show the current
provider-aware list plus boxed tmux sidebar; they do not expose real team session
contents.

### Dependency Check

![agentic-sessions doctor terminal output](docs/screenshots/doctor.svg)

### Session List

![agentic-sessions list terminal output](docs/screenshots/list.svg)

### tmux Sidebar With Resumed Agent Session

![agentic-sessions tmux sidebar next to an active resumed agent session](docs/screenshots/tmux-sidebar.svg)

## Requirements

Required:

- Linux/macOS shell environment with Python 3.7+ and stdlib `curses`.
- Codex sessions under `$CODEX_HOME/sessions`, `$CODEX_HOME/agent/sessions`, `~/.codex/sessions`, or `~/.config/codex/sessions`.
- Claude sessions under `$CLAUDE_CONFIG_DIR/projects`, `$CLAUDE_HOME/projects`, `~/.claude/projects`, or `~/.config/claude/projects`.
- `codex`/`claude` in `PATH`, common install locations, or explicit `CODEX_BIN` / `CLAUDE_BIN` for resume/sidebar.
- `tmux` for `agentic-sessions tmux`; `bash` and `install` for `install.sh`.

No external Python packages are required. On some Linux distributions, install `python3-curses` separately.

Run this after install to verify a machine:

```bash
agentic-sessions doctor
```

Use `--strict` to include agent CLI and `tmux` checks:

```bash
agentic-sessions doctor --strict
```

## Quick Start

From this folder:

```bash
./install.sh --aliases
# Follow the printed "Quick start" commands to reload aliases for this shell.
ags doctor
ags list -n 10
ags tmux
```

By default, `agentic-sessions` uses `--provider codex,claude` and merges sessions
from both tools by modified time. Filter to one provider when needed:

```bash
ags --provider codex list -n 10
ags --provider claude doctor
ags --provider claude list -n 10
ags --provider claude tmux
```

Without installing:

```bash
export PATH=/path/to/agentic-session-tools/bin:$PATH
agentic-sessions list -n 10
agentic-sessions tmux
```

If Codex is not in `PATH`, or you need a Codex-compatible wrapper:

```bash
export CODEX_BIN=/absolute/path/to/codex
# Optional: if sessions live outside the default Codex home
export CODEX_HOME=/absolute/path/to/codex-home-or-agent
agentic-sessions tmux
```

For Claude Code, use:

```bash
export CLAUDE_BIN=/absolute/path/to/claude
export CLAUDE_CONFIG_DIR=/absolute/path/to/claude-config
agentic-sessions --provider claude tmux
```

For machine-local defaults without changing your shell rc, create an ignored local env file next to this repo:

```bash
cat > .agentic-session-tools.env <<'EOF'
CODEX_HOME=/absolute/path/to/codex-home-or-agent
CODEX_BIN=/absolute/path/to/codex-or-compatible-wrapper
CLAUDE_CONFIG_DIR=/absolute/path/to/claude-config
CLAUDE_BIN=/absolute/path/to/claude-or-compatible-wrapper
EOF
```

## Installation

Install to `~/.local/bin`:

```bash
./install.sh
```

Install and add convenience aliases:

```bash
./install.sh --aliases
# The installer detects the running shell rc file and prints the exact reload command.
```

Install to a custom prefix:

```bash
./install.sh --prefix ~/tools
export PATH="$HOME/tools/bin:$PATH"
```

The installer copies `bin/agentic-sessions` plus a compatibility `bin/codex-sessions` wrapper; the tool remains relocatable.

`agentic-sessions` is the primary command. `codex-sessions` remains installed as
a backward-compatible entry point for existing scripts and muscle memory.


## Shell RC / Alias Notes

Shell rc changes are optional. `./install.sh --aliases` adds `ags`, `cs`, and
`cxs` to the detected rc file (`~/.zshrc`, `~/.bashrc`, or `~/.profile`) and
prints the reload command. To avoid rc changes, add the install prefix to `PATH`
or run `bin/agentic-sessions` directly.

The sidebar resolves agent CLIs through `CODEX_BIN`/`CLAUDE_BIN`, `PATH`, or
common install locations. If the wrong executable is selected, set:

```bash
export CODEX_BIN=/absolute/path/to/codex
export CLAUDE_BIN=/absolute/path/to/claude
```

`CODEX_BIN` and `CLAUDE_BIN` are intentionally generic: they may point to the real
CLI or a compatible wrapper executable. The tool does not hardcode wrapper names.
When either variable points at the `qgenie` executable, resume commands are sent
through QGenie's native Codex-compatible form, for example `qgenie resume <id>`.

For wrappers using `script`, common Linux argument order is:

```bash
script -qf -c "/path/to/codex resume <id>" /path/to/logfile
```

BSD/macOS `script` variants may differ.

## Commands

Show detected paths and dependency status:

```bash
agentic-sessions paths
agentic-sessions doctor
agentic-sessions doctor --strict
agentic-sessions --provider claude doctor
```

List sessions:

```bash
agentic-sessions list -n 20
agentic-sessions --provider codex,claude list -n 20
agentic-sessions --provider codex list -n 20
agentic-sessions --provider claude list -n 20
agentic-sessions list -q rv_github
agentic-sessions list --long
agentic-sessions list --json
agentic-sessions --provider codex list --all  # include generated child/background rollouts
```

The default and explicit `--provider codex,claude` modes interleave providers by
modified time. If the newest rows are all from one provider, increase `-n` or filter
with `--provider codex` / `--provider claude`.
Default views show top-level interactive sessions only so generated child,
background, and SDK probe sessions do not flood the list; use `--all` when you
need to inspect raw session files.

Rename a session with fallback sidecar metadata:

```bash
agentic-sessions rename 019eda11 "RPMI telemetry docs"
agentic-sessions rename 019eda11 ""   # clear custom title
```

Resume a session:

```bash
agentic-sessions resume 019eda11
agentic-sessions resume "RPMI telemetry"
agentic-sessions --provider claude resume 5656cd9d
```

Claude Code resume is run from the session's saved working directory because
Claude stores resumable conversations in project-scoped history.

Trash a session JSONL file:

```bash
agentic-sessions delete 019eda11
```

Launch the tmux sidebar:

```bash
agentic-sessions tmux
agentic-sessions --provider claude tmux
```

Inside an existing tmux session, `tmux` mode splits the current window into panes.
Outside tmux, it creates a new tmux session with one window and two panes.

## tmux Sidebar Keys

- `j` / `k` or arrow keys: move selection
- `Enter`: suspend the current right-pane agent with `Ctrl-Z`, resume selected session, and focus that pane
- `r`: prefill native `/rename` in the right pane for the active resumed session
- `d`: trash selected session after typing `DELETE`
- `/`: search/filter sessions
- `c`: clear search filter
- `R`: refresh cached session list
- `?`: show key help popup and toggle expanded sidebar help
- `q`: close the sidebar pane
- detected tmux prefix + `Left`: focus the sidebar pane from the agent pane
- detected tmux prefix + `Right`: focus the agent pane from the sidebar pane
- detected tmux prefix + `?`: show key help popup from either pane
- detected tmux prefix + `b`: reopen the sidebar if it was closed
- mouse click: focus the clicked pane when tmux mouse mode is enabled

Sidebar behavior:

- Card titles show `time · provider · name`; body rows show cwd, prompt `context`, and short id.
- Native names come from Codex/QGenie `session_index.jsonl` `thread_name` and Claude project JSONL `slug` when available.
- `r` stages `/rename <current-name>` in the right pane only for the active resumed session; edit there and press `Enter` yourself.
- Prompt context is never used as a rename default. Staging rename pauses background scanning; press `R` after submitting if you want native names reloaded.
- Sessions load newest-first in chunks for fast first paint and cached navigation. Search, clear, delete, and `R` reload.
- Prefix + `b` reopens the sidebar. Prefix + `?` shows help from either pane. The tmux status bar keeps these hints visible after the sidebar closes.
- Switching sessions suspends the current right-pane agent with `Ctrl-Z`; use `jobs`/`fg` there if needed.

## Optional tmux Configuration

The installer adds `set -g mouse on` to `~/.tmux.conf` only when no tmux mouse
setting exists. Use `--no-tmux-mouse` to skip it. Optional local extras:

```tmux
set -g mouse on

# Copy selected text to the X clipboard when mouse drag selection ends.
# Requires xclip on Linux/X11 systems.
bind-key -T copy-mode-vi MouseDragEnd1Pane send-keys -X copy-pipe-and-cancel "xclip -se c -i"
bind-key -T copy-mode MouseDragEnd1Pane send-keys -X copy-pipe-and-cancel "xclip -se c -i"

# Shift-left/right pane switching. Terminal support for these keys may vary.
bind -n S-Right select-pane -t :.+
bind -n S-Left select-pane -t :.-
```

Reload after editing:

```bash
tmux source-file ~/.tmux.conf
```

## Working Directory Prompt

Codex or Claude may ask follow-up questions in the right pane. For example, Codex may ask:

```text
Choose working directory to resume this session
1. Use session directory (...)
2. Use current directory (...)
```

After selecting a session from the sidebar, focus should automatically move to the
right pane. Press `Enter` to accept the default, or choose the desired option there.
Use the displayed tmux prefix + `Left` to return to the sidebar pane.

## Safety Model

The tool does not edit Codex or Claude session JSONL files for normal metadata operations.
It reads provider-owned native display names when they are present, but does not
write provider indexes directly.

- Native names are read from provider metadata where available:
  - Codex/QGenie: `session_index.jsonl` `thread_name` entries
  - Claude Code: project JSONL `slug` entries
- Sidebar rename uses provider-native `/rename` for the active right-pane session.
- The `agentic-sessions rename` CLI command still stores fallback custom names in sidecar metadata:
  - Codex: `~/.codex/session-tools/session-names.json`
  - Claude: `~/.claude/session-tools/session-names.json`
- Delete/trash moves rollout files into:
  - Codex: `~/.codex/session-tools/trash/`
  - Claude: `~/.claude/session-tools/trash/`
- Trash operations append a manifest:
  - `trash/manifest.jsonl` under the selected provider's state root

Use `--state-root DIR` to keep metadata somewhere else.

## Configuration Overrides

Use these when auto-detection does not match your setup:

```bash
agentic-sessions --agent-home /path/to/agent paths
agentic-sessions --sessions-root /path/to/sessions list
agentic-sessions --state-root /path/to/state rename <id> "Title"
agentic-sessions tmux --codex-bin /path/to/codex
agentic-sessions --provider claude --agent-home /path/to/.claude paths
agentic-sessions --provider claude tmux --claude-bin /path/to/claude
```

Environment variables:

- `AGENTIC_SESSION_PROVIDER`: default provider list, for example `codex`, `claude`, or `codex,claude`; default is `codex,claude`
- `CODEX_SESSION_PROVIDER`: legacy default-provider variable, still honored
- `CODEX_BIN`: explicit Codex binary path
- `CODEX_HOME`: agent home containing `sessions/`, or CLI home containing `agent/sessions/`
- `CODEX_SESSIONS_ROOT`: explicit rollout JSONL session root; overrides `CODEX_HOME`
- `AGENTIC_SESSION_TOOLS_HOME`: sidecar metadata root for both providers
- `CODEX_SESSION_TOOLS_HOME`: legacy sidecar metadata root, still honored
- `CLAUDE_BIN`: explicit Claude Code binary path
- `CLAUDE_CONFIG_DIR` or `CLAUDE_HOME`: Claude config dir containing `projects/`
- `CLAUDE_SESSIONS_ROOT`: explicit Claude JSONL session root; overrides `CLAUDE_CONFIG_DIR`
- `CLAUDE_SESSION_TOOLS_HOME`: Claude sidecar metadata root

## Validation Status

Validated with Python 3.7-compatible syntax checks, fake Codex/Claude sessions,
install/doctor/list/resume/delete flows, tmux dry-run, and host tmux sidebar use.

## Troubleshooting

### `codex: command not found` after pressing Enter

Restart the sidebar after updating this tool. The current sidebar process may still
be using old code. Also verify:

```bash
agentic-sessions resume <id> --print-command
```

It should print an absolute Codex path when Codex is installed in `~/.local/bin`.
If `CODEX_BIN` points at QGenie, it should print `qgenie resume <id>`, not
`qgenie codex resume <id>`.
If not, set:

```bash
export CODEX_BIN=/absolute/path/to/codex
```

For Claude sessions, use:

```bash
agentic-sessions --provider claude resume <id> --print-command
export CLAUDE_BIN=/absolute/path/to/claude
```

### Sidebar opens but arrows feel slow

Use the latest version of this tool. The sidebar should cache sessions and move
without reparsing JSONL on every keypress. Press `R` to refresh manually.

### Sidebar creates a new window inside tmux

Use the latest version. Inside tmux, `agentic-sessions tmux` should split the current
window, not create a new window.

### I am stuck at Codex's working-directory prompt

Move to the right pane with your tmux prefix + arrow key, or restart with the latest
tool version. Current versions automatically focus the right pane after `Enter`.

### Session list is missing expected sessions

Check detected paths:

```bash
agentic-sessions paths
```

Then override if needed:

```bash
agentic-sessions --sessions-root /path/to/sessions list -n 20
agentic-sessions --provider claude --sessions-root /path/to/claude/projects list -n 20
```

## Sharing With Teammates

Share the directory or archive it, then install or run directly:

```bash
tar -czf agentic-session-tools.tar.gz agentic-session-tools
./install.sh --aliases
./bin/agentic-sessions tmux
```

## Uninstall

If installed to `~/.local/bin`:

```bash
rm -f ~/.local/bin/agentic-sessions
rm -f ~/.local/bin/codex-sessions
```

If aliases were added, remove this block from your shell rc file:

```bash
# agentic-session-tools aliases
alias ags='.../agentic-sessions '
alias cs='.../agentic-sessions '
alias cxs='.../codex-sessions '
```

Sidecar metadata is not removed automatically. To remove it:

```bash
rm -rf ~/.codex/session-tools
rm -rf ~/.claude/session-tools
```

Review the trash folder before deleting it if you used `delete`.

## License

Licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE).

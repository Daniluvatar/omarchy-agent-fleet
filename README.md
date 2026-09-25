# Omarchy Agent Fleet

An Omarchy shell plugin that puts your AI coding subscription allowance in the
bar — one widget, one row per agent, percentage used visible at a glance.

**Status: Phase 1 scaffold (Task 1 complete, stopped at checkpoint 1).**
Nothing renders yet beyond a placeholder. See [Phase 1 scope](#phase-1-scope).

Plugin id: `io.github.daniluvatar.agent-fleet` · Kind: `bar-widget` ·
License: [MIT](LICENSE) · Author: Daniluvatar

## Why

The first-party Agents widget already knows your Codex limits, but its bar slot
is a single static glyph (`󱚣`) — every number lives inside the popup, and the
only at-a-glance signal is a colour change that stays silent below 90 % used.
Agent Fleet exists to answer "how much allowance do I have left" without
clicking anything.

## What it is

Omarchy Agent Fleet is an Omarchy plugin intended to observe AI usage across
multiple named agents and models, eventually resolving to:

```text
Provider / Subscription
└── Harness
    └── Agent
        └── Model
```

## Phase 1 scope

Phase 1 proves the foundation with **Codex only**:

- installs as a third-party/local plugin,
- shows a bar widget and opens a panel,
- reads the Codex subscription limits already produced locally by
  `omarchy-agent-usage-codex --limits-only`,
- displays tier, 5-hour percent used, 5-hour reset, weekly percent used, weekly
  reset,
- degrades gracefully when Codex is unavailable or unauthenticated,
- stores no prompts, responses, credentials or OAuth tokens.

Explicitly **not** in Phase 1: Hermes parsing, agent/model attribution, history,
SQLite, charts, burn-rate, configuration screens, daemons, network services, and
any other provider (Claude, Grok, opencode, local models). Those are Phase 2+
ideas and are listed so nobody implements them by accident.

## Layout

```text
omarchy-agent-fleet/
├── manifest.json             Omarchy plugin manifest (schemaVersion 1)
├── Panel.qml                 bar widget + popup (entryPoints.barWidget)
├── scripts/                  agent-fleet-codex arrives in Task 3
├── tests/fixtures/           collector fixtures arrive with Task 3
└── docs/
    ├── phase-1-playbook.md   the ticket this repository implements
    └── reference-notes.md    verified local Omarchy findings (Task 1 deliverable)
```

## Development

Requires Omarchy `4.x` (`omarchy --version`) and `jq`.

Validate the manifest at any time:

```bash
omarchy plugin validate .
```

`omarchy plugin add` accepts a git url only, and the validator refuses symlinked
plugin folders, so the local loop is copy-then-enable:

```bash
# 1. make the checkout available to the plugin directory
cp -r . ~/.config/omarchy/plugins/io.github.daniluvatar.agent-fleet
# 2. enable it (adds it to the bar layout in ~/.config/omarchy/shell.json)
omarchy plugin enable io.github.daniluvatar.agent-fleet
# 3. undo
omarchy plugin disable io.github.daniluvatar.agent-fleet
omarchy plugin remove io.github.daniluvatar.agent-fleet
```

Nothing in this repository writes to `/usr/share/omarchy`, `/usr/bin`, or your
`~/.config/omarchy/shell.json` by itself; enabling the plugin is a deliberate
step you run.

The collector can be run on its own once it exists:

```bash
omarchy-agent-usage-codex --limits-only | jq '{tierLabel, limits}'   # first-party source
./scripts/agent-fleet-codex | jq .                                   # Task 3 onwards
```

## Privacy

Phase 1:

- does not collect prompts,
- does not collect assistant responses,
- does not read OAuth tokens or credential files,
- does not require an OpenAI API key,
- does not add network calls of its own — it reads the output of the existing
  authenticated local Codex/Omarchy integration,
- prints only normalised usage numbers to stdout; diagnostics to stderr never
  include tokens.

## References

- `docs/reference-notes.md` — everything verified locally about manifest format,
  directory layout, entry points, `Process`/timer patterns and the Codex record.
- `/usr/share/omarchy/shell/plugins/README.md` — first-party plugin contract.
- `/usr/share/omarchy/bin/omarchy-plugin-validate` — the schema the shell
  enforces.

Unofficial. Not affiliated with Omarchy, OpenAI, or Codex.

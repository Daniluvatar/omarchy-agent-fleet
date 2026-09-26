# Omarchy Agent Fleet

An Omarchy shell plugin that puts your AI coding subscription allowance in the
bar — one widget, one number visible at a glance, full details one click away.

**Status: Phase 1 complete.** Codex subscription limit display is implemented
end-to-end (bar slot + panel + local collector + tests) and runs live against
the author's Omarchy install. See [Phase 1 capability](#phase-1-capability) for
exactly what works today.

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

That hierarchy is the long-term goal only. **None of it is implemented yet.**
Phase 1 ships the first building block: the plugin foundation, and a faithful
read of the one subscription that is already available locally — Codex.

## Phase 1 capability

Phase 1 supports **Codex subscription limit display only**:

- Installs as a third-party/local Omarchy `bar-widget` plugin
  (`io.github.daniluvatar.agent-fleet`), enabled via `omarchy plugin enable`.
- Shows a **bar slot** with the fullest window currently reported
  (`Codex 100%`), tinted urgent while the 5-hour session window is at ≥ 80 %;
  falls back to the `Agent Fleet` label when no window has a value.
- Opens a **panel** (click/left button) showing:
  - the **subscription tier** (`Codex · Plus plan`);
  - the **5-hour window**: percent **used** and a reset countdown;
  - the **weekly** window: percent **used** and a reset countdown;
  - a manual **Refresh** action, `R` refresh, `Tab` switch panel, `Esc` close;
  - the auto-refresh cadence in the footer.
- Refreshes conservatively: one refresh on activation, then on a timer with a
  15-minute default (`refreshIntervalSec`, manifest range 60–3600), collapsing
  refreshes that arrive while one is already running, plus a 30-second watchdog
  so the panel never wedges on "loading".
- **Null windows are graceful:** a window the collector leaves unmeasured
  renders as `—`; a record with no windows at all renders a `no window data`
  summary. The panel stays responsive throughout.
- **Exactly one unavailable state:** if the collector is missing, crashes, or
  reports an error, the panel shows a single `Usage unavailable — authenticate
  Codex and try again` line. No raw upstream text, exceptions, or diagnostics
  are ever shown in the UI.
- Right-click the bar slot to force a refresh.

**Explicitly not in Phase 1** (roadmap below): Hermes parsing, agent/model
attribution, history, SQLite, charts, burn-rate, configuration screens,
daemons, network services, and any other provider (Claude, Grok, opencode,
local models). Those are Phase 2+ ideas and are listed here so nobody
implements them by accident.

## How the local collector works (high level)

Three layers, smallest integration first:

```text
Panel.qml + CodexUsage.qml (Ui, QML)
        │  one JSON record on stdout
scripts/agent-fleet-codex (local CLI, Python 3, stdlib only)
        │  one subprocess call, no shell
/usr/bin/omarchy-agent-usage-codex --limits-only (Omarchy, first-party)
        │
existing authenticated local Codex integration
```

- `scripts/agent-fleet-codex` is a **bare local command** (no test hooks, no
  environment injection). It runs the first-party
  `omarchy-agent-usage-codex --limits-only` with a timeout, and transforms
  that output into the plugin's stable internal record (schemaVersion 1,
  `provider: codex`):

  ```json
  {
    "schemaVersion": 1,
    "provider": "codex",
    "available": true,
    "tier": "plus",
    "limits": {
      "session": { "label": "5h window",
                   "usedPercent": 0.0,
                   "resetsAt": "2026-09-26T20:43:58+00:00" },
      "weekly":  { "label": "Weekly (7-day)",
                   "usedPercent": 100.0,
                   "resetsAt": "2026-09-26T18:40:25+00:00" }
    },
    "error": null
  }
  ```

- The upstream collector emits `percent` as a fraction of 1 (`0.03` = 3 %,
  `1.0` = 100 %); the local command normalises it to `usedPercent` (0–100) and
  picks the `session` vs `weekly` window by semantic label (with array order
  as a fallback), preserving `resetsAt`. The UI displays `usedPercent` as-is.
- On failure — collector missing, upstream crash, unauthenticated Codex,
  malformed JSON, or a wedged run — the record is still valid
  (`available: false`, `limits` null, structured `error`), or the UI settles
  into its single unavailable state. Diagnostics go to stderr; secrets never do.
- The QML side (`CodexUsage.qml`) runs that one command via Quickshell
  `Process`, parses the record, and exposes state + slots to both the bar slot
  and the panel, so the two faces can never disagree. Nothing in the UI knows
  how Codex is authenticated.

## Privacy & security

Phase 1:

- does **not** collect prompts or assistant responses;
- does **not** read OAuth tokens or credential files (`~/.codex/auth.json` is
  never opened by this repository);
- does **not** require an OpenAI API key and never touches OpenAI billing;
- adds **no network calls of its own** — it reads the output of the existing
  authenticated local Codex/Omarchy integration, which remains the owner of
  auth;
- the collector is a single local subprocess with a timeout: no file writes,
  no sockets, no credentials in arguments;
- prints only normalised usage numbers to stdout;
- the UI never renders raw upstream text, stack traces, or diagnostics — the
  failure surface is one human-readable unavailable state;
- the repository and the live plugin directory both store no prompt, response,
  token, or message content (usage numbers and timestamps only).

## Layout

```text
omarchy-agent-fleet/
├── manifest.json             Omarchy plugin manifest (schemaVersion 1, bar-widget)
├── Panel.qml                 bar widget + panel (entryPoints.barWidget)
├── CodexUsage.qml            shared data source: runs the collector, one record
├── scripts/
│   └── agent-fleet-codex     local collector CLI (Python 3, stdlib only)
├── tests/
│   ├── test_agent_fleet_codex.py
│   └── fixtures/             codex-normal / codex-unavailable / codex-malformed
├── docs/
│   ├── phase-1-playbook.md   the ticket this repository implements
│   └── reference-notes.md    verified local Omarchy findings
├── LICENSE                   MIT
└── README.md
```

## Installation & development (verified on this system)

Verified against Omarchy **4.0.4-1** (`omarchy version`), Python **3.14.7**,
`jq` **1.8.2**, on Hyprland.

```bash
omarchy version                              # 4.x required
omarchy plugin validate .                    # passes on the real directory

# enable: adds the widget to ~/.config/omarchy/shell.json and the bar
omarchy plugin enable io.github.daniluvatar.agent-fleet

# disable / remove
omarchy plugin disable io.github.daniluvatar.agent-fleet
omarchy plugin remove io.github.daniluvatar.agent-fleet

# tests (offline, stdlib only)
python3 -m unittest discover -s tests -p 'test_*.py'

# collector, standalone
./scripts/agent-fleet-codex | jq .            # plugin's record
omarchy-agent-usage-codex --limits-only | jq .  # upstream source

# after QML edits
omarchy restart shell                        # reloads the plugin
journalctl -t omarchy-shell --since '1 min ago'   # shell log
```

Dev-loop note: `omarchy plugin add` takes a **git url only**, and the validator
refuses a symlinked plugin *path* — but the shell's plugin loader follows
symlinks fine. The live setup on this machine is exactly that:
`~/.config/omarchy/plugins/io.github.daniluvatar.agent-fleet` is a symlink to
this repository, enabled once, so edits here are live after a shell (re)start.
If `omarchy plugin validate` must pass for a published install, copy a real
directory into the plugins path instead (the validator rejects the symlink but
not the contents).

Nothing in this repository writes to `/usr/share/omarchy`, `/usr/bin`, or any
system file; the only user-config change is the deliberate
`omarchy plugin enable` step.

## Known limitations

- **Codex only.** No other provider, no per-agent attribution — that is the
  roadmap below, intentionally unimplemented.
- The `showPercentInBar` manifest setting is declared for the settings UI but
  does not change the bar yet (the bar always shows the fullest window).
- The panel labels are fixed (`5-HOUR WINDOW`, `WEEKLY`); window labels
  `session`/`weekly` are mapped from upstream label text, not from a stable
  key — a future upstream relabel could change the mapping.
- Percent values come from the existing Codex subscription integration; they
  are *allowance* numbers, not token counts, and there is no local
  cross-check.
- The first-party collector's `--limits-only` still touches its own cache/state
  under `~/.local/state/omarchy/agents/usage/` — that is Omarchy-owned
  behaviour we rely on, not something we write ourselves.

## Future direction (roadmap, not implemented)

Phase 2+ ideas, recorded so they are explicitly out of scope today:

- Hermes agent discovery (Engineer / Oracle / Tester, etc.);
- agent/model attribution under `Provider → Harness → Agent → Model`;
- historical allowance snapshots and a local history store;
- other harnesses such as OpenClaw and Pi;
- additional providers (Claude, Grok, opencode, local models);
- burn-rate analytics, forecasting, charts, export/reporting.

## References

- `docs/reference-notes.md` — everything verified locally about manifest format,
  directory layout, entry points, `Process`/timer patterns and the Codex record.
- `/usr/share/omarchy/shell/plugins/README.md` — first-party plugin contract.
- `/usr/share/omarchy/bin/omarchy-plugin-validate` — the schema the shell
  enforces.

Unofficial. Not affiliated with Omarchy, OpenAI, or Codex.

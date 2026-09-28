# Omarchy Agent Fleet

An Omarchy shell plugin that puts your AI coding subscription allowance in the
bar — one number visible at a glance, full details one click away — and, since
Phase 2, shows what your Hermes bots have actually been doing next to it.

**Status: Phase 2 complete.** Codex subscription allowance display (Phase 1) and
Hermes activity display (Phase 2) are implemented end-to-end — bar slot + panel
+ two local collectors + offline tests — and run live against the author's
Omarchy install. Allowance *attribution* (which bot used how much of the
subscription) is **not** implemented; see [Phase 3](#future-direction-roadmap).

Plugin id: `io.github.daniluvatar.agent-fleet` · Kind: `bar-widget` ·
License: [MIT](LICENSE) · Author: Daniluvatar

## Why

The first-party Agents widget already knows your Codex limits, but its bar slot
is a single static glyph (`󱚣`) — every number lives inside the popup, and the
only at-a-glance signal is a colour change that stays silent below 90 % used.
Agent Fleet exists to answer "how much of my allowance have I used?" at a
 glance, without clicking anything — and, with the fleet of Hermes bots on this
machine, "who has been burning it?" one step away from being answerable.

## What it is

Omarchy Agent Fleet is an Omarchy plugin that observes AI usage across
providers, harnesses, agents and models, resolving to this hierarchy:

```text
Provider / Subscription
└── Harness
    └── Agent
        └── Model
```

Concretely, on this machine:

```text
Codex Plus                      ← Provider / subscription  (Phase 1: allowance shown)
└── Hermes                      ← Harness                  (Phase 2: activity shown)
    ├── Engineer                ← Agent / profile          (Phase 2: activity shown)
    │   └── GPT-6 Sol
    ├── Oracle
    │   ├── GPT-6 Sol
    │   └── GPT-6 Astra
    ├── Publisher
    │   ├── GPT-6 Sol
    │   └── GPT-6 Luna
    └── Tester
        └── GPT-6 Luna
```

**Both sides of the hierarchy now carry live data; the edge between them does
not.** Allowance is read at the *provider/subscription* level (first-party
Omarchy integration); activity is read at the *agent* and *model* levels (each
Hermes profile's local state database). Nothing yet links a Hermes agent's calls
to a percentage of the Codex allowance, and no part of the UI implies it. A
Hermes agent that has no Codex activity (or runs entirely on other providers)
can coexist with a nearly-exhausted Codex allowance, and the panel will show
both numbers without reconciling them — by design, until Phase 3.

## Three different numbers — do not read one as another

| Concept | What it is | Where it comes from | Status |
|---|---|---|---|
| **Codex allowance** | Percent of the 5-hour and weekly subscription windows *used*, plus reset countdowns | first-party `omarchy-agent-usage-codex --limits-only` (authenticated local Codex integration) | **implemented (Phase 1)** |
| **Hermes activity** | Counts of successful Codex-backed model calls per Hermes agent/model in the last 7 days (calls, input/output/cache tokens, last activity) | each profile's `state.db`, read-only | **implemented (Phase 2)** |
| **Allowance attribution** | How much of the Codex allowance a given agent/model consumed | requires correlating allowance snapshots with activity intervals | **not implemented (Phase 3)** |

The two live numbers are **not two views of the same measurement**. The
allowance percentage is authoritative for the subscription; the Hermes numbers
are activity counts observed locally. They are displayed in the same panel, in
separate sections, and the panel says so out loud:

> Activity counts only — not a share of your Codex allowance.

## Phase 1 capability — Codex allowance

- Installs as a third-party/local Omarchy `bar-widget` plugin
  (`io.github.daniluvatar.agent-fleet`), enabled via `omarchy plugin enable`.
- Shows a **bar slot** with the fullest window currently reported
  (`Codex 100%`), tinted urgent while the 5-hour session window is at ≥ 80 %;
  falls back to the `Agent Fleet` label when no window has a value.
  `showPercentInBar` (manifest setting) turns the number into an icon-only bar.
- Opens a **panel** (click/left button) showing:
  - the **subscription tier** (hero title `Codex`, meta `Plus`);
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
  with Codex and try again` line. No raw upstream text, exceptions, or diagnostics
  are ever shown in the UI.
- Right-click the bar slot to force a refresh (refreshes both sections).

## Phase 2 capability — Hermes activity

- **Source: the per-profile Hermes state database**, not the free-form logs.
  Each Hermes profile keeps a SQLite database at
  `~/.hermes/profiles/<profile>/state.db`; the usage ledger lives in its
  `session_model_usage` table (one row per session + model + provider + task
  bucket), with timing taken from `sessions` (and the last message as a last
  resort). The logs were evaluated and rejected: profile `cloud` has Codex
  usage in its `state.db` and zero matching `API call #N` log lines.
  See [`docs/hermes-reference-notes.md`](docs/hermes-reference-notes.md).
- **Profiles are discovered dynamically** from the directories under
  `~/.hermes/profiles/` — nothing is hard-coded. Display names come from each
  profile's `profile.yaml` title (`oracle` → "TechLead"), falling back to the
  directory name, which stays the stable identity (`diana` has no `profile.yaml`
  at all on this machine and displays as `diana`); the title itself lives under
  `ui_meta.hermes-bots.title`.
- **What counts as activity:** successful calls with
  `billing_provider = 'openai-codex'`. Failed calls never reach
  `session_model_usage` (they have no usage response to record), so only
  completed calls are counted. Every task bucket is included — main turns plus
  `approval`, `background_review`, `title_generation` — because all of it is
  real Codex work. Other providers observed on this machine (`xai-oauth`,
  `github-copilot`, `copilot`, `custom`, `ollama-local`, `auto`, `openai-api`,
  `bedrock`, empty) are excluded in Phase 2.
- **Lookback: 7 days, explicitly bounded.** A record with a known timestamp
  older than `now − 7 days` is dropped; the default matches the Codex weekly
  window and keeps the scan bounded rather than pretending to be a history
  store. A record whose timestamp cannot be determined is *unknown*, so it
  stays in the totals but never moves `lastActivityAt`. Nothing is persisted —
  each refresh re-reads the source. (`--lookback-days` exists for tests/CLI.)
- **Aggregation** is per agent, per agent + model, and overall: `calls`,
  `inputTokens`, `outputTokens`, `cacheReadTokens`, `cacheWriteTokens`,
  `lastActivityAt`, plus `agent.totalCalls`, `summary.totalAgents` (agents with
  activity in the window) and `summary.totalCalls`. Cache counters stay
  separate; no share percentages are computed, ever. `agents[]` comes out in
  stable alphabetical profile order (deterministic output, asserted by tests);
  the panel re-sorts for display.
- **Contract** — `scripts/agent-fleet-hermes` prints exactly one JSON document
  (verified shape, trimmed to one agent; live values on 2026-09-28: 9 profiles
  discovered, 4 active agents, 1,159 calls — these counters move as the bots
  work, and the real `agents[]` lists all nine profiles in alphabetical order):

  ```json
  {
    "schemaVersion": 1,
    "harness": "hermes",
    "available": true,
    "source": { "type": "local", "profilesDiscovered": 9 },
    "agents": [
      {
        "id": "engineer",
        "displayName": "Engineer",
        "models": [
          {
            "provider": "openai-codex",
            "model": "gpt-6-sol",
            "calls": 450,
            "inputTokens": 1119514,
            "outputTokens": 95023,
            "cacheReadTokens": 43064192,
            "cacheWriteTokens": 0,
            "lastActivityAt": "2026-09-28T10:00:34-05:00"
          }
        ],
        "totalCalls": 450,
        "lastActivityAt": "2026-09-28T10:00:34-05:00",
        "error": null
      }
    ],
    "summary": { "totalAgents": 4, "totalCalls": 1159 },
    "error": null
  }
  ```

- **Panel section** `Hermes Activity` (small-caps header, like every panel
  section), below the Codex windows, clearly labelled
  as activity:

  Rendered from the live record on 2026-09-28 (all four active profiles):

  ```text
  Hermes Activity
  Last 7 days · 4 active agents · 1,159 calls

  Engineer
    GPT-6 Sol                      450 calls
    1.1M in · 95K out
  TechLead                                                       363 calls
    GPT-6 Sol                      345 calls
    2.6M in · 188K out
    GPT-6 Astra                     18 calls
    95.9K in · 1.7K out
  Tester
    GPT-6 Luna                     200 calls
    423K in · 36.6K out
  Publisher                                                      146 calls
    GPT-6 Sol                      120 calls
    1M in · 51K out
    GPT-6 Luna                      26 calls
    160K in · 9.4K out

  Activity counts only — not a share of your Codex allowance.
  ```

  Busiest agent first (then display name) — a *display* decision in
  `HermesUsage.qml`; the contract keeps agents in alphabetical profile order.
  Models are sorted busiest first inside an agent;
  an agent's own total only appears when it splits across more than one model
  (Engineer/Tester show one model row each). Profiles with no qualifying
  activity in the window are not rendered. Model ids are prettified for display
  (`gpt-6-sol` → `GPT-6 Sol`); the raw id stays in the contract. Session ids,
  cache counters and task buckets stay in the collector and are not rendered.
- **Graceful Hermes states:** `Checking Hermes activity…` while loading;
  `Hermes activity unavailable` if the collector is missing/crashes/reports
  `available: false` (e.g. no `~/.hermes/profiles`);
  `No Codex activity in the last 7 days` when nothing qualifies; an unreadable
  profile is reported per-profile by the collector and counted in the meta line
  (`… · 1 unreadable`) without taking the other profiles down. Hermes rows
  never feed the bar percentage, the window bars, or any attribution.
- **Refresh cadence is shared with Codex** — one `refresh()` drives both
  collectors on the same timer, so there is no extra polling. Hermes is a local
  scan (~50 ms measured) and runs under its own 30-second watchdog; a failed
  refetch keeps the last good record instead of blanking the section.

## How the local collectors work (high level)

Two independent collectors, two records, one panel. No parsing lives in QML.

```text
Panel.qml
├── CodexUsage.qml   (Ui, QML)                 Phase 1 — allowance
│       │  one JSON record on stdout
│   scripts/agent-fleet-codex (local CLI, Python 3, stdlib only)
│       │  one subprocess call, no shell
│   /usr/bin/omarchy-agent-usage-codex --limits-only (Omarchy, first-party)
│       │
│   existing authenticated local Codex integration
│
└── HermesUsage.qml  (Ui, QML)                 Phase 2 — activity
        │  one JSON record on stdout
    scripts/agent-fleet-hermes (local CLI, Python 3, stdlib only)
        │  sqlite3 URI "file:…/state.db?mode=ro", one query per profile
    ~/.hermes/profiles/<profile>/state.db      (Hermes-owned, read-only)
```

- `scripts/agent-fleet-codex` runs the first-party
  `omarchy-agent-usage-codex --limits-only` with a timeout and transforms that
  output into the plugin's stable internal record (schemaVersion 1,
  `provider: codex`). Upstream emits `percent` as a fraction of 1 (`0.03` = 3 %);
  the command normalises it to `usedPercent` (0–100) and picks `session` vs
  `weekly` by semantic label (array order as fallback), preserving `resetsAt`.
  On failure the record is still valid (`available: false`, `limits` null,
  structured `error`), or the UI settles into its single unavailable state.
- `scripts/agent-fleet-hermes` opens each profile DB with
  `file:…?mode=ro`, selects only `billing_provider = 'openai-codex'` rows from
  `session_model_usage` joined to `sessions` (and the last-message timestamp as
  fallback), normalizes them (missing numerics → `0`, never invented
  timestamps), applies the 7-day lookback, aggregates by agent and by agent +
  model, and prints the summary contract above. Thousands of raw events are
  never handed to QML. Diagnostics go to stderr; a crash still prints a
  parseable `available: false` record.
- The two QML components each run one command via Quickshell `Process`, parse
  their own record, and expose state + display-ready rows, so the bar and panel
  can never disagree and nothing in the UI knows how Codex is authenticated or
  where Hermes keeps its data.

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
  failure surface is one human-readable unavailable state.

Phase 2 adds Hermes activity, and holds the same line:

- **no prompt text, no assistant responses, no message bodies.** The collector
  reads aggregate usage rows only. `messages` is touched for
  `MAX(timestamp)` and its `content` column is never selected;
- **no OAuth tokens, no API keys, no Hermes configuration, no credentials** —
  nothing in this repository opens `auth.json`, a keyring, a `.env`, or
  `~/.hermes/**/profile.yaml` for anything but the optional display title;
- **Hermes files are never modified.** Opens are strictly `mode=ro`; verified
  locally that a scan creates no files and leaves `state.db` and
  `state.db-wal` unchanged (mtime + checksum) — including a controlled run on a
  copied profile tree where even the `-shm` WAL index is left untouched, while
  the `-shm` mtimes on a live tree move on Hermes' own cycle with no scan
  running (see
  [`docs/hermes-reference-notes.md`](docs/hermes-reference-notes.md) §9);
- **no persistent activity database or cache** — no history store, no snapshot
  files, nothing written anywhere by the plugin; the only state is in memory;
- **no network service, daemon, or additional network call** for Hermes: it is
  a local SQLite read triggered by the existing refresh timer;
- **no allowance attribution is calculated**, in the collector or in the UI;
- per-profile failures are reported as fixed codes with fixed human-readable
  messages (`HERMES_UNAVAILABLE`, `HERMES_PROFILE_UNREADABLE`); paths and
  exception details stay on stderr and are never rendered;
- **test fixtures are synthetic**: `tests/fixtures/hermes-profiles/*/state.db`
  contains generated rows only, its `messages` table has no content column at
  all, and it is regenerable with `tests/make_hermes_fixtures.py`. No real
  prompt, response, session, token, or key material is committed.

## Layout

```text
omarchy-agent-fleet/
├── manifest.json             Omarchy plugin manifest (schemaVersion 1, bar-widget)
├── Panel.qml                 bar widget + panel (entryPoints.barWidget)
├── CodexUsage.qml            Phase 1 data source: allowance record from agent-fleet-codex
├── HermesUsage.qml           Phase 2 data source: activity record from agent-fleet-hermes
├── scripts/
│   ├── agent-fleet-codex     Codex allowance collector (Python 3, stdlib only)
│   └── agent-fleet-hermes    Hermes activity collector (Python 3, stdlib + sqlite3)
├── tests/
│   ├── test_agent_fleet_codex.py
│   ├── test_agent_fleet_hermes.py
│   ├── make_hermes_fixtures.py        regenerates the synthetic Hermes DBs
│   └── fixtures/
│       ├── codex-normal.json / codex-unavailable.json / codex-malformed.json
│       └── hermes-profiles/           synthetic multi-profile state.db tree (sanitized)
├── docs/
│   ├── phase-1-playbook.md            the Phase 1 ticket
│   ├── omarchy-agent-fleet-phase-2.md the Phase 2 ticket
│   ├── reference-notes.md             verified local Omarchy/Codex findings
│   └── hermes-reference-notes.md      verified local Hermes source findings
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

# tests (offline, stdlib only, no Hermes or Codex required)
python3 -m unittest discover -s tests -p 'test_*.py'

# collectors, standalone
./scripts/agent-fleet-codex  | jq .          # allowance record
./scripts/agent-fleet-hermes | jq .          # activity record (7-day window)
omarchy-agent-usage-codex --limits-only | jq .  # upstream allowance source

# Hermes collector, pointed somewhere else / different window (dev only)
./scripts/agent-fleet-hermes --root tests/fixtures/hermes-profiles --lookback-days 30 | jq .

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
system file, and nothing writes into `~/.hermes`; the only user-config change is
the deliberate `omarchy plugin enable` step.

## Testing (offline, deterministic, no live state)

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
```

64 tests (27 Codex, 37 Hermes), all offline, stdlib only; nothing reads the live
`~/.hermes` tree, the Codex integration, or the network. Hermes tests run
against a synthetic profile tree in `tests/fixtures/hermes-profiles/`
(engineer / oracle / scribe / diana), regenerable with
`tests/make_hermes_fixtures.py`; `diana` deliberately exercises the identity
fallbacks (empty `profile.yaml`, no `title:`), and the fixture `messages` table
has no `content` column at all, so a test could not read a message body even if
someone tried.

**Codex collector:** contract shape and one-JSON-document stdout; fraction →
percent mapping (`0.03` → `3.0`, `1.0` → `100.0`) with `0.0` kept as a real
value; tier normalization; windows identified by semantic label with positional
fallback; duplicate/junk entries; reset passthrough; and the failure set —
unavailable, malformed, empty, JSON-array, missing / failing / blank upstream
command, missing input file — each still exit 0 with valid JSON, and error
records proven not to leak upstream text.

**Hermes collector:** contract shape (activity-only fields, no allowance math);
aggregation folding with no per-call fabrication; model ordering; zero-call
rows; multi-agent / multi-model separation; last-activity semantics (max known,
`null` never moves it, message timestamp as last resort); summary totals with
zero-activity profiles present but uncounted; the provider filter (only
`openai-codex`, non-Codex models never surface); task buckets kept internally
but never leaked into the contract; epoch-not-ISO internal timestamps; display
identity fallbacks; the 7-day default, cutoff boundary inclusion, unknown
timestamps surviving any window, and lookback never dropping profiles;
failure modes (missing root → unavailable, empty root → available but quiet,
corrupt DB isolated per profile, profile without `state.db` reported not fatal);
unit helpers; and determinism (same input → same output).

## Known limitations

- **Activity, not attribution.** Hermes numbers and Codex allowance numbers are
  not correlated. Any statement of the form "Engineer used 31 % of the weekly
  allowance" would be false and is deliberately impossible in this codebase.
- **The Hermes DB format is an internal implementation detail** of Hermes with
  no public contract; a Hermes update can rename tables or columns. The parser
  fails soft (per-profile error, or `available: false`) rather than crashing,
  and tests run against fixtures, never against the live DB.
- **Call counts include auxiliary work.** `approval`, `background_review` and
  `title_generation` buckets are summed with main turns, so "450 calls" is not
  "450 conversations". They are real Codex calls, which is why they are counted.
- **Timestamps are per session, not per call.** `session_model_usage.first_seen`
  /`last_seen` are `0` in practice, so timing comes from
  `sessions.last_activity_at`/`started_at` (then the last message), and rows
  whose time cannot be determined stay in the totals with a `null` timestamp —
  the 7-day lookback cannot exclude them and `lastActivityAt` ignores them.
- **Only `openai-codex` Hermes activity is shown**; activity through other
  Hermes providers is real but deliberately out of the Phase 2 contract.
- Quiet profiles (no qualifying activity in the window) are in the contract but
  not rendered; unreadable ones are summarized as a count, not listed.
- **Codex-only allowance.** Panel window labels are fixed
  (`5-HOUR WINDOW`, `WEEKLY`); `session`/`weekly` are mapped from upstream
  label text, not a stable key, so a future upstream relabel could change the
  mapping. Percentages come from the Codex subscription integration — they are
  allowance numbers, not token counts, with no local cross-check.
- **The Codex allowance can be intermittently unavailable.** The first-party
  integration sometimes answers `limits: []` / `"Codex limits unavailable"`
  (seen repeatedly on 2026-09-28, recovering on the next refresh). The
  collector maps that to the documented unavailable state instead of guessing,
  and — unlike Hermes — the Codex section does not hold a last-good record
  across a failed refresh. Holding the last-good allowance with a staleness
  marker is a Phase 3-sized change, not a Phase 2 bug.
- The first-party collector's `--limits-only` touches its own cache/state under
  `~/.local/state/omarchy/agents/usage/` — Omarchy-owned behaviour we rely on,
  not something we write ourselves.
- No history, charts, burn-rate, per-session drill-down, or configuration UI.

## Future direction (roadmap, not implemented)

- **Phase 3 — allowance attribution:** Codex allowance snapshots + Hermes
  activity intervals → observed/estimated agent + model contribution, keeping
  directly observed deltas separate from estimated allocations and recording
  ambiguity when several agents/models are active in one interval.
- Hermes activity from additional providers (Claude, Grok, Copilot, local), and
  other harnesses such as OpenClaw and Pi.
- Historical allowance snapshots and a local history store; burn-rate
  analytics, forecasting, charts, export/reporting.
- Cross-machine sync.

## References

- `docs/hermes-reference-notes.md` — the verified Hermes source: paths, schema,
  field mapping, rotation, risks, read-only side effects.
- `docs/omarchy-agent-fleet-phase-2.md` — the Phase 2 ticket (contract, tasks,
  validation checklist).
- `docs/reference-notes.md` — everything verified locally about manifest format,
  directory layout, entry points, `Process`/timer patterns and the Codex record.
- `docs/phase-1-playbook.md` — the Phase 1 ticket.
- `/usr/share/omarchy/shell/plugins/README.md` — first-party plugin contract.
- `/usr/share/omarchy/bin/omarchy-plugin-validate` — the schema the shell
  enforces.

Unofficial. Not affiliated with Omarchy, OpenAI, Codex, or Hermes.

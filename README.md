# Omarchy Agent Fleet

An Omarchy shell plugin that puts your AI coding subscription allowance in the
bar — one number visible at a glance, full details one click away — shows what
your Hermes bots have actually been doing next to it (Phase 2), and since
Phase 3 infers — clearly labeled, never as billing — which agent and model the
observed Codex allowance movement most plausibly belongs to.

**Status: Phase 3 complete, live-tested on this system.** Codex subscription
allowance display (Phase 1) and Hermes activity display (Phase 2) are
implemented end-to-end — bar slot + panel + two local collectors + offline
tests — and run live against the author's Omarchy install. Phase 3 adds a
user-only observation store and a chain of four pure, offline CLI stages that
turn observed Codex allowance *movement* into per-agent / per-model *inferred
attribution*, with an explicit unattributed remainder and a coverage figure
that says exactly what it is and is not. The attribution numbers are
correlation from local observability — **not provider-reported per-agent
billing data**, not a share of the subscription, and not a confidence score.
See the [Phase 3](#phase-3--allowance-attribution-inferred-not-provider-reported) section
for the full rules.

Plugin id: `io.github.daniluvatar.agent-fleet` · Kind: `bar-widget` ·
License: [MIT](LICENSE) · Author: Daniluvatar

## Why

The first-party Agents widget already knows your Codex limits, but its bar slot
is a single static glyph (`󱚣`) — every number lives inside the popup, and the
only at-a-glance signal is a colour change that stays silent below 90 % used.
Agent Fleet exists to answer "how much of my allowance have I used?" at a
 glance, without clicking anything — and, with the fleet of Hermes bots on this
machine, "who has been burning it?" one click away, answered as *inferred*
attribution (never as billing — see the Phase 3 section).

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

**Both sides of the hierarchy now carry live data; the edge between them is
an *inference*, labeled as such — not a measurement.** Allowance is read at
the *provider/subscription* level (first-party Omarchy integration); activity
is read at the *agent* and *model* levels (each Hermes profile's local state
database). Phase 3 deliberately links the two, and only as inference: the
*weekly observed allowance movement* is attributed to the `agent + model`
identities that local evidence can tie to it — and movement that cannot be
tied to anything stays unattributed, explicitly, never scaled, never
invented. A Hermes agent with no Codex activity (or running entirely on other
providers) may coexist with a nearly-exhausted Codex allowance, and the panel
shows both — with the shortfall sitting in *Unattributed*, not assigned by
guess.

## Three different numbers — do not read one as another

| Concept | What it is | Where it comes from | Status |
|---|---|---|---|
| **Codex allowance** | Percent of the 5-hour and weekly subscription windows *used*, plus reset countdowns | first-party `omarchy-agent-usage-codex --limits-only` (authenticated local Codex integration) | **implemented (Phase 1)** |
| **Hermes activity** | Counts of successful Codex-backed model calls per Hermes agent/model in the last 7 days (calls, input/output/cache tokens, last activity) | each profile's `state.db`, read-only | **implemented (Phase 2)** |
| **Allowance attribution** | Which `agent + model` the *observed* weekly Codex allowance movement is inferred to belong to (in pp of that movement) | inference: allowance observation store × local activity intervals | **implemented as inference (Phase 3)** |

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
- Right-click the bar slot to force a refresh (refreshes all sections, and arms
  at most one snapshot).

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
  never feed the bar percentage or the window bars; in Phase 3 they feed only
  the *inferred* Weekly Attribution section, as correlation.
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
- **no persistent activity database or cache** — no history store, no live
  tree writes; the only state is in memory. (Phase 3 adds exactly one
  user-owned observation store — see the Phase 3 section for its path,
  retention, permissions, and what it never contains.)
- **no network service, daemon, or additional network call** for Hermes: it is
  a local SQLite read triggered by the existing refresh timer;
- **no allowance attribution in the Phase 2 collector or UI.** Phase 3 adds
  it as local inference from the observation store — no new network path, no
  new credentials, no billing computation.
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
├── AttributionUsage.qml      Phase 3 data source: runs the intervals→attribution→
│                             aggregate chain read-only for the Attribution section
├── HistoryUsage.qml          Phase 5 data source: strictly read-only `--list` source
│                             for the Recent Segments section (never writes the store)
├── scripts/
│   ├── agent-fleet-codex     Codex allowance collector (Python 3, stdlib only)
│   ├── agent-fleet-hermes    Hermes activity collector (Python 3, stdlib + sqlite3)
│   ├── agent-fleet-snapshot  Phase 3 store writer: one settled observation per refresh wave
│   ├── agent-fleet-intervals Phase 3: observations → interval records (pure)
│   ├── agent-fleet-attribution Phase 3: intervals → attribution records (pure)
│   ├── agent-fleet-aggregate Phase 3: per-window rollup (pure)
│   └── agent-fleet-history   Phase 4 segments store: append on completion, 90-day
│                             retention (write path), and `--list` (strictly read-only)
├── tests/
│   ├── test_agent_fleet_codex.py
│   ├── test_agent_fleet_hermes.py
│   ├── test_agent_fleet_snapshot.py       Phase 3 store (path/permissions/retention/spacing/privacy)
│   ├── test_agent_fleet_intervals.py      Phase 3 boundary/gap/reset semantics
│   ├── test_agent_fleet_attribution.py    Phase 3 categories + invariants
│   ├── test_agent_fleet_aggregate.py      Phase 3 rollups, pp, coverage
│   ├── test_agent_fleet_failure_recovery.py Phase 3 fail-safe behavior
│   ├── test_agent_fleet_history.py        Phase 4/5 store write contract + read-only `--list`
│   ├── test_agent_fleet_markers.py        Phase 4.5 gap/reset marker display metadata
│   ├── make_hermes_fixtures.py        regenerates the synthetic Hermes DBs
│   └── fixtures/
│       ├── codex-normal.json / codex-unavailable.json / codex-malformed.json
│       └── hermes-profiles/           synthetic multi-profile state.db tree (sanitized)
├── docs/
│   ├── phase-1-playbook.md            the Phase 1 ticket
│   ├── omarchy-agent-fleet-phase-2.md the Phase 2 ticket
│   ├── phase-3-attribution-notes.md   Phase 3 discovery notes (source-of-truth decision, verified commands)
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

192 tests — 27 Codex, 37 Hermes, 26 snapshot, 24 intervals, 17 attribution,
19 aggregate, 1 failure-recovery, 27 history (Phase 4 store + the Phase 5
`--list` read-only contract), 14 markers (Phase 4.5 gap/reset display
metadata) — all offline, stdlib only; nothing reads
the live `~/.hermes` tree, the Codex integration, or the network. Hermes
tests run
against a synthetic profile tree in `tests/fixtures/hermes-profiles/`
(engineer / oracle / scribe / diana), regenerable with
`tests/make_hermes_fixtures.py`; `diana` deliberately exercises the identity
fallbacks (empty `profile.yaml`, no `title:`), and the fixture `messages` table
has no `content` column at all, so a test could not read a message body even if
someone tried. The Phase 3 chain tests always run against a temporary
`$XDG_STATE_HOME`/temp dir store and never touch `~/.local/state`.

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

**Phase 3 attribution chain:** `test_agent_fleet_snapshot.py` (store path /
`XDG_STATE_HOME` fallback, `0700`/`0600` permissions, atomic append + rename,
14-day retention pruning, ~60 s minimum spacing, baseline-only first
observation, and store privacy — no prompt/response content, credentials, raw
log lines, or raw error text: only fixed codes like `CODEX_UNAVAILABLE`);
`test_agent_fleet_intervals.py` (gap and `reset_boundary` semantics, first
observation never yields a delta, a later-lower `usedPercent` or changed
`resetsAt` is a reset, never a negative delta, a reappearing profile with
higher lifetime counters is unknown, not invented);
`test_agent_fleet_attribution.py` (every rule: `gap`, `reset_boundary`,
`no_allowance_delta`, `unattributed` with its three reasons, `observed_single`,
`estimated_shared`; partial observability blocks the whole delta; allocations
weight by `deltaCalls` only; `attributed ≤ observed`; no confidence scores;
weekly and session never mixed);
`test_agent_fleet_aggregate.py` (rollups sum to `attributedPoints`,
unattributed remainder stays unattributed, coverage = attributed/observed or
`null`, never a fabricated 100 %);
`test_agent_fleet_failure_recovery.py` (collector or store failure at any
stage keeps the pipeline and the panel alive — diagnostic only).

## Known limitations

- **Attribution is inference, not billing.** Phase 3 correlates the observed
  allowance movement with local activity counters — but a statement of the form
  "Engineer *used* 31 % of the weekly allowance* as the provider counts it*"
  is still false, and still impossible in this codebase: it is inferred from
  local observability, it is bounded by the observed movement, and everything
  the local evidence cannot tie down stays unattributed.
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
  collector maps that to the documented unavailable state instead of guessing.
  When a refresh settles with a previously confirmed record already on
  screen, the panel now retains that last-good value and flags it stale
  ("Last successful update HH:MM") instead of blanking; with no prior good
  record the section simply shows unavailable. That stale continuity is
  display-only: the Phase 3 snapshot store re-collects fresh on every capture,
  so the same failed refresh is recorded there as `codex.available = false`
  and produces a gap in the interval/attribution chain — the UI is never
  allowed to paper over a break in the data.
- The first-party collector's `--limits-only` touches its own cache/state under
  `~/.local/state/omarchy/agents/usage/` — Omarchy-owned behaviour we rely on,
  not something we write ourselves.
- No history, charts, burn-rate, per-session drill-down, or configuration UI.

## Phase 3 — allowance attribution (inferred, not provider-reported)

> **Read this first:** *Agent Fleet attribution is inferred from observed
> Codex allowance movement and local Hermes activity. It is not a
> provider-reported per-agent billing figure.* The provider reports the
> *shared* Codex subscription allowance; it does not report how each local
> agent split it. Every number in this section is built entirely from local
> signals — the allowance record and the Hermes activity counters — so
> "observed", "estimated" and "unattributed" are never charges, costs, or
> provider accounting. They are labeled in the panel next to the numbers,
> and the code paths are built to keep it that way.

Three conservative integrations. The bar, the two existing data flows, and
the panel's look are unchanged; the new machinery is four pure CLI stages
plus one read-only QML source:

```text
settled refresh wave (900 s timer / manual / panel reopen)
    ├── CodexUsage.refresh()   > agent-fleet-codex   (allowance, pp)
    └── HermesUsage.refresh()  > agent-fleet-hermes  (activity counters)
            │ once the wave has settled, exactly once
            ▼
    agent-fleet-snapshot        fresh collection → append ONE observation
                                $XDG_STATE_HOME/omarchy/agent-fleet/observations.jsonl
            │ everything below here is read-only
            ▼
    agent-fleet-intervals       consecutive observations → interval records
            ▼
    agent-fleet-attribution     per window (weekly | session, independently)
            ▼
    agent-fleet-aggregate       one-window rollup: observed / attributed /
                                unattributed (pp), coverage, agent+model rollups
            ▼
    AttributionUsage.qml        runs the same chain read-only → the
                                "Weekly Attribution" section (render-only)
```

- **Snapshot capture.** Each refresh wave (the 900 s cadence timer, a manual
  refresh, or a panel re-opening — all of them refresh, none of them
  redraw) settles through both collectors; exactly once per wave a
  settled refresh arms `scripts/agent-fleet-snapshot`, which does its own
  fresh collection and appends one observation to
  `~/.local/state/omarchy/agent-fleet/observations.jsonl`
  (`$XDG_STATE_HOME/omarchy/agent-fleet/observations.jsonl`). The store is
  user-only: `0700` directory / `0600` file, atomic write (temp file +
  `fsync` + rename), 14-day retention pruned on every write, and a ~60 s
  minimum spacing enforced inside the store. A failed or duplicate capture is
  diagnostic only and never disturbs the panel or the collector records.
  Each observation is ~3 KB (the Codex window state plus the cumulative
  `openai-codex` usage counters per profile/model), so the default cadence
  is ≈ 300 KB/day, hard-capped around ≈ 4 MB by the 14-day window. What an
  observation is *never* given: prompts, responses, session ids, task
  buckets, credentials, raw log lines, raw error strings (only fixed codes
  such as `CODEX_UNAVAILABLE`), or raw upstream text.
- **Stale Codex handling** as noted in the known limitations above —
  including that the last-good value is in-memory and per-shell: **after an
  OmniShell restart, a first refresh that fails has no last-good value to
  show (the section is just unavailable until the next success)**. The
  store's view of the same failure is a `codex.available = false`
  observation → a gap in the interval chain, never backfilled.
- **Panel scrolling.** The content was already inside a `Flickable`; this
  adds the same two reachability affordances the first-party agents panel
  uses, so every section stays reachable with a dozen Hermes agents: a
  vertical `ScrollBar` shown when needed, and ArrowUp/ArrowDown, `j`/`k`
  scrolling with the first-party step size and clamping. Scrolling only
  moves the viewport; it never triggers a refresh or a snapshot.
- **Weekly Attribution section (inferred only).** The panel shows a clearly
  separate third section, fed by `AttributionUsage.qml` — a read-only data
  source that runs the repo's own aggregation chain
  (`scripts/agent-fleet-intervals` + `scripts/agent-fleet-attribution` +
  `scripts/agent-fleet-aggregate --window weekly`) against the snapshot
  store. Parsing and aggregation never live in `Panel.qml`; the panel only
  renders. It shows *Observed movement: N pp*, *Coverage: N%*, per-agent
  (and model) *N pp observed · N pp estimated*, and a compact
  *Unattributed: N pp* breakdown by reason. It explains itself
  ("Inferred from Codex allowance changes and local Hermes activity") and
  keeps coverage honest: the share of observed movement that could be
  attributed, not a share of the subscription, not a confidence score. The
  agent breakdown is never normalized to 100 percentage points. States:
  *Collecting attribution data…* (no store or no intervals yet),
  *New weekly window — collecting data…* (a reset happened and there are
  still no usable post-reset intervals), *Attribution incomplete — Codex
  observations contain gaps.* (the current weekly segment has gaps; the
  valid attribution is still shown, nothing is inferred across the break).
  It refreshes once per settled wave — never on open/redraw — only reads the
  store, and never arms or creates its own snapshots.
  The session window is attributed by the same engine for CLI consumers
  (`--window session`); the panel displays the weekly section only, and the
  two windows are never mixed into one number.

### Attribution semantics (enforced by `agent-fleet-attribution`)

Per Codex window (weekly and session are operated on independently,
never mixed), over the current reset segment:

1. Codex `gap` (either endpoint unreadable) → `gap`. A gap is displayed as a
   break; it's never bridged, filled, or inferred across. A gap reduces the
   evidence within a segment but doesn't reset the segment.
2. Codex `reset_boundary` (a `resetsAt` move, or a subsequent `usedPercent`
   below the previous one) → `reset_boundary`. That delta is unknown — a new
   segment starts here; any valid intervals from before the reset still count.
3. `ok` with delta ≤ 0 → `no_allowance_delta`. No consumption is inferred —
   an unchanged or lower-allowance delta is never attributed as use, and no
   "zero-provider-cost" inference is made or recorded.
4. `ok` with a positive delta but incomplete Hermes observability (a
   profile unreadable at either endpoint, or any `agent + model` whose
   counter delta is not computable) → the entire delta is `unattributed`
   (`incomplete_hermes_observability`). Partial visibility is never treated
   as complete.
5. `ok`, fully observable, but no Hermes activity in the interval →
   `unattributed (`no_hermes_activity`)`; with only token movement (no
   attributable calls) → `unattributed (`no_callable_activity`)`.
6. `ok`, fully observable, exactly one `agent + model` with an attributable
   delta → `observed_single`: the full observed delta is attributed to that
   identity — *observed correlatively, never as provider billing.*
7. `ok`, fully observable, multiple identities attributable →
   `estimated_shared`: split by weight of **call count only**
   (`delta * calls_i / sum(calls)`); zero-call rows don't take weight;
   input/output/cache token deltas are *never* used as cost weights;
   no model multipliers.

Invariants across all rules: identity is always `agent + model` (never just
agent, never just model); allocations sum back to the observed delta within
float tolerance; `attributed ≤ observed` (never more); unattributed movement
stays unattributed — it's never re-normalized to 100% or absorbed into
someone else; and no numeric confidence score of any kind exists anywhere in
the chain.

### Coverage — what the number is/isn't

The panel shows `Coverage: N%`, defined exactly as
`attributedPoints / observedPoints × 100` over the current segment (or `null`
when there is no observed movement — no fabricated 100%):

- **not** provider-reported usage (the provider reports the total allowance,
  not per-agent usage);
- **not** a confidence score about the underlying activities being real;
- **not** a claim that unattributed movement belongs to "no one" — it belongs
  to *known specific unknowns* (resets, gaps, unobservable identities, or
  Codex activity that never shows up in local Hermes counters);
- **not** a share of the subscription (the denominator is observed movement,
  not the 5-hour or weekly window).

`Coverage: 71%` without this framing is a defect; the panel prints the
definition right next to the number.

### Live verification (Phase 3, on this system)

- 151 offline unit tests (7 modules) pass; `omarchy plugin validate .`
  exits 0; all six CLI scripts were run successfully from a clean worktree;
  `git diff --check` clean (no whitespace errors).
- The installed plugin is a symlink to this repo, so the live shell is
  running exactly this tree. Live session: the panel opens and renders all
  three sections (Codex, Hermes Activity, Weekly Attribution) with zero QML
  errors and no agent-fleet / AttributionUsage crashes in
  `journalctl -t omarchy-shell`; the scroll affordances (Flickable +
  ScrollBar + `j`/`k` / ArrowUp/Down handlers) compile and load, but
  keystroke-driven scrolling was not exercised in the live check (no
  key-injection in the session); the panel's attribution values match what
  `agent-fleet-aggregate --window weekly` reports against the same store.
- Every settled refresh wave appended exactly one observation (no burst on
  redraw); the ~60-second minimum spacing is observable in the file;
  directory/file permissions were `0700`/`0600` throughout;
  a grep of the store lines for prompt content, credentials, and raw error
  text found nothing.
- The intermittent upstream `CODEX_UNAVAILABLE` state behaved as designed:
  the panel kept the last-good value flagging as stale; the store recorded a
  gap; the affected interval's attribution stayed `gap` / coverage-reduced —
  nothing was backfilled.

See `docs/phase-3-attribution-notes.md` for the verification notes
(source-of-truth decisions, verified command shapes, fixture inventory)
that this section summarizes.

## Recent Segments — completed attribution windows (Phase 4/5)

`Panel.qml` also renders a **read-only “Recent Segments” list**: the
**5 most recent completed** attribution segments already persisted in
`segments.jsonl`, **newest first**, with **both windows coexisting**
(`Weekly` and `5-hour`).

- Each row shows the window label, the **persisted time range**
  (e.g. `2026-09-22 → 2026-09-29`, or `08:30 → 13:30`), `observedPoints`,
  `coveragePercent`, and — compact, when non-zero — `unattributedPoints`.
  There is no unbounded expansion, and no raw observations, prompts, IDs,
  or logs (the record schema itself excludes them).
- **Strictly read-only.** The panel data source (`HistoryUsage.qml`) calls
  only `scripts/agent-fleet-history --list`: one JSON document, newest
  first, sorted from the persisted records. That mode **never scans**
  `observations.jsonl`, **never prunes**, **never re-derives**, and
  **never writes** to the segments store. Opening, closing, or refreshing
  the section does not mutate the store; a missing store is a normal
  empty state (“No completed segments yet”), not an error.
- **No read-time retention filter.** The 90-day retention policy still
  applies at write time only, when a completed segment is first persisted
  (Task 2 semantics). Listing never applies retention and never repairs
  or deletes records.
- **No selector coupling.** The `[ Weekly ] [ 5-hour ]` selector chooses
  the *live* attribution summary above; it does not filter the persisted
  segment list — both windows always coexist there.
- The Phase 4.5 gap/reset **markers** (display metadata derived in
  `scripts/agent-fleet-aggregate`, never stored) and the expand/collapse
  of the *live* attribution summary are implemented in the same panel;
  `Coverage: N%` keeps its definition line.
- **Settings (Task 7):** two manifest settings, both presentation-only —
  `defaultAttributionWindow` (`weekly` (default) | `session`) seeds the
  `[ Weekly ] [ 5-hour ]` selector's initial selection; the selector
  itself, expand/collapse, and both cached windows work exactly as
  before. `showRecentSegments` (`true` default | `false`) hides this
  section and its separator (and stops the read-only `--list` process
  running); turning it off never affects the store. Neither setting
  changes attribution math, retention, snapshots, or the history store.
  A configurable row count was deliberately *not* exposed — `5`
  stays a component constant (`HistoryUsage.maxRows`) to keep the
  manifest small; it can gain a setting later without a behavior change.

`tests/test_agent_fleet_history.py` covers the `--list` contract
(ordering, weekly + session coexistence, persisted fidelity,
malformed-line tolerance, byte-for-byte read-only behavior,
single-JSON-document stdout); `tests/test_agent_fleet_markers.py`
covers the marker display metadata.

## Future direction (roadmap, not implemented)

- Hermes activity for additional providers (Claude, Grok, Copilot, local)
  and other harnesses (e.g. OpenClaw, Pi).
- Historical allowance snapshots and burn-rate analytics, forecasting,
  charts, export/reporting on top of the existing completed-segment store.
- Cross-machine sync.

## References

- `docs/hermes-reference-notes.md` — the verified Hermes source: paths, schema,
  field mapping, rotation, risks, read-only side effects.
- `docs/omarchy-agent-fleet-phase-2.md` — the Phase 2 ticket (contract, tasks,
  validation checklist).
- `docs/phase-3-attribution-notes.md` — the Phase 3 discovery notes
  (source-of-truth decision: cumulative counters in `state.db` rather than
  `agent.log`, verified command shapes, fixture inventory).
- `docs/reference-notes.md` — everything verified locally about manifest format,
  directory layout, entry points, `Process`/timer patterns and the Codex record.
- `docs/phase-1-playbook.md` — the Phase 1 ticket.
- `/usr/share/omarchy/shell/plugins/README.md` — first-party plugin contract.
- `/usr/share/omarchy/bin/omarchy-plugin-validate` — the schema the shell
  enforces.

Unofficial. Not affiliated with Omarchy, OpenAI, Codex, or Hermes.

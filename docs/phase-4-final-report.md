# Omarchy Agent Fleet — Phase 4 Final Report

Phase 4 (“Compact completed-segment history UI + UX polish”) on top of
Phase 3 (attribution), Phase 2 (Hermes activity), and Phase 1 (Codex
allowance). This report describes the **actual shipped implementation**,
not the original phase plan.

Commit lineage (this repo, as of this report — commit messages are the
committer’s own; `a58d084` is the gap/reset marker work that this phase
integrates, labeled “phase five” in its message):

```
56b9f8b feat: add recent attribution history and ux settings   <- Phase 4 (Tasks 6+7)
a58d084 feat: add phase five gap and reset markers             <- gap/reset marker work (this phase's marker source)
a815f47 feat: add phase four attribution history and ux        <- earlier Phase 4 tasks (store/CLI)
```

---

## 1. Task status

| # | Task | Status |
|---|------|--------|
| 1 | Codex collector | ✅ (Phase 1, pre-existing) |
| 2 | Hermes collector | ✅ (Phase 2, pre-existing) |
| 3 | Observation snapshot store + `agent-fleet-snapshot` | ✅ (Phase 3, pre-existing) |
| 4 | `agent-fleet-intervals` (pure interval builder) | ✅ (Phase 3, pre-existing) |
| 5 | `agent-fleet-attribution` (pure inference) | ✅ (Phase 3, pre-existing) |
| 6 | `agent-fleet-aggregate` (pure summary + marker display metadata) | ✅ (Phase 3, pre-existing) |
| 7 | Attribution panel UI + expand/collapse | ✅ (Phase 3, pre-existing) |
| 8 | Attribution integration + validation | ✅ (Phase 3, pre-existing) |
| — | Phase 4 Task 1: history store CLI (`--store` write path) | ✅ shipped |
| — | Phase 4 Task 2: retention + identity + first-write-wins semantics | ✅ shipped |
| — | Phase 4 Task 3: `--list` read-only mode | ✅ shipped |
| — | Phase 4 Task 4/5: panel integration wiring + `HistoryUsage.qml` | ✅ shipped |
| — | Phase 4 Task 6: compact 5-row Recent Segments UI + read-only contract | ✅ shipped |
| — | Phase 4 Task 7: settings (`defaultAttributionWindow`, `showRecentSegments`) + discoverability hint | ✅ shipped |
| — | Phase 4 Task 8: this final documentation + validation pass | ✅ shipped (this report) |

Nothing was left half-done: every checklist item from the phase-4
playbook is implemented, tested, documented, or explicitly recorded as a
known limitation (section 19).

## 2. Plugin behavior, current state (all phases combined)

One bar widget + one panel:

- **Bar**: the Codex **weekly percent used** (primary number) and the
  5-hour percent (secondary), each with a simple reset countdown; the bar
  itself is the Phase 1 measurement only.
- **Panel, top**: Codex allowance section (5-hour + weekly, percent,
  reset countdown, unreadable-tile handling).
- **Panel, agents**: every Hermes agent with its models, per-model local
  call/tokens counters, and an expand/collapse per agent (Phase 2).
- **Panel, attribution**: for the selected window `[ Weekly ] [ 5-hour ]`,
  the current reset segment’s summary — observed points, per
  agent/model `observed single`, `estimated shared`, unattributed
  breakdown, coverage — with **gap/reset markers** as display metadata
  and the mandatory `Coverage: N%` definition line. “Observed movement,
  not billing” is always visible.
- **Panel, Recent Segments** (Phase 4): the 5 most recent **completed**
  attribution segments from `segments.jsonl`, both windows coexisting,
  newest first, each showing persisted `startedAt → endedAt`, window
  label, observed points, coverage, and (when non-zero) unattributed
  points. Strictly read-only.
- **Settings** (Phase 4): `defaultAttributionWindow` and
  `showRecentSegments` (section 11).

## 3. What Phase 4 shipped

1. `scripts/agent-fleet-history` — one CLI, two modes:
   - default (store) mode: pure re-derivation of completed segments from
     `observations.jsonl` (reuses the attribution chain read-only),
     **append** of first-seen `(window, resetsAt)` records, **90-day
     retention prune** at write time, atomic + `fsync` write, `0600`
     files in a `0700` directory;
   - `--list` mode: read-only, prints one JSON document of the stored
     records (newest first, both windows), **never** scans observations,
     prunes, re-derives, or writes anything.
2. `HistoryUsage.qml` — the read-only Recent Segments section:
   5-row cap (`maxRows` constant), empty state, `enabled` gate
   (driven by `showRecentSegments`), zero writes by construction.
3. `Panel.qml` — integration: attribution window selector seeded from
   the `defaultAttributionWindow` setting (setting stays bound; first
   click breaks only the selector’s binding so it stays responsive),
   section + separator visibility gated by `showRecentSegments`,
   `Component.onCompleted` enable-gating so a hidden section performs
   zero `--list` runs, and one faint discoverability caption (“Click an
   agent to expand or collapse its models”).
4. `manifest.json` — two new typed settings with defaults matching
   prior behavior (`weekly`, `true`); existing `refreshIntervalSec` /
   `showPercentInBar` untouched.
5. Tests: `tests/test_agent_fleet_history.py` (18 tests: store-mode
   identity/first-write-wins/zero-observed/duplicate/retention
   semantics + 9 list-mode contract tests covering ordering, weekly and
   session coexistence, persisted fidelity, malformed-line tolerance,
   byte-for-byte read-only behavior, single-JSON-document stdout, and
   the normal empty state).
6. README — layout tree synced (all Phase 4 files), Recent Segments
   section, settings documentation, and the attribution disclaimer
   kept verbatim in place (section 4).

## 4. Documentation status

- **README.md** — authoritative current description: “Three different
  numbers” warning, Phase 1/2/3 sections intact, new “Recent Segments”
  section (behavior + read-only contract + settings), updated layout
  tree (includes `HistoryUsage.qml`, `scripts/agent-fleet-history`,
  `tests/test_agent_fleet_history.py`, `tests/test_agent_fleet_markers.py`),
  updated testing + verification sections, “Future direction” with the
  remaining roadmap.
- **docs/omarchy-agent-fleet-phase-4.md** — kept as the phase playback
  document; `docs/phase-4-history-notes.md` keeps working notes;
- **docs/phase-4-final-report.md** — this report (final, actual
  implementation + full audit + validation record).

The attribution disclaimer (Phase 3 baseline) is preserved in the
README in three places: the “Three different numbers” section,
“### Attribution semantics”, and “### Coverage — what the
number is/isn’t” (the “not provider-reported / not a confidence score /
not a claim that unattributed movement belongs to no one / not a share
of the subscription” list, plus the `Coverage: 71%` warning). The
panel UI still prints “Observed movement, not billing” and the
`Coverage: N%` definition line.

## 5. History store — actual record structure

`segments.jsonl` (one compact JSON record per line, `0600` inside a
`0700` `agent-fleet` directory):

```json
{
  "schemaVersion": 1,
  "window": "weekly",
  "resetsAt": "<identity string — the reset that closed the segment>",
  "startedAt": "<iso8601>",
  "endedAt": "<iso8601>",
  "observedPoints": 20.0,
  "attributedPoints": 12.0,
  "unattributedPoints": 8.0,
  "coveragePercent": 60.0,
  "unattributed": {
    "noHermesActivityPoints": 0.0,
    "incompleteHermesObservabilityPoints": 8.0,
    "noCallableActivityPoints": 0.0
  },
  "agents": [
    { "agent": "cloud",
      "totalAttributedPoints": 12.0,
      "models": [
        { "model": "gpt-5.6-terra",
          "observedSinglePoints": 12.0,
          "estimatedSharedPoints": 0.0,
          "totalAttributedPoints": 12.0 }
      ] }
  ]
}
```

Fixed keys, no free-form fields: this schema structurally excludes
prompts, responses, tokens, credentials, raw logs, confidence scores,
and provider multipliers. `startedAt`/`endedAt` are the persisted
segment range (observation timestamps); `resetsAt` is the closing
reset identity. `coveragePercent` is `null` when `observedPoints == 0`
(no fabricated 100%).

## 6. History CLI — exact behavior

`scripts/agent-fleet-history` (default mode), from
`observations.jsonl` (read-only input) to `segments.jsonl`:

- **Reuses the exact attribution pipeline**: loads sibling modules
  `agent-fleet-snapshot` (only the `atomic_write` helper — never a
  collector call), `agent-fleet-intervals`, `agent-fleet-aggregate`
  (which loads `agent-fleet-attribution`) via `importlib` under stable
  spec names; no re-implementation of interval/attribution logic.
- **Completed segment definition**: a reset boundary
  (`resetsAt` change) closes the segment behind it; a segment qualifies
  when `observedPoints > 0`. Sessions and weekly are derived fully
  independently (same `resetsAt` string may appear in both windows).
- **Identity = `(window, resetsAt)`** — first-write-wins: already-
  stored identities are skipped (`duplicatesSkipped`), never rewritten;
  blank/whitespace identity or missing `resetsAt` is skipped and
  counted, never guessed.
- **Retention** (write-time only): records older than 90 days are
  pruned; **the newest record is never pruned**, even if old.
- **Zero-observed completed segments** are skipped, never stored.
- **Write discipline**: single JSON per line, `0600` file, `0700`
  dir, atomic replace + `fsync` + dir sync, stdout is one JSON
  document. Nothing on stdout can be confused with an observation
  record.
- **No side effects**: never calls snapshot/collectors, never mutates
  `observations.jsonl`, no network, no subprocesses besides the sibling
  module imports (which are local Python files).

`--list` mode: opens **only** `segments.jsonl` (missing file = normal
empty `{records: [], total: 0}`), skips malformed lines (counted),
sorts newest first (`endedAt`, then insertion order), returns one JSON
document. **It cannot produce, modify, or delete anything by
construction** (read-only open, no write path exists in that branch).

## 7. Attribution selector — behavior

`[ Weekly ] [ 5-hour ]` toggle in the panel:

- Selects the **live** attribution summary window (current reset
  segment) — both windows are precomputed and cached by
  `AttributionUsage.qml` on the same refresh, so **switching launches
  nothing** and changes only which cached summary is displayed;
  unselected window is never discarded.
- **Seed from settings**: `attributionWindow` is bound to
  `defaultAttributionWindow` (readonly setting proxy). First user click
  breaks only `attributionWindow`’s binding; the setting remains the
  source for the next panel instantiation. Defaults to `weekly`.
- The selector does **not** filter Recent Segments (both windows
  always coexist there) and has no coupling to the history store.
- Markers, coverage line, and expand/collapse all follow the selected
  window’s cached summary.

## 8. Expand/collapse — behavior

- Per agent row: click the agent header to expand/collapse its models
  and per-model point breakdown; `expandedAgentIds` tracks state;
  `toggleAgent(id)` flips one row; header count text changes
  (`N models` / `expanded`).
- Only display state — no data reload, no subprocess, no store access.
- One-line discoverability caption added in Task 7: “Click an agent to
  expand or collapse its models” (faint, shown whenever there are agent
  rows).

## 9. Markers — behavior

Derived in `agent-fleet-aggregate` from the interval classification
of the segment (pure, in-memory):

- `reset_boundary` — at most one per summary, at the newest reset
  that closed the current segment (timestamp = the resetting
  observation’s `observedAt`); the segment it bounds is displayed as
  the pre-reset span.
- `gap` — one per gap interval after the last reset; each carries the
  gap’s end timestamp and its point span.
- Markers are **display metadata only**: they never alter
  `observedPoints`, `attributedPoints`, `unattributedPoints`,
  `coveragePercent`, `agents`, or the unattributed breakdown.
- Markers are **never persisted** into `segments.jsonl`; the history
  record schema has no marker fields.
- Both windows derive markers independently from their own interval
  list.
- Panel renders them as compact chips (simple Unicode, no icon fonts)
  between the summary and the agent list.

## 10. Recent Segments — UI contract

- `HistoryUsage.qml` runs **exactly one** read-only process per
  refresh: `agent-fleet-history --list` (via `listCommand`, direct
  executable — matching the repo pattern; no `python3` wrapper).
- 5-row cap (`maxRows: 5` component constant; deliberately not a
  setting — see §11), newest first, both windows coexisting.
- Row content: window label, persisted duration/range, observed
  points, coverage, and unattributed points (compact, only when
  non-zero). **No raw observations, prompts, IDs, tokens, or logs can
  be shown** — the record schema excludes them and the renderer only
  reads the fixed keys.
- Empty state: “No completed segments yet” (first-use; the user has
  simply not completed a reset window on this machine yet — see §17).
- `enabled` property gates `refresh()`; `Component.onCompleted` uses
  `Qt.callLater` so the panel’s synchronous
  `historyUsage.enabled = root.showRecentSegments` assignment lands
  first — hidden section = zero processes, no startup race.
- Refresh on: panel open, `refresh` interval timer (shared with the
  rest of the panel), panel re-focus. No independent timer.
- Strictly read-only at every layer: QML only spawns the `--list`
  process; `--list` only opens `segments.jsonl` for reading.

## 11. Settings — full inventory

| setting | type | default | effect | presentation-only? |
|---|---|---|---|---|
| `refreshIntervalSec` | integer | 60 | panel auto-refresh cadence | yes (existing) |
| `showPercentInBar` | boolean | true | bar shows percent next to countdown | yes (existing) |
| `defaultAttributionWindow` | enum `weekly`\|`session` | `weekly` | seeds selector initial selection (Phase 4) | yes |
| `showRecentSegments` | boolean | `true` | section + separator visibility + `--list` gating (Phase 4) | yes |

Both new settings default to the prior (visible) behavior; changing
either has **zero effect** on attribution math, retention, snapshots,
or the history store (verified: they appear only in QML bindings and
one `enabled` gate + two `visible` flags; the manifest schema is the
single declaration site).

Not added: `recentSegmentsLimit` — one section, one constant, adding
a setting would grow the manifest for negligible value;
`HistoryUsage.maxRows` is documented as its natural home if ever
requested.

## 12. Security / privacy audit — findings and residual risk

Checks performed (code-level + system state):

- [x] **No prompts, responses, token contents, keys, or raw logs**
      persisted anywhere: `observations.jsonl` inspected live — fixed
      record schema (numeric points, percentages, timestamps, call
      counts, tier/error codes). `segments.jsonl` schema (section 5)
      is a subset of the summary — no free-form fields exist.
- [x] **No provider billing, no model multipliers, no cost weights,
      no confidence scores**: `grep` across all scripts — none;
      attribution uses observed point movement + local call counts only.
- [x] **Read-only upstream access**: Hermes `state.db` opened with
      `file:...?mode=ro` URI (verified in code); Codex collector
      invokes the local Codex CLI (`--limits-only` style), whose own
      network behavior is pre-existing Phase 1 behavior — Phase 4
      code spawns **no** network connections and **no** subprocesses
      beyond the documented `--list` invocation.
- [x] **No writes outside the two declared state files**: history uses
      only the snapshot module’s `atomic_write` helper for
      `segments.jsonl`; no other output paths exist.
- [x] **Permissions**: `agent-fleet/` `0700`, both store files `0600`
      (verified live + asserted in tests); ownership: current user.
- [x] **No credential reads**: no `.env`, no keychain, no
      `~/.config` outside the collectors’ existing local-CLI
      integrations (Phase 1/2 surface, unchanged).
- [x] **No destructive window management**: panel never kills, closes,
      or moves other windows; `omarchy shell shell hide` used for
      verification is the panel’s own hide.
- [x] **Single-JSON stdout contracts** maintained (history store mode
      and `--list` each emit exactly one document; aggregate unchanged).
- [x] **Malformed input tolerance**: list mode skips bad lines (counted,
      not fatal); store mode skips missing/blank identity; neither
      panics the panel.
- [x] **No schema evolution surprises**: `schemaVersion: 1` on both
      stores; readers ignore unknown keys, writers add none.

Residual risks (documented, accepted):

- The Codex CLI upstream (Phase 1) may network — pre-existing,
  out of scope; collector is still read-only from the user’s data
  perspective.
- `segments.jsonl` is local-only; cross-machine sync is a roadmap
  item, not a security control.
- History record `agents` names reflect local Hermes profile names
  (user-controlled); not a secret, but they are the closest thing to
  user-specific identifiers persisted — acceptable and intentional.

## 13. State file audit

| file | path | perms | owner | contents | writes it |
|---|---|---|---|---|---|
| observations | `~/.local/state/omarchy/agent-fleet/observations.jsonl` | `0600` | danilo | Phase 3 records (verified live: points, percentages, timestamps, call counts, tiers, error codes) | `agent-fleet-snapshot` only (panel refresh) |
| segments | `~/.local/state/omarchy/agent-fleet/segments.jsonl` | `0600` (when present) | danilo | completed attribution summaries (section 5) | `agent-fleet-history` store mode only |
| — | `~/.config/omarchy/shell.json` | — | danilo | manifest defaults (not live-mutated by Phase 4) | user/omarchy tooling only |

No other state files are created or read by Phase 4 code. The real
`segments.jsonl` does not exist on this machine yet (no reset window
has completed since the observation store began) — verified, and
intentionally left uncreated (section 17).

## 14. Validation — tests and validator

- **192 tests passed** (`python3 -m pytest tests/ -q`), covering:
  codex (27), hermes (37), snapshot (26), intervals (24), attribution
  (17), aggregate (19), failure-recovery (1), **history (27: 18 store
  + 9 list)**, markers (14).
- `omarchy plugin validate .` → **0** (manifest schema + structure
  valid, including the two new settings).
- `git diff --check` → clean; working tree committed (HEAD `56b9f8b`),
  `git status` clean.
- No flaky state: all hermes fixtures are generated local `state.db`
  (`tests/make_hermes_fixtures.py`), all codex fixtures are static
  JSON; tests use isolated `tmp_path` / `XDG_STATE_HOME` homes.
- Bracket/structure sanity across all 5 QML files verified (Panel,
  AttributionUsage, HistoryUsage, CodexUsage, HermesUsage — all
  balanced).

## 15. Validation — CLI chain (live runs)

Executed against real local state on this machine (all read-only from
the store’s perspective):

- `agent-fleet-codex` → graceful `available: false` (Codex upstream
  currently unavailable on this machine) — expected, panel renders
  the unreadable state.
- `agent-fleet-hermes` → **12 agents** with per-model counters.
- `agent-fleet-intervals` → **66 interval records** from the existing
  observation store.
- `agent-fleet-attribution --window session` → empty current segment
  (normal, session boundary not yet crossed in the store).
- `agent-fleet-aggregate --window weekly` → **6 observed points @ 100%
  coverage**, `2 observed single + 4 estimated shared` over 2 agents,
  1 marker (`reset_boundary`).
- `agent-fleet-aggregate --window session` → empty summary (correct
  for the store’s session state), no markers, `coveragePercent: null`.
- `agent-fleet-history` (default/store mode) → `status: skipped`,
  `appended: 0` (no completed segment in the real store — correct).
- `agent-fleet-history --list` → `{records: [], total: 0}` (normal
  empty state, not an error).

## 16. Validation — live UI (what was verifiable, how)

- **Widget live in the running shell**: `omarchy shell shell summon
  io.github.daniluvatar.agent-fleet` → `ok`; panel opened without
  errors (the real panel component instantiated and rendered —
  `AttributionUsage`, `HistoryUsage`, and all Phase 3 sections
  composed), then closed cleanly via `omarchy shell shell hide …`
  (non-destructive: the panel’s own hide path; no other window was
  touched).
- **Data behind the panel verified live** (section 15) — the exact
  JSON documents the QML components render.
- **Interactions** (selector switching launches nothing; expand/
  collapse; marker chips; 5-row cap; settings gating) are covered by
  code inspection (bindings verified: `attributionWindow` seed binding
  breaks only on click while `root.defaultAttributionWindow` stays
  bound; `historyUsage.enabled` gate lands before the child’s
  `Qt.callLater` fires; `refresh()` guards on `enabled`) and by the
  test suite — direct property-level IPC introspection of the running
  panel is not exposed by this shell build (`omarchy shell <plugin>
  <prop>` targets don’t resolve in the current build), so pixel-level
  inspection was not available and is reported as such rather than
  claimed.
- Screenshot tooling requires interactive region selection (timed
  out, cancelled with Escape; artifact cleaned up).

## 17. Controlled write-path demonstration (temporary store)

Run under an isolated `XDG_STATE_HOME` (real store untouched —
verified: still only `observations.jsonl` there, 68 lines):

- Crafted a 5-line chronological observation timeline with a weekly
  `resetsAt` change (W1 → W2) and Hermes activity counts.
- `agent-fleet-history` (store mode) →
  `status: written, appended: 1, appendedSegments: [["weekly","W1"]]`;
  second identical run → `status: written, appended: 0,
  duplicatesSkipped: 1` (first-write-wins, byte-for-byte stable).
- Stored record (summarized): `weekly / W1 / 20 observed / 12
  attributed / 8 unattributed (incompleteHermesObservability) /
  60% coverage` over one agent + one model (`observedSinglePoints:
  12, estimatedSharedPoints: 0`) — exactly matching the hand-computed
  expectation from the timeline.
- Both files `0600`; directory `0700`; `observations.jsonl` untouched
  by the history runs (line count and content unchanged).
- `--list` on the same temporary home returned the single record under
  the documented `{records, total, segmentsPath}` shape.
- Negative case confirmed: a timeline with **no** reset boundary
  (all rows same `resetsAt`) produced **zero** appends (`status:
  skipped`) — the writer does not invent completed segments.
- Temporary homes and the screenshot artifact were cleaned up after
  the demonstration.

On this machine the real `segments.jsonl` does not yet exist because
no window has completed a reset in the observation store since it
began (2026-09-29) — this is the correct first-use empty state, not a
bug; the first real completed segment will appear naturally.

## 18. What was not done (explicitly, per instruction)

- No features beyond the phase-4 scope (no charts, no burn-rate, no
  export, no cross-machine sync).
- No changes to Phase 1/2/3 collectors, snapshot semantics, interval
  builder, attribution arithmetic, or aggregate summary shape.
- No new settings beyond the two justified ones (section 11).
- No fake records in the real `segments.jsonl` (controlled
  demonstration used temporary homes only — section 17).
- No push, no remote interaction, no Phase 5.
- No destructive Hyprland/window-management invocations (panel
  `hide` only).

## 19. Known limitations

- `--list` sorting ties on `endedAt` break by file order (newest line
  first) — acceptable for append-only, first-write-wins data.
- `--list` has no pagination (5-row cap is a UI constant, by
  design); a very large store still reads fully into one JSON
  document (fine at current scale; would need paging if it grew to
  thousands — noted in the future direction).
- `HistoryUsage.maxRows` is a constant, not a setting (documented
  decision).
- Marker chips are compact; extremely long `gap` labels wrap (no
  truncation policy yet beyond QML’s own elision).
- `defaultAttributionWindow` seeds the initial selection per panel
  instantiation; it does not override a user’s mid-session click
  (by design — the selector is user state after first click).
- Live UI pixel verification was not available in this environment
  (section 16); logic is covered by code + tests.
- `schemaVersion` is not yet used for any migration path — the stores
  are brand-new (`v1`) and there is no prior version to migrate from.

## 20. Future directions

- Historical allowance **burn-rate analytics**, forecasting, and light
  charts on top of the existing completed-segment store (the store
  schema is already the right input for this).
- Export/reporting (e.g. a small `--export` mode reusing `--list`) if
  a real need appears — deliberately not built now.
- Hermes activity for additional providers (Claude, Grok, Copilot,
  local) and other harnesses (OpenClaw, Pi).
- Cross-machine sync of the two local stores (with explicit
  retention-aware merge) — requires a deliberate design; not
  implied by this phase.
- If Recent Segments ever grows beyond a handful of rows, a
  `recentSegmentsLimit` setting and pagination — the constant
  (`HistoryUsage.maxRows`) is the declared home for the setting.

## 21. Final checkpoint status

- **STOP CHECKPOINT 7** was reported and approved earlier in this
  session (section 11 + settings + hint, 192 tests, validator 0,
  README synced, working tree as committed).
- **STOP CHECKPOINT 8 / Phase 4 final**: this report (section 1–20)
  is the final deliverable. All validation (sections 14–17) re-ran
  green at the committed state (HEAD `56b9f8b`), validator 0, git
  clean, 192 tests passed.
- **Do not proceed to Phase 5** (charts / burn-rate / export) without
  an explicit new instruction.

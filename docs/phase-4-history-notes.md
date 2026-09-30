# Phase 4 — Completed Segment History Discovery (Task 1)

Read-only discovery, 2026-09-29. No persistence code written. Sources
inspected, read-only:

- `scripts/agent-fleet-snapshot` (observation store, retention, crash safety)
- `scripts/agent-fleet-intervals` (reset-boundary representation)
- `scripts/agent-fleet-attribution` (per-window attribution kinds)
- `scripts/agent-fleet-aggregate` (current-segment summary)
- `~/.local/state/omarchy/agent-fleet/observations.jsonl` (live store, 36
  lines, `0600` in `0700` dir; counts/timestamps only inspected)

Baseline: branch `phase-3-attribution` (Phase 3 complete; note: local and
remote `main` do not yet contain the Phase 3 commit, contrary to the
playbook's expected baseline — work here proceeds on this branch),
151 unit tests pass, `omarchy plugin validate .` passes.

## 1. How reset boundaries are represented today

- `agent-fleet-intervals` compares **consecutive** observations per window.
  `codex_delta()` emits `reset_boundary` for a window exactly when
  `resetsAt` changes between the two endpoints **or** `usedPercent`
  decreases. `deltaPoints` is `null` there — nothing is bridged, nothing is
  inferred across.
- `resetsAt` is the provider-reported window boundary timestamp (ISO-8601
  with offset). **Live verification:** across all 36 observations in the
  store, `weekly.resetsAt` is `2026-10-05T14:43:07+00:00` and
  `session.resetsAt` is `2026-09-30T00:49:18+00:00` at every point where
  Codex was available — i.e. `resetsAt` is stable **within** one window and
  changes **at** the boundary. It is a natural, provider-supplied segment
  identity. The same string is what the intervals layer uses to *detect*
  the boundary, so it cannot drift from our detection.
- `agent-fleet-aggregate` uses `current_segment_intervals()`: the current
  segment for a window is the tail after the last `reset_boundary` in the
  interval list for that window. Everything before the last boundary is
  already deterministically addressable as "completed segments" — the
  aggregate just does not emit them today.
- Gaps (`codex unavailable`) produce `gap` intervals and never split a
  segment; valid intervals around them stay in the segment. This is
  confirmed in the live store (15 of 36 observations are
  Codex-unavailable; attribution still ran and matched
  `agent-fleet-aggregate --window weekly`: 6.0 pp, 100 % coverage,
  `engineer/gpt-6-sol` 3.93 pp single+shared).

## 2. Can the aggregate layer emit a completed segment deterministically?

**Yes.** `summarize(window, intervals)` is a pure function of one
contiguous run of intervals. Generalizing
`current_segment_intervals()` — which already returns *the* newest run —
to return **every** run between `reset_boundary` splits (or the whole list
when there is no boundary) needs no new rules:

```text
segments(window) = split intervals at reset_boundary (exclusive of the
                   boundary interval itself, which contributes nothing)
completed  = all segments except the last
current    = the last segment   (== today's current_segment_intervals)
```

The "last segment is the current one" invariant holds by construction: a
segment is current because its window's `resetsAt` is the window
identity of the newest usable observations; as soon as an observation with
a *different* `resetsAt` lands, the intervals layer records
`reset_boundary` and that segment becomes "everything except the last".
No clock, no inference, no cross-window mixing (session and weekly are
split independently exactly as they are today).

Determinism caveats (both already true of the current aggregate):

- It is a function of the *retained* observations file. Once raw
  observations are pruned, the input changes and the output could differ
  (see §3). Therefore a completed segment must be captured **before**
  pruning can touch its raw endpoints.
- The first usable observation in the store is baseline-only, so the
  first-ever segment per install absorbs "since first observation" — the
  existing Phase 3 baseline rule, unchanged.

## 3. Can a completed segment be reconstructed after observations are pruned?

**No — not in general.** Attribution is defined over *consecutive*
observations; intervals do not exist without their two endpoints. Pruned
lines are gone, and there is no other durable source:

- Hermes counters are cumulative/lifetime in `state.db`; re-differencing
  tomorrow against tomorrow's values cannot reproduce Tuesday's delta.
- `agent.log` is an incomplete, rotating record (rejected as an input in
  Phase 3; still true).
- The store keeps 14 days only (`agent-fleet-snapshot --retention-days 14`).

Contraction: **history must be written while the raw data still exists.**
That window is generous in practice:

- A completed *session* segment spans ≤ 5 h; its last endpoint (the
  reset-boundary observation) is minutes old.
- A completed *weekly* segment spans ≤ 7 d; by construction the
  pre-reset endpoint is at most ~7 d old — inside the 14-day retention.
- Only the exotic case "machine dormant across a weekly boundary AND more
  than 14 days since the last pre-reset endpoint" would change values;
  that means no usable segment existed at all for that span, so a bounded
  undercount (never an overcount, never fabricating negative values) is
  the worst that can be recorded. Accept and document; do not solve.

Practical rule for Task 2: the history write happens as part of the
settled refresh wave (right after `agent-fleet-snapshot` appends and
prunes), when a new `reset_boundary` for a window is the *newest*
interval. At that moment the store holds the segment's raw endpoints and
the summary is a pure function of them.

## 4. Should weekly and session segments share one history store?

**Yes — one file, one record per segment, with a `window` field.**

- They are distinct records anyway; the aggregate already emits
  per-window summaries with a `"window": "weekly" | "session"` discriminator.
- One file means one location, one permission scheme (`0700` dir / `0600`
  file), one retention pass, one dedup pass — the exact shape of
  `observations.jsonl` today.
- Session segments are short-lived and frequent (one every ~5 h); weekly
  is rare. Keeping them interleaved in chronological order makes the
  "RECENT SEGMENTS" UI (Task 6) trivial and the file's time order natural.
- Sharing a file does *not* mix data: no cross-window computation is ever
  performed on it; `window` + `resetsAt` keep identities separate.

## 5. Minimal fields for useful history

The playbook's suggested record covers everything the current aggregate
computes (`summarize()` output is strictly *richer*: it also has
`segmentStartAt`/`segmentEndAt`/`evidence`). One field is **missing**
from the suggestion and is required for reliable dedup (§6): the window
identity `resetsAt`. Proposed record:

```json
{
  "schemaVersion": 1,
  "window": "weekly",
  "resetsAt": "2026-10-05T14:43:07+00:00",
  "startedAt": "2026-09-22T14:43:08-05:00",
  "endedAt":   "2026-09-29T14:40:00-05:00",
  "observedPoints": 42.0,
  "attributedPoints": 35.0,
  "unattributedPoints": 7.0,
  "coveragePercent": 83.33333333333333,
  "agents": [
    {
      "agent": "engineer",
      "models": [
        {
          "model": "gpt-6-sol",
          "observedSinglePoints": 12.0,
          "estimatedSharedPoints": 8.0,
          "totalAttributedPoints": 20.0
        }
      ]
    }
  ],
  "unattributed": {
    "noHermesActivityPoints": 3.0,
    "incompleteHermesObservabilityPoints": 4.0,
    "noCallableActivityPoints": 0.0
  }
}
```

Notes:

- **`resetsAt` (new vs. the playbook suggestion):** provider-window
  identity used for dedup; also pins *which* Codex window the numbers
  refer to. Verified stable within a window on the live store.
- `evidence` (observedSingle/estimatedShared totals) from the aggregate
  is *derivable* from the `agents[].models[]` split (sum of the two
  per-model fields) and is deliberately not duplicated into the record.
- Invariant kept: `attributedPoints + unattributedPoints == observedPoints`
  at full precision; `coveragePercent` = `attributed/observed*100` or
  `null` when `observedPoints == 0` (never a fabricated 100 %).
- All values are aggregate summaries already shown (or derivable in the
  panel today); no new data class enters the store.

### Write-minimality rule (proposed, to ratify at checkpoint)

Persist a completed segment **only when `observedPoints > 0`**. A
completed window with no observed allowance movement carried no
information (coverage `null`, no agents, zero buckets); writing it would
only grow the file and clutter Task 6's "RECENT SEGMENTS" list. Session
windows especially produce many idle resets overnight. If the project
prefers an audit-style "the window existed" record, that is a one-flag
change for Task 2 — but the default recommendation is content-bearing
segments only.

## 6. How duplicate segment writes can be prevented

**Dedup key: `(window, resetsAt)`.**

- Deterministic: both components come from the Codex window record, not
  from clocks, counters, or computed totals. Two runs of the same
  history pass over the same store must yield the same key.
- Collision-safe: `resetsAt` is unique per window identity (it changes at
  every boundary), and session/weekly boundaries cannot share meaning
  because `window` is part of the key. (Same timestamps across different
  windows — explicitly on the Task 2 test list — is therefore a
  non-collision by construction.)
- Strategy: **scan the existing `segments.jsonl` before appending; if a
  line with the same `(window, resetsAt)` exists, skip.** First-write
  wins. Justification: the summary is a pure function of the retained
  observations, so a skipped later pass would normally recompute the
  *same* numbers; the one case where it would differ (raw endpoints
  pruned in the interim, §3) is exactly the drift we do not want to
  silently overwrite earlier evidence with. Skipping also makes the
  writer idempotent under crash/retry: a line that already landed counts
  as done.
- Implementation note for Task 2: "append-only JSONL" and "14-day-style
  retention pruning" are reconciled the same way `observations.jsonl`
  already is — write retained lines + new line to a same-directory temp
  file, fsync, atomic `os.replace`, `0700`/`0600`. The file is logically
  append-only (no line is ever *modified*); retention re-emits kept
  lines.

## 7. Append-only JSONL

**Yes**, and for the same reasons the Phase 3 store is:

- One line per completed segment, valid UTF-8 JSON, compact separators —
  a line's validity is independent of every other line, so a truncated
  last line (worst-case crash artifact) never corrupts the rest; the
  reader already tolerates malformed lines in `observations.jsonl` and the
  same rule applies.
- No schema in the middle: `schemaVersion` per line allows evolution.
- Human-auditable with `jq`; trivially greppable for the privacy checks.
- Same-directory temp + fsync + atomic replace (reuse the Phase 3
  `atomic_write` pattern, not the exact code — Task 2 decides reuse vs.
  copy) gives identical crash safety with no lock files and no daemon.

## 8. Retention — separate from the 14-day raw store, justified

**Recommended: 90 days, confirmed in Task 2.** Justification, not a
blind pick:

1. **Different content, different risk.** Raw observations are the
   sensitive side (they must expire quickly to bound what is persisted).
   Completed segments are pure aggregates: pp amounts, agent profile
   names, model names. Retaining them longer carries no additional
   privacy exposure beyond what the Phase 3 panel already renders on
   screen.
2. **Size stays bounded.** A record is ≈ 0.4–2 KB depending on
   agent/model count. Upper bound: ≤ 1 session window per 5 h → ≤ 4–5
   eligible session segments/day (realistically far fewer idle ones pass
   the `observedPoints > 0` rule) + 1 weekly/week. Worst ≈ 5×90 + 13 ≈
   **463 records ≈ < 1 MB**; the realistic case is one to two orders of
   magnitude below that. Bounded, and pruned on every write like the raw
   store.
3. **Usefulness horizon.** Task 6 asks for "recent" segments (5 visible);
   90 days ≈ 13 weekly + any number of session segments — enough for the
   intended UX, and covers the "compare to last month/quarter" reading
   without a growth problem. Longer horizons (full history) are explicitly
   out of scope ("prefer compact, privacy-safe summaries over retaining
   raw observations forever").
4. **Independence from raw retention.** A completed segment never needs
   raw observations again, so its retention can ignore the 14-day store
   entirely; conversely, pruning history must never reach back into
   `observations.jsonl` (and won't — different file).

## Privacy impact

- Same data classes as the existing Phase 3 panel and raw store:
  allowance pp, Hermes profile ids (agent names), model names, window
  timestamps. No new categories.
- **Not persisted** (same guarantees as Phase 3, now for history too):
  prompt/response bodies, session ids, task buckets, credentials, OAuth
  tokens, raw Hermes log lines, raw Codex upstream error text. The
  `unattributed` buckets carry *reason codes* (fixed strings), never
  cause text.
- Store location: `$XDG_STATE_HOME/omarchy/agent-fleet/segments.jsonl`,
  fallback `~/.local/state/omarchy/agent-fleet/segments.jsonl` — same
  directory as `observations.jsonl`, `0700` dir / `0600` file, user-owned.
- Attribution remains inference: history rows must keep the same
  disclaimer framing ("inferred from observed Codex allowance changes and
  local Hermes activity — not provider billing").

## Decisions requested at STOP CHECKPOINT 1

1. Approve the record schema (playbook suggestion **plus** `resetsAt`)
   and the one-file `segments.jsonl` layout.
2. Approve dedup key `(window, resetsAt)` with first-write-wins skip.
3. Approve persisting only `observedPoints > 0` completed segments
   (or request audit-style zero-movement rows).
4. Approve 90-day history retention (independent of the 14-day raw
   retention).
5. Note: Phase 3 is not yet on `main` (local/remote); proceed on
   `phase-3-attribution` until it is merged, unless told otherwise.

**Stopped here. No persistence, UI, or aggregate changes have been made.**

---

# Checkpoint status and implementation (appended 2026-07-21)

**STOP CHECKPOINT 1 — PASSED (design approved).** All five decisions
ratified as written, including §5's `observedPoints > 0` write-minimality
rule and the §8 90-day retention.

**STOP CHECKPOINT 2 — PASSED (tasks 1, 2, 3 + task-4 semantics).**
Implemented and tested; full suite green: `TZ=America/Guayaquil python3
-m unittest discover -s tests -p 'test_*.py'` → **169 tests OK** (151
prior + 18 new in `tests/test_agent_fleet_history.py`).

- **CLI:** `scripts/agent-fleet-history [--state PATH] [--segments PATH]
  [--now SECONDS] [--retention-days N]`; `--now` (or `AGENT_FLEET_NOW`)
  pins the retention clock so retries/tests are deterministic. Defaults
  resolve exactly as the Phase 2 store: `XDG_STATE_HOME` (fallback
  `~/.local/state`)/`omarchy/agent-fleet/{observations,segments}.jsonl`.
  Stdout is exactly one JSON document with the fixed key set
  `{appended, appendedSegments, duplicatesSkipped,
  missingIdentitySkipped, pruned, retentionDays, schemaVersion,
  segmentsPath, status, zeroObservedSkipped}`; diagnostics on stderr.
  `status` is `written` when a store write happened and `skipped` when
  there was nothing to append (no store file is created in that case).
- **Completion rule (as §2):** completed runs are the interval slices
  between `reset_boundary` splits per window, excluding the boundary
  interval itself; the run after the last boundary (in-progress) is
  never persisted. Runs are derived on every pass and deduped against
  the store by `(window, resetsAt)` first-write-wins (§6). The identity
  of a closed run is the provider `resetsAt` read from the observation
  that closes it (§2: the boundary observation is guaranteed to have a
  usable identity by construction). Closed runs lacking a usable
  `resetsAt` are skipped (`missingIdentitySkipped`) — never a local
  timestamp, never `unknown`. Zero-movement closed runs are skipped
  (`zeroObservedSkipped`) per §5.
- **Record shape:** exactly the §5 sample (incl. `schemaVersion: 1` and
  `resetsAt`), written as one compact key-sorted JSON line; existing
  lines are preserved byte-for-byte; malformed lines are dropped at
  write time (same corruption tolerance as the Phase 2 store); the run's
  `segmentStartAt`/`segmentEndAt` become `startedAt`/`endedAt` (the
  evidence envelope), `agents`/`unattributed` keep the exact Phase 3
  attribution engine field names.
- **Retention (§8):** 90 days (default; `--retention-days` adjustable),
  applied at write time against `endedAt`, independent of and never
  touching the 14-day raw store; the history write leaves
  `observations.jsonl` byte-for-byte unchanged (asserted in tests).
- **Privacy:** record content is drawn only from fixed numeric/identity
  fields (verified in tests that extra secret-like fields never leak);
  attribution disclaimer is unchanged (inference, not provider billing).
- **Determinism:** identical inputs produce byte-identical stores across
  repeated runs (tested);
  the CLI reuses the shared phase layers (`agent-fleet-snapshot.atom_write`,
  `agent-fleet-intervals.build_interval`, `agent-fleet-aggregate` —
  which embeds the `agent-fleet-attribution` engine per its contract)
  rather than re-deriving any rule.

**Remaining phase work per the approved plan:** task 5 (live +
completed combined read command with the live/current vs completed
split) and task 6 (phase-4 integration tests + final report). Both
follow the same record contract fixed here.

# STOP CHECKPOINT 3 — Session / 5-hour attribution view (Task 3)

Task 3 is complete. The panel now exposes both attribution windows
(`--window weekly` and `--window session`) behind a native `[ Weekly ]
[ 5-hour ]` selector, weekly by default. Switching is display-only: no
collector refresh, no snapshot, no segment write, no data mutation.
Stopped here per instruction; Task 4 was not started.

## What changed

- **`AttributionUsage.qml`** — rewritten (schema `attribution-usage/v2`,
  365 lines). The component exposes a `window` property but a single
  refresh pass fetches and computes **both** windows (3 child processes:
  intervals → aggregate for weekly and session, against the unchanged
  raw store). Both computed summaries are cached; the `window` property
  only selects which cached summary is surfaced through the read-only
  presentation properties (`dataState`, `ready`, `refreshing`,
  `observedText`, `coverageText`, `statusText`, `agentRows`,
  `unattributedLine`, `coverageFootnote`, `explanationLine`,
  `formatPoints`). Per-window state is independent (ready/error/empty/
  gap tracked per window). Idempotency: per-process `onStreamFinished` /
  `onExited` bool flags (both signals fire per process; the second
  arrival is a no-op), replacing the earlier shared counter.
- **`Panel.qml`** —
  - Header row: the old "Weekly Attribution" heading is now
    "Attribution", with the native `qs.Ui ButtonGroup` selector below it
    (options `weekly`/`session`, labels `Weekly`/`5-hour`;
    `value: root.attributionWindow`; `onChanged: v → root.attributionWindow = v`).
  - `property string attributionWindow: "weekly"` — pure panel state,
    never persisted, weekly is the default on every load.
  - `readonly property var attributionUsage: AttributionUsage { window:
    root.attributionWindow }`; the panel body reads the presentation
    properties, so switching just rebinds them from cache.
  - `maybeSnapshot()` remains the single refresh call site (fires once
    after the Codex+Hermes wave settles); it now also calls
    `attributionUsage.refresh()`. The selector issues **no** commands.
- Terminology kept exactly as required: Observed, Estimated,
  Unattributed, Coverage, pp; "Coverage is the share of observed
  movement Agent Fleet could attribute to an agent and model — not a
  share of the subscription."; "Inferred from Codex allowance changes
  and local Hermes activity." No provider-truth phrasing.

## Verification

- **Live CLI comparison (both windows):** weekly → Observed movement
  6 pp, coverage 100%, 3 agents; session (5-hour) → Observed movement
  29 pp, coverage 100%, 3 agents. Same status line on both windows
  ("Attribution incomplete — Codex observations contain gaps."),
  per-window state carried independently.
- **Real widget, real data, inside a shell (probe instance):** the
  plugin's `Panel.qml` was instantiated by a throwaway quickshell
  instance (`/tmp/af-probe`, since the live shell's a11y tree does not
  expose panel internals). Driven over IPC:
  - initial state `{"win":"weekly", st:"ready", refreshing:false,
    observed:"Observed movement: 6 pp", coverage:"Coverage: 100%",
    rows:3, expl:"Inferred from Codex allowance changes and local
    Hermes activity."}` — default window is **weekly**, values match
    the live CLI exactly;
  - `setWindow("session")` → immediate `st:"ready"`,
    `refreshing:false`, `observed:"Observed movement: 29 pp"`,
    `coverage:"Coverage: 100%"`, `rows:3` — no fetch triggered;
  - `setWindow("weekly")` → back to the 6 pp state, still
    `st:"ready"` from the same cache (both windows cached since the one
    refresh pass);
  - **process count around the switches: 0 before → 0 after** (no
    child processes spawned by switching);
  - `observations.jsonl` unchanged by the switches (42 lines before and
    after in the probe window; the only appends of the session came from
    the normal 60 s panel open/refresh snapshot cadence on the live
    shell — not from switching).
  - Note: `refreshing` is a *pending-fetch* flag, true only between
    "fetch started" and every pending process settled.
- **Live shell (production panel):** restarted quickshell
  (supervisor respawn), no QML errors/warnings in
  `journalctl --user -t omarchy-shell` beyond the standard per-target
  IpcHandler co-registration warning (same as other Omarchy plugins).
  The panel opens via IPC (`omarchy shell io.github.daniluvatar.agent-fleet
  open`, rc 0) and renders; screenshot OCR shows the panel content
  (Agent Fleet title, Codex hero, Hermes Activity rows). The
  Attribution section is inside the panel's scrollable `Flickable`
  (standard kit behavior; arrows scroll per the existing
  `PanelKeyCatcher` `onMoveRequested` handler). The live target's IPC
  surface is unchanged: `open/close/show/hide/toggle/refresh`
  (`refresh()` → "ok").
- **Static / suite:** `omarchy plugin validate .` rc 0; full test suite
  **169 tests OK** (4.0 s) — the QML selector adds no Python surface, so
  the Python suite is unchanged and green.
- **Command-set simulation (read-only-ness):** opening the panel path
  and switching windows issued zero state writes to
  `~/.local/state/omarchy/agent-fleet/` (observations mtime unchanged
  across both switches; `segments.jsonl` still absent — no completed
  segment has closed yet in this session, as before Task 3).

## Root-cause note (for the record)

The first live attempt failed with
`Panel.qml:633:15: Cannot assign to non-existent property "onChange"`.
`qs.Ui ButtonGroup` declares `signal changed(string value)`; the QML
signal handler is `onChanged:`, not `onChange:` (that would target a
signal named `change`, which does not exist). Fixed to `onChanged:
function(v) { root.attributionWindow = v }`; after the fix the widget
loads cleanly in both the live shell and the probe instance.

## State at stop time

- Probe instance terminated; only the production shell running.
- Live panel closed after testing.
- Store: `observations.jsonl` 44 lines (all from the normal 60 s open /
  refresh cadence during verification), `segments.jsonl` absent, no
  corruption, store permissions 0600.
- Task 4 (live + completed combined read command) **not started**.

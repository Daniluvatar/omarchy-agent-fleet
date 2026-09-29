# Phase 3 — Attribution Timing Discovery (Task 1)

Verified read-only on this machine, 2026-09-29. Only counts, timestamps, and
metadata were inspected. No prompt/response content, no `messages` bodies,
no credentials, and no Hermes/Codex state was modified
(`file:<db>?mode=ro` opens, targeted `grep -c`/`tail` on logs).

Baseline at discovery time: `main @ db8b252` (Phase 2 merged), tree clean,
64 unit tests pass, `omarchy plugin validate .` passes.

## Sources considered

### 1. `~/.hermes/profiles/<profile>/state.db` (SQLite, per profile)

- `session_model_usage`: aggregate counters
  (`api_call_count`, `input_tokens`, `output_tokens`, `cache_read_tokens`,
  `cache_write_tokens`, `reasoning_tokens`) with primary key
  `(session_id, model, billing_provider, billing_base_url, billing_mode, task)`.
  Rows are per session + model + task bucket and accumulate over the
  session's life.
- `sessions`: `started_at` / `last_activity_at` (epoch seconds).

Evidence collected (Codex-filtered: `billing_provider='openai-codex'`):

| Profile | Codex usage rows | rows with valid `last_activity_at` | notes |
|---|---|---|---|
| cloud | 5 | **1** | usage exists but mostly *unjoinable* to a valid session timestamp |
| diana | 0 | — | (Phase-2 counter-example profile: DB had data, log didn't) |
| engineer | 35 | 35 | newest activity ~16 h old |
| engineeringmanager | 26 | 8 | newest ~1.5 h old |
| oracle | **337** | **116** | 221 rows lack a usable session timestamp |
| productmanager | 18 | 10 | |
| publisher | 12 | 12 | |
| researcher / reviewer | 0 | — | |
| scribe | 7 | 7 | activity predates the 7-day window |
| staff | 4 | 2 | |
| tester | 13 | 9 | |
| **total live fleet profiles** | **9** with `state.db` | | |

Every row had at least one non-zero timestamp (`bothTsZero = 0` on all
profiles), but a **time-window filter on `sessions.last_activity_at` is
unreliable**: on `oracle` 65 % of Codex usage rows carry no valid session
timestamp, and on `cloud` 80 % do not. A windowed (e.g. 7-day) sum computed
from such rows is therefore unstable: counters can enter and leave the window
as timestamps are corrected/backfilled, which would produce spurious
"negative activity" when snapshots are differenced.

### 2. `~/.hermes/profiles/<profile>/logs/agent.log*` (free text)

Successful calls match the `API call #N: model=… provider=… in=… out=…` INFO
shape with a local ISO timestamp; failures are distinct WARNING lines (both
established in Phase 2, `docs/hermes-reference-notes.md` §3/§6 and
re-confirmed by line counts today).

Observed today:

- Per-profile current `agent.log` success-line counts range from 6 (`staff`)
  to 1166 (`engineer`); all lines carry timestamps.
- Rotation exists only on `oracle` (`agent.log.1..3`, spanning ~Aug 18 to
  Sep 22). For every other profile the current `agent.log` alone begins
  within the last 7 days, so **rotated files are not required to cover the
  current 7-day window**.
- **Completeness is not guaranteed**: `cloud` has 13 cumulative Codex calls
  in `state.db` and only 8 success lines in its (tiny) current log, all
  timestamped one moment; the Phase-2 finding (DB row with *zero* log lines)
  continues to generalize — the log is a partial record, the DB is the
  complete one.

## Answers to the Task 1 questions

1. **Per-call successful Codex timestamps in `agent.log`?**
   Yes, technically — `API call #N:` lines carry per-call local timestamps,
   model, provider, in/out tokens, cache, and session id. But the log is an
   incomplete record (the `cloud` and earlier counter-examples), so it can
   undercount activity and cannot be the source of truth for attribution.

2. **Profile / model / provider / tokens / session identifiable?**
   Profile: `state.db` location. Model/provider/calls/tokens:
   `session_model_usage` (complete). Session id and (sometimes) timestamps:
   `sessions` join — usable for *staleness hints* but unreliable for window
   boundaries (see table above). All per-call details: `agent.log`,
   where present.

3. **Rotated logs needed for the 7-day window?**
   No. Only `oracle` has rotated files and even there the current `agent.log`
   starts inside the 7-day window.

4. **Are log records stable enough as a timing supplement?**
   Line *shape* is stable within this Hermes version, but the log is partial,
   free-form, bounded by rotation (~3 × ~5 MB), and a private format. We
   reject it as an input source for Phase 3.

5. **Is `state.db` alone sufficient for change detection between snapshots?**
   Yes. The counters in `session_model_usage` accumulate per
   session+model+task and are monotonic in practice; summing them without a
   time window makes the total monotonic even when session timestamps are
   missing or backfilled. Interval activity is then simply the difference of
   two cumulative checkpoints — no per-call timing needed.

6. **Can cumulative Hermes state be differenced safely?**
   Yes, with the playbook's guardrails: snapshot the *un-windowed* Codex
   cumulative totals per profile + model; a delta is activity in the
   interval; if a counter decreases between checkpoints, treat that
   identity's delta as unknown/reset (never negative, never fabricate
   continuity). Two risks are recorded rather than solved:
   (a) Hermes' own maintenance — `state.db.fts_rebuild.lock` and
   `state.db.quarantine.lock` siblings exist, so row rewriting/quarantine is
   *possible*; the decrease → reset rule is the documented response.
   (b) counters are cumulative over the profile's lifetime, so the first
   valid interval after installation would absorb lifetime activity — the
   UI's "Collecting attribution data…" early state (fewer than two valid
   snapshots) and per-Codex-window (session/weekly) reset-segment handling
   bound the exposure; the playbook already requires not mixing 5h/weekly
   windows.

## Chosen strategy for Phase 3 MVP

**Cumulative `state.db` checkpoints, differenced between snapshots.
`agent.log` is NOT used.**

- Per profile, one checkpoint row per model (billing_provider =
  `openai-codex`): cumulative `calls`, `inputTokens`, `outputTokens`,
  `cacheReadTokens`, `cacheWriteTokens` over **all time** (no time filter).
- Intervals derive activity as `checkpoint[n+1] − checkpoint[n]` per
  identity, with the decrease → unknown/reset rule per identity.
- `sessions.last_activity_at` is kept only as an *optional staleness hint*
  (never for windowing, because of the join failures above).
- No second log parser, no regex over free text, no dependence on rotation.
- Read access strictly `file:…?mode=ro` with a short timeout; fail soft to
  "Hermes unavailable" for that profile rather than crashing the snapshot.

## Remaining ambiguity

- Per-call timing within an interval is unknown by design: attribution is
  interval-granular. This is exactly what the observed/estimated evidence
  classes are meant to express.
- `title_generation`/`approval`/`background_review` task buckets are summed
  (real successful Codex calls, same as Phase 2).
- Call-weight (`deltaCalls`) allocation remains the deterministic rule for
  `ESTIMATED_SHARED`; token volume is deliberately not used (cache/context
  distortion; unknown model weighting).

## Privacy implications

- Checkpoints store counts and token totals only — no prompt/response text,
  no session identifiers, no `resp_…` ids, no credentials, no upstream error
  text.
- `state.db` is opened read-only; Phase 2's verification (DB/WAL unchanged
  before/after runs) applies and must be re-checked after Task 2.
- The new state file lives under `$XDG_STATE_HOME/omarchy/agent-fleet/` (or
  `~/.local/state/omarchy/agent-fleet/`), user-only permissions, bounded
  retention — not inside `~/.hermes`, `~/.codex`, or this repository.
- Attribution numbers are derived *inference*, never displayed as provider
  billing facts.

## STOP CHECKPOINT 1 status

- `state.db` snapshot differencing: **viable** (un-windowed cumulative sums;
  decrease → reset/unknown rule).
- `agent.log`: **not required** (incomplete record; rotation not covering
  the 7-day window; rejected as an input source).
- Proposed observation strategy: cumulative per-profile/per-model Codex
  checkpoints from `state.db` only.
- Ambiguity: interval-granular timing; possible Hermes counter
  rewrite/quarantine — handled by the reset rule, not silently.
- Privacy: counts/tokens only, read-only access, XDG-state persistence.

**Stopped here. No snapshot, interval, or attribution code has been written.**

---

## Recorded rules for Task 3 (checkpoint 2A)

- Codex endpoint missing/unusable = **gap**.
- A Codex percentage/reset change that indicates a new window = **reset_boundary**.
- A Hermes cumulative counter decreasing = **continuity unknown** for that identity (no negative activity, no invented activity).
- `last_activity_at` staleness **alone** does **not** reset cumulative counters.
- A Hermes profile that was unreadable in one snapshot and readable in a
  later one: that transition is **not** a measurable interval — the
  cumulative counters present after recovery must not be attributed to the
  first readable window.
- A profile that did not exist before is a **baseline** at its first
  readable observation, like the first snapshot overall.

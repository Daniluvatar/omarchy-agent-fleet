# Phase 3 Final Report — Weekly allowance attribution (inferred)

Worktree: `~/Projects/OmarchyContribution/plugins/omarchy-agent-fleet`
Plugin id: `io.github.daniluvatar.agent-fleet`
Date: 2026-09-29 (local, `-05:00`)

## 1. Scope and completion status

Phase 3 (weekly allowance attribution) is implemented, offline-tested, and
live-tested on this machine. Nothing was pushed, committed, or installed
anywhere new; the installed plugin remains the pre-existing symlink → this
repository. No features beyond Phase 3 were added.

> **Agent Fleet attribution is an inference from locally observed Hermes
> activity and changes in Codex subscription allowance. It is not
> provider-supplied per-agent billing data.**

## 2. Changed & added files

Modified: `README.md`, `Panel.qml`, `CodexUsage.qml` (minor), `HermesUsage.qml` (minor).
Added: `AttributionUsage.qml`, `scripts/agent-fleet-snapshot`,
`scripts/agent-fleet-intervals`, `scripts/agent-fleet-attribution`,
`scripts/agent-fleet-aggregate`, `docs/phase-3-attribution-notes.md`,
`tests/test_agent_fleet_{snapshot,intervals,attribution,aggregate,failure_recovery}.py`.

## 3. Snapshot mechanism

Each settled refresh wave (timer / manual / panel reopen — never a redraw)
arms `agent-fleet-snapshot` exactly once; it does its own fresh collection
(Codex + Hermes), appends ONE observation (atomic temp + fsync + rename),
enforces ~60 s minimum spacing and 14-day retention pruning internally.
A failed/duplicate capture is diagnostic only.

## 4. State file location & permissions

`$XDG_STATE_HOME/omarchy/agent-fleet/observations.jsonl`
(= `~/.local/state/omarchy/agent-fleet/observations.jsonl`). Verified live:
directory `0700`, file `0600`, owner-only. No state outside XDG.

## 5. Retention & size bounds

14-day retention pruned on every write. Measured observation ≈ 3 KB →
≈ 300 KB/day at the 900 s default cadence, capped around ≈ 4 MB in steady
state.

## 6. Attribution categories (per interval, per window)

`gap` · `reset_boundary` · `no_allowance_delta` · `unattributed`
(`incomplete_hermes_observability` | `no_hermes_activity` |
`no_callable_activity`) · `observed_single` · `estimated_shared`.
Identity is always `agent + model`. Allocations sum back to the observed
delta; `attributed ≤ observed` is never violated; unattributed movement is
never re-normalized.

## 7. Weighting rule

`estimated_shared` splits a positive delta by **call-count weight only**
(`delta * calls_i / sum(calls)`); zero-call rows don't weight; token
deltas are never used as cost weights; no model multipliers; no confidence
scores anywhere in the chain.

## 8. Reset handling

A `resetsAt` change or a later-lower `usedPercent` = `reset_boundary` →
new segment; the pre-reset intervals keep their valid attributions; nothing
is backfilled across the boundary. First observation is baseline-only.

## 9. Gap handling

A failed Codex refresh = one gap observation; its interval kind is `gap`;
gaps are displayed as breaks and never inferred across. Weekly and session
windows are operated on independently and never mixed.

## 10. Coverage — exact meaning

`coveragePercent = attributedPoints / observedPoints × 100` (or `null`;
never a fabricated 100 %). It is NOT provider-reported usage, NOT a
confidence score, NOT a claim the remainder belongs to "nobody", and NOT a
share of the subscription. The panel prints the definition next to the
number.

## 11. Privacy & security (14-item checklist — all verified)

- [x] No prompt bodies persisted · [x] no response bodies persisted ·
  [x] no OAuth tokens · [x] no API keys · [x] no raw Hermes logs (only fixed
  codes like `CODEX_UNAVAILABLE`) · [x] no raw Codex auth/error data
- [x] State only under XDG state · [x] permissions 0700/0600 (live-verified)
- [x] Hermes DBs opened `mode=ro` · [x] no system Omarchy files modified
- [x] no new network service · [x] no daemon · [x] no model cost multipliers
- [x] no exact-attribution claim anywhere in UI or contracts

## 12. Limitations (documented in README)

Attribution is inference, not billing (stated verbatim above). The
last-good Codex value is in-memory per shell — **after an Omarchy shell
restart, a first refresh failure has no last-good value to show** (section
is unavailable until next success); the store side is a gap, never
backfilled. Upstream `CODEX_UNAVAILABLE` is intermittent (by design, the
panel flags stale values). Scrolling affordances compile/load cleanly but
keystroke-driven scrolling was not live-exercised (no key-injection in this
session).

## 13. UI integration

New third panel section "Weekly Attribution" fed by
`AttributionUsage.qml` — a read-only data source running
intervals → attribution → aggregate against the store. Panel renders only;
no attribution QML math. States: *Collecting attribution data…* / *New
weekly window — collecting data…* / *Attribution incomplete — Codex
observations contain gaps.*. Refresh once per settled wave; never on
open/redraw; never arms a snapshot of its own.

## 14. Documentation

README fully updated: status → "Phase 3 complete, live-tested", 10-item
doc set present (snapshot mechanism, state location, retention, categories,
weighting, reset, gap, coverage, privacy, limitations), the verbatim
inference disclaimer, layout tree, test inventory, future-direction
rebaselined (Phase 3 removed from "not implemented").

## 15. Verification — automated

`python3 -m unittest discover -s tests -p 'test_*.py'` →
**151 tests, OK** (codex 27, hermes 37, snapshot 26, intervals 24,
attribution 17, aggregate 19, failure_recovery 1).
`omarchy plugin validate .` → exit 0. All six CLI scripts exercised end to
end. `git diff --check` clean.

## 16. Verification — live (real system)

Installed = repo (symlink, same inode). Live session: panel opened and
rendered all three sections with **zero QML errors** and no agent-fleet /
AttributionUsage crashes in `journalctl -t omarchy-shell`;
151/151 → store grew **exactly 1 line per refresh wave** (no redraw
bursts); panel attribution values matched
`agent-fleet-aggregate --window weekly` on the same store.

## 17. Verification — privacy scan of the live store

Grep of `observations.jsonl`: no prompts, responses, session ids, task
buckets, credentials, raw logs, or raw error text. Codex unavailable lines
carry only the fixed code. Permissions stable 0700/0600.

## 18. Live example (observed during testing, 2026-09-29)

Weekly segment 15:33–16:52 local: observed movement 6.0 pp; engineer /
gpt-6-sol 3.9 pp (2.0 observed_single + 1.93 estimated_shared);
oracle / gpt-6-astra 1.84 pp; TechLead / gpt-6-luna 0.23 pp; attributed
6.0 pp; unattributed ≈ 0; coverage ≈ 100 % (single-observation segments
dominated).

## 19. Follow-ups (not done deliberately)

Phase 4 (proposed): per-agent collapse/expand, reset-boundary markers,
session-window panel variant (engine already supports it), per-segment
history of coverage/pp. No further scope was started.

## 20. Explicit statement (required by Task 8)

> Agent Fleet attribution is an inference from locally observed Hermes
> activity and changes in Codex subscription allowance. It is not
> provider-supplied per-agent billing data.

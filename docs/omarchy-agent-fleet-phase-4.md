# Omarchy Agent Fleet — Phase 4 Implementation Playbook

## Phase 4 Goal

Phase 4 improves the usability of Phase 3 attribution without changing its mathematical semantics.

Primary goals:
1. Retain compact completed attribution segments safely.
2. Add session / 5-hour attribution to the panel.
3. Add expand/collapse behavior for agent/model attribution rows.
4. Add visible reset and gap markers.
5. Add compact completed-segment history.
6. Keep the panel readable as content grows.
7. Preserve Phase 3 attribution semantics exactly.

Phase 4 is primarily a UX + history phase, not a new attribution-model phase.

## Non-negotiable Phase 3 Semantics

Do not change these rules unless a correctness bug is proven and reported before modification:

- first snapshot = baseline only;
- cumulative Hermes counters come from `state.db`;
- `agent.log` is not an attribution source;
- Codex session and weekly windows are independent;
- gaps are never bridged;
- reset boundaries start new segments;
- partial Hermes observability blocks allocation;
- `observed_single` is observational correlation, not provider billing truth;
- `estimated_shared` uses `deltaCalls` only;
- no token-weighted attribution;
- no model multipliers;
- unattributed movement remains unattributed;
- coverage = attributed positive observed movement / all positive observed movement;
- coverage is not a confidence score;
- coverage is not subscription share;
- stale UI values never become fresh attribution observations.

## Explicitly Out of Scope

Do not implement new providers, Claude/Grok/Copilot/local-model attribution, OpenClaw/Pi integration, cross-machine synchronization, charting, burn-rate forecasting, notifications, exports, prompt/session drill-down, billing estimation, money/cost calculations, numeric confidence scores, or changes to Phase 3 weighting.

## Fresh Session Workflow

At the start of a fresh local-model session:

```text
/omarchy
```

Then read:

```text
README.md
docs/reference-notes.md
docs/hermes-reference-notes.md
docs/phase-3-attribution-notes.md
docs/phase-3-final-report.md
this Phase 4 playbook
```

Then verify:

```bash
git status
git log --oneline -12
python3 -m unittest discover -s tests -p 'test_*.py'
omarchy plugin validate .
```

Expected baseline: Phase 3 merged to `main`, clean working tree, attribution UI operational, 151 tests passing, and no Phase 4 work started.

## Phase 4 Architecture

```text
Phase 3 observations
        ↓
intervals
        ↓
attribution
        ↓
aggregate
        ↓
current segment UI
        │
        └──────────────┐
                       ↓
             completed segment summary
                       ↓
                 compact history
```

Phase 4 should prefer compact, privacy-safe summaries over retaining raw observations forever.

# Task 1 — Completed Segment History Discovery

## Objective

Determine the safest way to retain completed weekly/session attribution segments after Phase 3 observations expire.

Do not implement persistence yet.

Investigate:
1. How reset boundaries are represented today.
2. Whether the current aggregate layer can emit a completed segment deterministically.
3. Whether a completed segment can be reconstructed after raw observations are pruned.
4. Whether weekly and session segments should share one history store.
5. What minimal fields are needed for useful history.
6. How duplicate segment writes can be prevented.
7. Whether history should be append-only JSONL.
8. Whether retention should differ from the 14-day raw observation store.

Preferred direction:

```text
$XDG_STATE_HOME/omarchy/agent-fleet/segments.jsonl
```

fallback:

```text
~/.local/state/omarchy/agent-fleet/segments.jsonl
```

Suggested record:

```json
{
  "schemaVersion": 1,
  "window": "weekly",
  "startedAt": "...",
  "endedAt": "...",
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

Do not persist prompts, responses, session IDs, credentials, raw logs, or raw error text.

Do not pick a retention period blindly. A bounded period such as 90 days may be reasonable, but discovery must justify it.

Deliverable:

```text
docs/phase-4-history-notes.md
```

STOP CHECKPOINT 1 must report whether completed segments can be reconstructed safely, the exact history record proposal, recommended retention, dedup strategy, weekly/session handling, and privacy impact.

# Task 2 — Segment History Store

Persist completed reset segments only.

Recommended script:

```text
scripts/agent-fleet-history
```

Requirements:
- append only completed segments;
- never write current in-progress segment as completed;
- deduplicate by stable segment identity;
- weekly and session remain separate;
- retain full precision internally;
- preserve agent+model split and unattributed reason buckets;
- no new attribution rules;
- no raw observation copying;
- no prompt/session/log content.

Prefer `segments.jsonl` in the same XDG state directory.

Use same conservative crash-safety style as Phase 3: same-directory temp file, fsync, atomic replace where practical, user-only permissions.

Test first weekly/session segment, duplicate skip, same timestamps across different windows, current segment exclusion, malformed old lines, retention pruning, breakdown preservation, no secrets, deterministic output.

STOP CHECKPOINT 2: storage path, schema, permissions, retention, dedup key, examples, tests, working tree. No UI.

# Task 3 — Session / 5-Hour Attribution View

Expose the already-supported Phase 3 `session` attribution window in the panel. Do not change attribution math.

Preferred compact UX:

```text
ATTRIBUTION

[ Weekly ] [ 5-hour ]

Observed movement: 11 pp
Coverage: 73%
...
```

Requirements:
- weekly default;
- switching is display-only/read-only;
- no snapshot/history writes from switching;
- session and weekly never mix;
- states remain window-specific;
- labels identify selected window.

Verify weekly against `agent-fleet-aggregate --window weekly` and session against `--window session`; switching must not change snapshot count.

STOP CHECKPOINT 3: selector UX, weekly/session values, snapshot count, state behavior, tests.

# Task 4 — Agent / Model Expand-Collapse

Reduce vertical density without hiding information.

Example:

```text
▾ Engineer                         7 pp
    GPT-6 Sol
      5 pp observed · 2 pp estimated

▸ TechLead                         2 pp
▸ Publisher                        1 pp
```

Requirements:
- agent total visible while collapsed;
- expanding shows models;
- observed/estimated stay distinct;
- unattributed separate;
- presentation-only state;
- no collector refresh/snapshot write;
- no attribution changes.

In-memory expansion state is sufficient.

STOP CHECKPOINT 4: default, behavior, multi-model example, snapshot count unchanged, scrolling interaction, tests.

# Task 5 — Gap and Reset Markers

Make evidence discontinuities visible without introducing charts.

Possible presentation:

```text
↻ Reset boundary
│ Gap: Codex unavailable
● Observed
◐ Estimated
○ Unattributed
```

Requirements:
- reset marker from actual reset boundary;
- gap marker from actual gap intervals;
- no invented timestamps;
- no implication missing usage was zero;
- no confidence scores;
- consistent Omarchy style.

STOP CHECKPOINT 5: reset/gap representation, current-segment behavior, density impact, tests.

# Task 6 — Compact Segment History UI

Show recent completed segments from the Phase 4 history store.

Preferred:

```text
RECENT SEGMENTS

Weekly · Sep 22–29
42 pp observed · 83% coverage

Weekly · Sep 15–22
35 pp observed · 71% coverage
```

Optional expansion may show attributed/unattributed totals.

Requirements:
- completed segments only;
- current segment remains in main Attribution view;
- show window, date range, observed movement, coverage;
- optionally attributed/unattributed;
- limit visible history rows;
- remain scrollable;
- no raw observations or prompt/session detail.

Recommended visible limit: 5 most recent segments.

STOP CHECKPOINT 6: live/synthetic list, ordering, row limit, scroll, privacy, tests.

# Task 7 — UX Polish / Settings

Allowed candidates:
- default attribution window;
- show/hide completed history;
- history row limit;
- collapsed/expanded default;
- compact labels;
- keyboard navigation.

Do not add all automatically. Justify each new setting and follow repository conventions.

STOP CHECKPOINT 7: settings, defaults, keyboard behavior, panel-size impact, tests.

# Task 8 — Final Documentation and Validation

Update README/docs for segment history architecture, state location, retention, dedup, weekly/session switch, expand-collapse, reset/gap markers, recent history, privacy, limitations.

Preserve this statement:

> Agent Fleet attribution is inferred from observed Codex allowance changes and local Hermes activity. It is not provider-supplied per-agent billing data.

## Final Security Checklist

```text
[ ] No prompt bodies persisted
[ ] No response bodies persisted
[ ] No OAuth tokens persisted
[ ] No API keys persisted
[ ] No raw Hermes logs persisted
[ ] No raw Codex upstream errors persisted
[ ] Completed history stores summaries only
[ ] History file is user-owned
[ ] History file permissions are restrictive
[ ] No new daemon
[ ] No new network service
[ ] No attribution math changed silently
[ ] No token/model cost multipliers introduced
[ ] No numeric confidence score added
```

## Final Validation

```bash
TZ=America/Guayaquil python3 -m unittest discover -s tests -p 'test_*.py' -v
omarchy plugin validate .
./scripts/agent-fleet-codex | jq .
./scripts/agent-fleet-hermes | jq .
./scripts/agent-fleet-intervals --pretty
./scripts/agent-fleet-attribution --pretty
./scripts/agent-fleet-aggregate --window weekly --pretty
./scripts/agent-fleet-aggregate --window session --pretty
git diff --check
git status
```

Also verify live: Codex, Hermes Activity, weekly attribution, 5-hour attribution, switching, expand/collapse, reset/gap markers, completed history, scrolling, no recursive snapshot creation, and no QML errors.

## Definition of Done

Phase 4 is complete only when segment-history design/persistence/retention/dedup, weekly/session selector, expand-collapse, reset/gap markers, compact history, existing UI compatibility, frozen Phase 3 semantics, no snapshot recursion, tests, validator, live panel, privacy checks, docs, clean tree, and no Phase 5 work are all confirmed.

## Suggested Commit Sequence

```text
docs: record phase four history design
feat: persist completed attribution segments
test: cover segment history persistence
feat: add attribution window selector
feat: add attribution row expansion
feat: show reset and gap evidence markers
feat: render recent attribution segments
feat: polish attribution ux
docs: finalize phase four attribution ux
```

Do not push unless explicitly instructed.

## Final Report Expected

Report:
1. Status.
2. History design.
3. History store path.
4. Retention.
5. Dedup strategy.
6. Weekly/session UX.
7. Expand/collapse UX.
8. Reset behavior.
9. Gap behavior.
10. Recent segment history.
11. Snapshot interaction.
12. Tests.
13. Live verification.
14. Privacy/security.
15. Known limitations.
16. Findings for Phase 5.
17. Commit hashes.
18. Confirmation Phase 5 was not started.

# Instructions to the Coding Agent

Start with **Task 1 — Completed Segment History Discovery only**.

Do not write persistence code yet.

Create:

```text
docs/phase-4-history-notes.md
```

Then stop at **STOP CHECKPOINT 1** and wait for approval.

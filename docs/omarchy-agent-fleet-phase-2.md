# Omarchy Agent Fleet — Phase 2 Implementation Playbook

## Purpose

This document defines **Phase 2 only** of **Omarchy Agent Fleet**.

Phase 1 is complete and already provides:

- a working Omarchy third-party bar widget;
- a live Codex subscription allowance panel;
- a local Codex collector;
- a stable JSON contract;
- tests and documentation.

Phase 2 adds **Hermes discovery and normalized activity records**.

It does **not** calculate how much of the Codex weekly or 5-hour allowance each bot consumed. That is Phase 3.

---

# How the coding agent must work

Treat this as a junior-developer ticket.

## Rules

- Do only the work described in this document.
- Work in small steps.
- Stop at every checkpoint.
- Do not continue automatically after a STOP checkpoint.
- Do not invent Hermes file formats or paths.
- Inspect the local Hermes installation before writing parsers.
- Do not rewrite Phase 1 unless a Phase 2 change strictly requires it.
- Do not push unless the human explicitly asks.
- Do not start Phase 3.

## Recommended Pi workflow

At the start of a fresh Pi session:

```text
/omarchy
```

Then provide the Phase 2 handoff.

If the context meter is around **60–65% or higher at a checkpoint**, prefer starting a fresh Pi session before the next task instead of relying on auto-compaction.

Git + this playbook + repository files are the persistent project memory.

---

# Phase 2 Goal

At the end of Phase 2, Agent Fleet must be able to:

1. Discover Hermes agent/profile identities from the local Hermes installation.
2. Read Hermes activity **read-only**.
3. Identify successful Codex-backed model calls from Hermes logs/state.
4. Normalize those calls into a stable internal event schema.
5. Produce aggregate activity summaries by:
   - Hermes agent/profile;
   - model;
   - agent + model.
6. Expose that normalized Hermes activity to the Omarchy plugin.
7. Display a simple **Hermes activity** section in the panel.
8. Preserve all Phase 1 Codex allowance behavior.
9. Store no prompt content, assistant response content, credentials, or OAuth tokens.
10. Avoid any claim that a Hermes agent consumed a specific percentage of the Codex allowance.

---

# Explicitly Out of Scope

Do **not** implement any of the following in Phase 2:

```text
Codex allowance attribution
5-hour percentage attribution
weekly percentage attribution
allowance delta correlation
snapshot history
SQLite
historical usage database
burn-rate prediction
forecasting
confidence scores
OpenClaw support
Claude support
Grok support
other providers
cross-machine sync
charts
exports
reports
background daemon
network service
web API
automatic bot configuration
modifying Hermes configuration
reading prompt bodies
reading assistant response bodies
```

If the implementation begins heading toward one of these, stop.

---

# Target Architecture

Phase 2 extends the existing architecture:

```text
                         ┌──────────────────────────┐
                         │      Agent Fleet UI      │
                         │  Codex + Hermes activity │
                         └────────────┬─────────────┘
                                      │
                 ┌────────────────────┴────────────────────┐
                 │                                         │
        ┌────────▼────────┐                       ┌────────▼─────────┐
        │ CodexUsage.qml  │                       │ HermesUsage.qml  │
        │   Phase 1       │                       │    Phase 2       │
        └────────┬────────┘                       └────────┬─────────┘
                 │                                         │
      ┌──────────▼──────────┐                   ┌──────────▼──────────┐
      │ agent-fleet-codex   │                   │ agent-fleet-hermes  │
      │   Phase 1 script    │                   │   Phase 2 script    │
      └──────────┬──────────┘                   └──────────┬──────────┘
                 │                                         │
      Omarchy/Codex local auth                    Hermes local logs/state
```

The two collectors are separate.

Do not put Hermes parsing logic into QML.

---

# Core Data Model

Phase 2 introduces a normalized Hermes activity event.

Recommended schema:

```json
{
  "timestamp": "2026-09-25T09:28:42-05:00",
  "harness": "hermes",
  "agent": "engineer",
  "provider": "openai-codex",
  "model": "gpt-6-sol",
  "sessionId": "20260924_141726_0f561f",
  "inputTokens": 196110,
  "outputTokens": 1223,
  "cacheReadTokens": 192256,
  "cacheWriteTokens": 0
}
```

## Required properties

- `timestamp`
- `harness`
- `agent`
- `provider`
- `model`
- `sessionId`
- `inputTokens`
- `outputTokens`
- `cacheReadTokens`
- `cacheWriteTokens`

## Rules

- `harness` is always `"hermes"` in Phase 2.
- `agent` is the normalized Hermes profile/bot identity.
- `provider` must come from actual Hermes activity data.
- Only Codex-backed calls relevant to this project should be included in the first implementation.
- Missing numeric token fields normalize to `0`.
- Never infer a model or provider when the source does not contain enough evidence.
- Never read prompt/message text merely to reconstruct usage metadata.

---

# Phase 2 Output Contract

Create a collector:

```text
scripts/agent-fleet-hermes
```

It should print one JSON document.

Recommended top-level schema:

```json
{
  "schemaVersion": 1,
  "harness": "hermes",
  "available": true,
  "source": {
    "type": "local",
    "profilesDiscovered": 4
  },
  "agents": [
    {
      "id": "engineer",
      "displayName": "Engineer",
      "models": [
        {
          "provider": "openai-codex",
          "model": "gpt-6-sol",
          "calls": 42,
          "inputTokens": 123456,
          "outputTokens": 4567,
          "cacheReadTokens": 100000,
          "cacheWriteTokens": 0,
          "lastActivityAt": "2026-09-25T09:28:42-05:00"
        }
      ],
      "totalCalls": 42,
      "lastActivityAt": "2026-09-25T09:28:42-05:00"
    }
  ],
  "summary": {
    "totalAgents": 1,
    "totalCalls": 42
  },
  "error": null
}
```

This is a **summary contract** for the UI.

Internally, the parser may produce normalized events first and aggregate them after.

Do not send thousands of raw events into QML.

---

# Important Semantic Rule

Phase 2 reports **activity**, not allowance contribution.

Allowed:

```text
Engineer
GPT-6 Sol
42 calls
123K input tokens
Last active 09:28
```

Not allowed:

```text
Engineer used 31% of weekly Codex
```

Not allowed:

```text
GPT-6 Sol consumed 45% of the subscription
```

Those require Phase 3 correlation with actual Codex allowance deltas.

---

# Task 1 — Hermes Discovery

## Objective

Learn the real Hermes layout on this machine before writing code.

Inspect the local Hermes installation and identify:

1. where profiles/bots are stored;
2. where activity logs live;
3. whether each profile has a separate log;
4. how session IDs are represented;
5. how successful API calls are represented;
6. which fields identify:
   - timestamp;
   - profile/agent;
   - provider;
   - model;
   - input tokens;
   - output tokens;
   - cache read;
   - cache write;
   - session ID;
7. whether unsuccessful calls are distinguishable from successful calls;
8. whether logs rotate or have historical files;
9. whether another structured source is safer than parsing free-form logs.

Likely candidate paths may include:

```text
~/.hermes/profiles/
~/.hermes/profiles/<profile>/logs/
```

These are **starting points only**. Verify locally.

Do not assume the exact schema from this document.

## Safety

Do not dump entire logs to the terminal.

Prefer targeted discovery and searches for metadata strings such as:

```text
provider=
model=
API call
session
input
output
cache
```

Redact or avoid message bodies.

## Deliverable

Create:

```text
docs/hermes-reference-notes.md
```

It should document:

- discovered paths;
- actual relevant line/schema examples with sensitive content removed;
- field mappings;
- rotation/history behavior;
- failure/success distinction;
- any uncertainty.

## Acceptance criteria

- The source format is verified from the local install.
- No prompt or response content is copied into the notes.
- A proposed event mapping exists.
- No parser has been implemented yet.

## STOP CHECKPOINT 1

Report:

1. discovered Hermes paths;
2. exact source chosen for Phase 2;
3. a sanitized example record/line;
4. proposed mapping into the normalized event schema;
5. unresolved risks or ambiguities.

Do not start Task 2 until approved.

---

# Task 2 — Parser + Normalized Event Model

## Objective

Implement a standalone Hermes parser library/module with offline fixtures.

Do **not** connect it to the UI yet.

The code should:

1. parse only the selected Hermes metadata source;
2. identify successful Codex-backed calls;
3. normalize them into event objects;
4. ignore irrelevant lines/events;
5. ignore malformed entries safely;
6. never emit prompt or response content.

## File layout

Choose a small structure, for example:

```text
scripts/
├── agent-fleet-hermes
└── lib/
    └── hermes_activity.py
```

or another locally appropriate structure.

Keep it simple.

## Fixtures

Create sanitized fixtures under:

```text
tests/fixtures/hermes/
```

Minimum fixtures:

```text
successful-codex.log
multiple-agents.log
mixed-providers.log
malformed.log
failed-calls.log
```

Fixtures must contain no real prompt text, OAuth tokens, keys, or personal message content.

## Required tests

At minimum:

- successful Codex event parses;
- correct agent/profile mapping;
- correct model mapping;
- correct provider mapping;
- correct session ID;
- input/output token counts;
- cache read count;
- missing cache write becomes 0;
- failed calls are ignored;
- non-Codex providers are ignored in Phase 2;
- malformed lines are ignored;
- unrelated log text is ignored;
- parser never emits prompt/response body fields.

## Acceptance criteria

- Tests run offline.
- Parser does not require Hermes to be running.
- Parser produces normalized events.
- No aggregation yet beyond what is useful for tests.

## STOP CHECKPOINT 2

Show:

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

and provide 2–3 sanitized normalized example events.

Do not start Task 3.

---

# Task 3 — Hermes Collector + Aggregation

## Objective

Build:

```text
scripts/agent-fleet-hermes
```

The collector should:

1. discover Hermes profiles from the verified local structure;
2. scan relevant activity data read-only;
3. parse normalized events;
4. aggregate by:
   - agent;
   - provider + model;
5. return the Phase 2 summary JSON contract.

## Time range

For Phase 2, use a small, explicit default lookback.

Recommended default:

```text
7 days
```

Reason:

- aligns well with the Codex weekly window;
- keeps scans bounded;
- avoids pretending the collector is a permanent history store.

If the local Hermes source is already bounded/rotated, document that.

Provide a test-only or CLI override only if needed for offline tests.

Do not add persistent storage.

## Aggregation rules

For each agent/model:

```text
calls
inputTokens
outputTokens
cacheReadTokens
cacheWriteTokens
lastActivityAt
```

Also:

```text
agent.totalCalls
agent.lastActivityAt
summary.totalAgents
summary.totalCalls
```

Do not calculate a "share" percentage.

Do not combine cached tokens into input unless the Hermes source already defines them that way.

Preserve each metric separately.

## Error state

Recommended:

```json
{
  "schemaVersion": 1,
  "harness": "hermes",
  "available": false,
  "source": {
    "type": "local",
    "profilesDiscovered": 0
  },
  "agents": [],
  "summary": {
    "totalAgents": 0,
    "totalCalls": 0
  },
  "error": {
    "code": "HERMES_UNAVAILABLE",
    "message": "Hermes activity information is unavailable."
  }
}
```

No raw exception paths or log contents in the UI contract.

## Acceptance criteria

```bash
./scripts/agent-fleet-hermes | jq .
```

returns valid JSON.

Tests cover:

- multiple agents;
- multiple models per agent;
- repeated calls;
- malformed data;
- missing profile directory;
- empty profile;
- lastActivityAt ordering;
- summary counts.

## STOP CHECKPOINT 3

Report:

- live collector output with sensitive fields absent;
- test results;
- discovered agents;
- discovered models;
- number of calls scanned;
- exact lookback behavior;
- working-tree state.

Do not start Task 4.

---

# Task 4 — Connect Hermes Activity to the UI

## Objective

Add a **Hermes Activity** section to the existing Agent Fleet panel.

Do not replace the Codex allowance section.

Recommended structure:

```text
AGENT FLEET

CODEX · PLUS
5-HOUR WINDOW     12% used
WEEKLY            44% used

HERMES ACTIVITY
Last 7 days

Engineer
  GPT-6 Sol        42 calls
                   123K in · 4.5K out

Oracle
  GPT-6 Astra      10 calls
  GPT-6 Sol         8 calls

Tester
  GPT-6 Luna       21 calls
```

Keep it compact.

## UI requirements

- Keep existing Phase 1 UI working.
- Do not change the meaning of the Codex bar percentage.
- Hermes section must clearly say **activity**.
- Do not show allowance contribution percentages.
- Show no prompt text.
- Show no session IDs in the main UI unless they are genuinely useful.
- Use existing Omarchy UI components and theme.
- Gracefully handle:
  - Hermes unavailable;
  - no Hermes profiles;
  - profiles with zero Codex calls;
  - missing model data;
  - collector refresh in progress.

## New QML data source

Prefer a separate:

```text
HermesUsage.qml
```

It should call:

```text
scripts/agent-fleet-hermes
```

and expose the summary record.

Do not mix Hermes parsing into `Panel.qml`.

## Refresh

Reuse or align with the existing refresh cadence where practical.

Do not create aggressive polling.

Hermes activity is local, so a 5–15 minute interval is sufficient unless an existing project pattern strongly suggests otherwise.

## Acceptance criteria

- Phase 1 Codex display remains correct.
- Hermes activity section renders real local agents.
- Agent names/models/call counts match the collector output.
- No attribution claim appears anywhere.
- Shell logs contain no plugin errors.

## STOP CHECKPOINT 4

Compare:

```bash
./scripts/agent-fleet-hermes | jq .
```

with the UI.

Report:

- agents shown;
- models shown;
- call counts;
- refresh behavior;
- shell log status;
- screenshots or textual verification.

Do not start Task 5.

---

# Task 5 — Documentation + Final Phase 2 Validation

## README updates

Document:

- Phase 2 Hermes support;
- what "activity" means;
- 7-day lookback behavior;
- which Hermes data source is read;
- privacy behavior;
- limitations;
- explicit distinction between:
  - Codex allowance;
  - Hermes activity;
  - future allowance attribution.

## Add architecture note

Include:

```text
Provider / Subscription
└── Harness
    └── Agent
        └── Model
```

For example:

```text
Codex Plus
└── Hermes
    ├── Engineer
    │   └── GPT-6 Sol
    ├── Oracle
    │   ├── GPT-6 Sol
    │   └── GPT-6 Astra
    └── Tester
        └── GPT-6 Luna
```

Make clear that this hierarchy is now **partially implemented**:

- Provider/subscription: Codex allowance display exists.
- Harness: Hermes activity exists.
- Agent/model: Hermes agent/model activity exists.
- Attribution between those layers does not yet exist.

## Final security checklist

Verify:

```text
[ ] No prompt text stored
[ ] No assistant response text stored
[ ] No OAuth token read
[ ] No API key read
[ ] No Hermes configuration modified
[ ] No first-party Omarchy files modified
[ ] No Hermes files modified
[ ] No persistent activity database created
[ ] No network service added
[ ] No allowance attribution calculated
[ ] Fixtures are sanitized
[ ] Logs do not print secrets
```

## Final tests

Run at minimum:

```bash
omarchy plugin validate .
python3 -m unittest discover -s tests -p 'test_*.py' -v
./scripts/agent-fleet-codex | jq .
./scripts/agent-fleet-hermes | jq .
git status
```

## Definition of Done

Phase 2 is complete only when all are true:

```text
[ ] Hermes source format documented
[ ] Hermes profiles discovered dynamically
[ ] Codex-backed Hermes calls parsed
[ ] Normalized event schema implemented
[ ] Aggregation by agent implemented
[ ] Aggregation by agent + model implemented
[ ] Hermes collector returns stable JSON
[ ] Hermes UI section renders
[ ] Codex Phase 1 UI still works
[ ] Offline tests pass
[ ] No prompt/response content stored
[ ] README accurately distinguishes activity from attribution
[ ] Working tree clean
[ ] Phase 3 not started
```

---

# Suggested Git Commit Sequence

Keep commits small.

Suggested sequence:

```text
docs: record hermes activity source format
feat: parse hermes codex activity
test: cover hermes activity normalization
feat: aggregate hermes agent activity
feat: render hermes activity in fleet panel
docs: document phase two behavior
```

Before every commit:

1. inspect `git diff`;
2. run relevant tests;
3. check for secrets;
4. do not push unless requested.

---

# Final Report Expected From the Coding Agent

When Phase 2 is complete, report:

1. Status.
2. Files created/modified.
3. Hermes source chosen and why.
4. Normalized event schema implemented.
5. Live discovered agents.
6. Live discovered models.
7. Aggregation semantics.
8. Lookback behavior.
9. Test commands/results.
10. UI behavior.
11. Privacy/security verification.
12. Known limitations.
13. Anything discovered that changes assumptions for Phase 3.
14. Git commit hashes.
15. Confirmation that Phase 3 was not started.

Stop after the final report.

---

# Phase 3 Preview — Do Not Implement

Phase 3 will introduce:

```text
Codex allowance snapshots
+
Hermes normalized activity intervals
=
estimated/observed agent + model allowance contribution
```

That phase must distinguish:

- directly observed allowance deltas;
- intervals with only one active agent/model;
- intervals with multiple active agents/models;
- estimated allocation;
- confidence/ambiguity.

Phase 2 must only prepare clean Hermes activity data for that future correlation.

---

# Instructions to the Coding Agent

Start with **Task 1 — Hermes Discovery only**.

Read:

```text
README.md
docs/reference-notes.md
this Phase 2 playbook
```

Inspect the current repository and Git history.

Do not modify application code yet.

Create:

```text
docs/hermes-reference-notes.md
```

Then stop at **STOP CHECKPOINT 1** and wait for approval.

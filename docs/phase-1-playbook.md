# Omarchy Agent Fleet --- Phase 1 Implementation Playbook

## Purpose

This document is the complete scope for **Phase 1 only** of **Omarchy
Agent Fleet**.

The implementation agent should behave like a junior developer working
from a precise ticket:

-   Do only the work described here.
-   Do not implement future phases.
-   Do not redesign the architecture without asking.
-   Work in small, verifiable steps.
-   Run the stated checks after every step.
-   If an assumption cannot be verified locally, stop and report it
    instead of inventing a solution.

## Product idea

Omarchy Agent Fleet will eventually help a user understand how multiple
named AI agents/bots consume a shared AI subscription allowance.

Example future hierarchy:

``` text
Provider / Subscription
└── Harness
    └── Agent
        └── Model
```

Example:

``` text
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

**Phase 1 does NOT implement that attribution yet.**

Phase 1 establishes a safe, maintainable Omarchy plugin foundation and
proves that the plugin can read and display the real Codex subscription
limits already available locally.

------------------------------------------------------------------------

# Phase 1 Goal

Create a third-party Omarchy plugin named:

**Omarchy Agent Fleet**

Suggested plugin/repository identifier:

``` text
omarchy-agent-fleet
```

At the end of Phase 1, the plugin must:

1.  Install/run as a local third-party Omarchy plugin.
2.  Show a bar widget.
3.  Open a simple panel when activated.
4.  Obtain Codex limit information locally.
5.  Display:
    -   subscription tier;
    -   5-hour usage percentage;
    -   5-hour reset time;
    -   weekly usage percentage;
    -   weekly reset time.
6.  Handle unavailable Codex/authentication gracefully.
7.  Store no prompts, credentials, OAuth tokens, or message content.
8.  Contain no Hermes parsing, attribution algorithm, history database,
    charts, or multi-provider support yet.

------------------------------------------------------------------------

# Known Reference Behavior

The installed first-party Omarchy Codex collector is:

``` text
/usr/bin/omarchy-agent-usage-codex
```

It may also appear through:

``` text
/usr/share/omarchy/bin/omarchy-agent-usage-codex
```

The first-party collector gets real subscription limits through the
authenticated Codex app-server. Conceptually it performs:

``` text
codex -s read-only -a on-request app-server
```

and requests:

``` text
initialize
account/read
account/rateLimits/read
```

The relevant response contains the plan and rate-limit windows.

Observed output from the existing Omarchy collector has this shape:

``` json
{
  "tierLabel": "plus",
  "limits": [
    {
      "label": "5h window",
      "percent": 0.03,
      "resetsAt": "2026-09-25T19:26:51+00:00"
    },
    {
      "label": "Weekly (7-day)",
      "percent": 1.0,
      "resetsAt": "2026-09-26T18:40:25+00:00"
    }
  ]
}
```

Important:

-   `percent` is normalized from 0.0 to 1.0.
-   `0.03` means 3% used.
-   `1.0` means 100% used.
-   These are subscription allowance values, not calculated token
    percentages.

------------------------------------------------------------------------

# Engineering Constraints

## MUST

-   Develop as a third-party/local plugin.
-   Keep the plugin source in the user's development
    directory/repository.
-   Treat `/usr/share/omarchy` and `/usr/bin` as read-only references.
-   Reuse existing Omarchy behavior where practical.
-   Keep data collection separate from presentation.
-   Use structured JSON between collector and UI.
-   Fail safely when Codex is unavailable.
-   Keep the implementation small.
-   Add useful comments around non-obvious integration code.
-   Commit work in small logical commits if Git is initialized.

## MUST NOT

Do not:

-   modify first-party Omarchy files;
-   modify `/usr/share/omarchy`;
-   modify `/usr/bin/omarchy-agent-usage-codex`;
-   ask for an OpenAI API key;
-   use OpenAI API billing;
-   read OAuth/token files directly;
-   copy authentication tokens;
-   log credentials;
-   store prompt text;
-   store assistant responses;
-   parse Hermes logs;
-   implement bot attribution;
-   implement SQLite;
-   implement historical snapshots;
-   implement burn-rate prediction;
-   support Claude/Grok/local models;
-   build charts;
-   add configuration screens;
-   add network services;
-   create a daemon.

Those belong to later phases.

------------------------------------------------------------------------

# Architecture for Phase 1

Use three conceptual layers:

``` text
┌──────────────────────────────┐
│ Omarchy Agent Fleet UI       │
│ bar widget + panel           │
└───────────────▲──────────────┘
                │ JSON
┌───────────────┴──────────────┐
│ Fleet Codex Collector        │
│ small local command/module   │
└───────────────▲──────────────┘
                │
┌───────────────┴──────────────┐
│ Existing local Codex auth    │
│ / app-server / Omarchy       │
└──────────────────────────────┘
```

The UI must not know how Codex authentication works.

The collector must return a stable internal record.

Recommended internal contract:

``` json
{
  "schemaVersion": 1,
  "provider": "codex",
  "available": true,
  "tier": "plus",
  "limits": {
    "session": {
      "label": "5h window",
      "usedPercent": 3.0,
      "resetsAt": "2026-09-25T19:26:51+00:00"
    },
    "weekly": {
      "label": "Weekly (7-day)",
      "usedPercent": 100.0,
      "resetsAt": "2026-09-26T18:40:25+00:00"
    }
  },
  "error": null
}
```

On failure:

``` json
{
  "schemaVersion": 1,
  "provider": "codex",
  "available": false,
  "tier": null,
  "limits": {
    "session": null,
    "weekly": null
  },
  "error": {
    "code": "CODEX_UNAVAILABLE",
    "message": "Codex usage information is unavailable."
  }
}
```

Do not put stack traces, tokens, environment dumps, or credential
information in this JSON.

------------------------------------------------------------------------

# Implementation Strategy

Prefer the smallest integration that is reliable on the user's installed
Omarchy version.

Before coding, inspect the local first-party plugin implementation.

Useful commands include:

``` bash
omarchy plugin list --json
```

``` bash
find /usr/share/omarchy -path '*agents*' -o -iname '*agent*usage*' 2>/dev/null
```

``` bash
ls -l /usr/share/omarchy/bin/omarchy-agent-usage*
```

Inspect relevant first-party plugin files and one simple third-party
bar-widget plugin.

Do not blindly copy a large plugin.

Identify:

1.  manifest format;
2.  plugin directory structure;
3.  bar-widget entry point;
4.  panel entry point;
5.  command execution pattern;
6.  refresh/timer pattern;
7.  installation/development workflow.

Write these findings in:

``` text
docs/reference-notes.md
```

Keep it short.

------------------------------------------------------------------------

# Task 1 --- Repository Scaffold

Create the repository/directory for:

``` text
omarchy-agent-fleet
```

Minimum expected structure should resemble:

``` text
omarchy-agent-fleet/
├── README.md
├── docs/
│   └── reference-notes.md
├── scripts/
│   └── agent-fleet-codex
├── tests/
│   └── ...
└── <Omarchy plugin files discovered from local references>
```

Do not invent Omarchy filenames if local examples show the correct
convention.

### Acceptance criteria

-   Repository exists.
-   README identifies the project as Omarchy Agent Fleet.
-   Plugin manifest/metadata uses the correct locally verified format.
-   No system Omarchy files have been edited.

### STOP CHECKPOINT 1

Show:

``` text
tree -a -L 3
```

and summarize what local Omarchy plugin was used as the structural
reference.

Do not continue if the plugin format is still uncertain.

------------------------------------------------------------------------

# Task 2 --- Static Plugin UI

Implement only enough UI to prove plugin integration.

Bar widget:

``` text
Fleet
```

or a small suitable icon plus `Fleet`, following existing Omarchy
conventions.

Clicking it should open a panel approximately containing:

``` text
AGENT FLEET

Codex
Status: Not loaded

Phase 1
Subscription limits
```

Do not spend time polishing visual design.

Follow existing Omarchy spacing, typography, component and theme
conventions rather than hard-coding a custom visual system.

### Acceptance criteria

-   Plugin loads without QML/runtime errors.
-   Widget is visible.
-   Clicking opens the panel.
-   Panel closes normally.
-   Existing Omarchy bar continues working.

### STOP CHECKPOINT 2

Provide:

-   screenshot or textual confirmation;
-   relevant Omarchy/plugin logs;
-   changed-file list.

Do not begin Codex integration until the static plugin works.

------------------------------------------------------------------------

# Task 3 --- Codex Collector

Create:

``` text
scripts/agent-fleet-codex
```

Its only job in Phase 1 is to return the internal JSON contract.

## Preferred first implementation

For the MVP, it is acceptable to invoke the existing:

``` text
omarchy-agent-usage-codex --limits-only
```

and transform its output into the Agent Fleet schema.

This is preferred initially because:

-   Omarchy already implements the Codex app-server protocol;
-   authentication remains owned by Codex/Omarchy;
-   we avoid duplicating security-sensitive RPC code;
-   Phase 1 stays small.

Do NOT copy the complete 600-line first-party collector.

Later phases can decide whether a direct app-server client is justified.

## Collector behavior

Successful execution:

``` bash
scripts/agent-fleet-codex
```

must output exactly one JSON document to stdout.

Diagnostic messages go to stderr.

Exit code:

``` text
0 = collector executed and returned valid structured state
```

Even an unauthenticated/unavailable state may be represented as valid
JSON instead of crashing.

### Mapping

From Omarchy:

``` text
tierLabel
limits[].label
limits[].percent
limits[].resetsAt
```

to Fleet:

``` text
tier
limits.session
limits.weekly
```

Convert normalized fractions to human percentages:

``` text
0.03 -> 3.0
1.00 -> 100.0
```

Identify windows by semantic label/window information, not merely array
position if sufficient metadata exists.

### Acceptance criteria

This command:

``` bash
./scripts/agent-fleet-codex | jq .
```

returns valid JSON.

A small test must validate at least:

-   3% session mapping;
-   100% weekly mapping;
-   tier mapping;
-   reset timestamp preservation;
-   unavailable/malformed upstream output.

### STOP CHECKPOINT 3

Show:

``` bash
./scripts/agent-fleet-codex | jq .
```

and test results.

Do not continue while collector tests fail.

------------------------------------------------------------------------

# Task 4 --- Connect Collector to UI

Connect the panel to the collector.

Required panel content:

``` text
AGENT FLEET

CODEX PLUS

5-HOUR WINDOW
3% used
Resets <formatted time>

WEEKLY
100% used
Resets <formatted time>
```

Use progress bars if an existing Omarchy component makes this
straightforward.

If not, textual percentages are sufficient for Phase 1.

The UI should clearly say **used**, not remaining.

Do not infer remaining percentages unless needed for a standard existing
component.

Refresh interval should be conservative. Follow an existing Omarchy
usage widget's convention rather than polling aggressively.

Also provide a manual refresh action only if it is trivial using
existing plugin patterns.

### Error state

If collector reports unavailable:

``` text
CODEX

Usage unavailable

Authenticate with Codex and try again.
```

Do not display raw exception text to the normal UI.

### Acceptance criteria

-   Real values match `omarchy-agent-usage-codex --limits-only`.
-   UI remains responsive.
-   Failure does not break the panel.
-   No credentials appear in logs.

### STOP CHECKPOINT 4

Compare:

``` bash
omarchy-agent-usage-codex --limits-only | jq .
```

against the values displayed by Agent Fleet.

They must agree.

------------------------------------------------------------------------

# Task 5 --- Minimal Documentation

Update README with:

## What it is

Omarchy Agent Fleet is an Omarchy plugin intended to observe AI usage
across multiple named agents and models.

## Phase 1 capability

Only Codex subscription limit display is implemented.

## Explicit future direction

Mention, but DO NOT implement:

-   Hermes agent discovery;
-   agent/model attribution;
-   historical allowance snapshots;
-   other harnesses such as OpenClaw;
-   additional providers;
-   burn-rate analytics.

## Privacy

State that Phase 1:

-   does not collect prompts;
-   does not collect responses;
-   does not read OAuth tokens;
-   does not require an OpenAI API key;
-   relies on the existing authenticated local Codex/Omarchy
    integration.

Include installation/development instructions verified against the local
Omarchy version.

------------------------------------------------------------------------

# Tests Required in Phase 1

Keep testing small.

At minimum test collector transformation using fixtures.

Fixtures:

``` text
tests/fixtures/codex-normal.json
tests/fixtures/codex-unavailable.json
tests/fixtures/codex-malformed.json
```

The normal fixture should model:

``` text
tier = plus
5h = 3%
weekly = 100%
```

Tests must not call OpenAI or require internet access.

Do not attempt full QML GUI automation in Phase 1 unless Omarchy already
provides an extremely simple established pattern.

------------------------------------------------------------------------

# Security Checklist

Before declaring Phase 1 complete, verify:

``` text
[ ] No OpenAI API key required
[ ] No OAuth token read directly
[ ] No credential copied
[ ] No prompt stored
[ ] No response content stored
[ ] No Hermes logs parsed
[ ] No secrets printed in logs
[ ] No system Omarchy files modified
[ ] Collector executes local read-only usage command only
```

If any box cannot be checked, Phase 1 is not complete.

------------------------------------------------------------------------

# Git / Development Discipline

Use small commits.

Suggested sequence:

``` text
chore: scaffold agent fleet plugin
feat: add static fleet panel
feat: add codex limit collector
test: cover codex limit normalization
feat: display codex limits in fleet panel
docs: document phase one behavior
```

Do not combine unrelated refactoring.

Before each commit:

1.  inspect `git diff`;
2.  run relevant tests;
3.  ensure no credentials/secrets are staged;
4.  use a descriptive commit message.

Do not push unless the human explicitly requests it.

------------------------------------------------------------------------

# Definition of Done

Phase 1 is complete only when all are true:

``` text
[ ] Omarchy recognizes the local plugin
[ ] Bar widget renders
[ ] Panel opens
[ ] Collector emits stable JSON
[ ] Tier displays correctly
[ ] 5-hour used percentage displays correctly
[ ] 5-hour reset displays correctly
[ ] Weekly used percentage displays correctly
[ ] Weekly reset displays correctly
[ ] Unavailable state is handled
[ ] Tests pass
[ ] README is accurate
[ ] No first-party/system files were modified
[ ] No credentials or conversation content are stored
```

------------------------------------------------------------------------

# Out of Scope / Do Not Implement

The following are explicitly **Phase 2+**:

``` text
Hermes integration
Hermes profile discovery
Engineer / Oracle / Tester identification
Model attribution
Codex allowance delta snapshots
Historical database
SQLite
Per-agent percentages
Estimated-vs-observed confidence
OpenClaw
Pi agent attribution
Multi-provider support
Claude
Grok
local model telemetry
burn rate
forecasting
charts
configuration UI
export/reporting
```

If tempted to implement one of these, stop.

------------------------------------------------------------------------

# Final Report Expected From the Implementation Agent

When Phase 1 is complete, return a concise report containing:

1.  **Status** --- complete / blocked / partially complete.
2.  **Files created or modified.**
3.  **Architecture actually implemented.**
4.  **Commands used to test it.**
5.  **Test results.**
6.  **How the plugin was installed locally.**
7.  **Screenshot or description of the final panel.**
8.  **Known limitations.**
9.  **Anything discovered about Omarchy that changes assumptions for
    Phase 2.**
10. **Git commit hashes**, if commits were created.

Do not start Phase 2.

------------------------------------------------------------------------

# Instructions to the Coding Agent

Start with **Task 1 only**.

Inspect the local Omarchy plugin conventions before creating integration
files. Do not guess the manifest or QML layout.

After Task 1 reaches **STOP CHECKPOINT 1**, report the result and wait
for approval before proceeding to Task 2.

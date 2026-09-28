# Hermes Discovery Notes — Phase 2 Task 1

Verified against the local Hermes installation on 2026-09-26 (read-only inspection only).

## 1. Discovered paths

```text
~/.hermes/                                    # Hermes root (gateway, shared state)
├── logs/agent.log                            # main/gateway-level agent log (not per-profile)
├── state.db                                  # shared global state DB (100 MB+, avoid)
└── profiles/<profile>/                       # one directory per bot/profile
    ├── profile.yaml                          # display identity (title, description, shape)
    ├── state.db                              # per-profile session DB (SQLite)
    │   ├── state.db-wal / -shm               # WAL files present on some profiles
    └── logs/
        ├── agent.log                         # per-profile free-form log (rotates ~5 MB
        │                                     # → agent.log.1, agent.log.2, agent.log.3 ...)
        ├── errors.log
        └── ...                               # gateway/gui/tui logs, not usage-relevant
```

Profiles present on this machine (9): `cloud`, `diana`, `engineer`, `oracle`,
`publisher`, `researcher`, `reviewer`, `scribe`, `tester`.

Every profile has `state.db` and `logs/agent.log`. Display names live in
`profile.yaml` → `ui_meta.hermes-bots.title` (e.g. `engineer` → "Engineer",
`oracle` → "TechLead"); one profile (`diana`) has an empty `profile.yaml`, so
the collector must fall back to the directory name for `displayName`.

## 2. Source chosen for Phase 2: **`state.db` (SQLite, per profile)** — not the free-form logs

There are two usable sources. The structured DB wins:

| Question | `logs/agent.log` | `state.db` |
|----------|------------------|------------|
| Has all metadata (model, provider, session, in/out/cache) | Yes (`API call #N:` lines) | Yes (`session_model_usage`) |
| Per-call timestamps | Yes | Via `messages.timestamp` / `sessions` |
| Failure/success separation | Yes (separate WARNING lines) | Implied: only calls that returned usage are counted |
| Incomplete? | **Yes** — see counter-example below | Complete, single query per profile |
| Requires regex over MB of free text | Yes | No |
| Rotation/historical files | Yes (`agent.log.N`, ~5 MB each) | Bounded by profile; old sessions age out |

**Counter-example found:** profile `cloud` has a Codex usage row in its
`state.db` (`gpt-5.6-terra`, 2 calls) but **zero** `API call #N` lines in
`logs/agent.log` — the log is not a reliable complete record. The DB is.

Read-only access must use the URI form
`file:<profile>/state.db?mode=ro` (works with WAL files present).

## 3. Relevant tables (schema verified locally)

`session_model_usage` — the aggregate usage ledger (one row per
session + model + provider + billing mode + task):

```sql
CREATE TABLE session_model_usage (
    session_id TEXT NOT NULL REFERENCES sessions(id),
    model TEXT NOT NULL,
    billing_provider TEXT NOT NULL DEFAULT '',
    billing_base_url TEXT NOT NULL DEFAULT '',
    billing_mode TEXT NOT NULL DEFAULT '',
    task TEXT NOT NULL DEFAULT '',
    api_call_count INTEGER NOT NULL DEFAULT 0,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens INTEGER NOT NULL DEFAULT 0,
    cache_write_tokens INTEGER NOT NULL DEFAULT 0,
    reasoning_tokens INTEGER NOT NULL DEFAULT 0,
    ...
    first_seen REAL,          -- observed as 0 (unreliable, do not use)
    last_seen REAL,           -- observed as 0 (unreliable, do not use)
    PRIMARY KEY (session_id, model, billing_provider, billing_base_url, billing_mode, task)
);
```

`sessions` — identity and time:

```sql
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,                -- e.g. 20260924_141726_0f561f
    model TEXT,
    billing_provider TEXT,
    started_at REAL NOT NULL,            -- epoch seconds (some rows may be 0)
    last_activity_at REAL,               -- epoch seconds (may be NULL)
    input_tokens ..., cache_read_tokens ...,   -- session-level rollups
    archived INTEGER, hidden INTEGER,
    ...
);
```

`messages` — per-message `timestamp REAL` epoch seconds; used only if we
need a timestamp finer than `sessions`. **Never read `content`** in Phase 2.

### Sanitized example row (no prompt/response content; real values)

```text
session_id                model        billing_provider  task               calls  in       out   cache_read  cache_write
20260907_181120_5d25bc    gpt-6-astra openai-codex      (main)             7      45897    2360  168960      0
20260907_181120_5d25bc    gpt-6-astra openai-codex      approval           2      1018     14    0           0
20260907_181120_5d25bc    gpt-6-astra openai-codex      title_generation   1      281      14    0           0
```

For reference, the corresponding free-form log line format (engineer
`agent.log`, content-free line):

```text
2026-09-07 18:11:49,459 INFO [20260907_181120_5d25bc] agent.conversation_loop: \
API call #2: model=gpt-6-astra provider=openai-codex in=11915 out=67 \
total=11982 latency=5.3s cache=10368/11915 (87%) id=resp_<redacted-id>
```

Failure lines are distinct (`WARNING [session] ... API call failed
(attempt N/3) error_type=... provider=... model=...`) and never match the
success shape — success/failure is distinguishable in both sources.

## 4. Field mapping → normalized event schema

| Required field | Source |
|----------------|--------|
| `timestamp` | epoch s → ISO 8601 in machine local tz (`America/Guayaquil`, UTC-5). Use per-session `COALESCE(sessions.last_activity_at, sessions.started_at)`; fall back to `MAX(messages.timestamp)`; if all are 0/NULL, omit rather than fake a value (see risks) |
| `harness` | constant `"hermes"` |
| `agent` | profile directory name under `~/.hermes/profiles/` (normalized identity); `displayName` from `profile.yaml` `ui_meta.hermes-bots.title` |
| `provider` | `session_model_usage.billing_provider` (must equal `openai-codex` in Phase 2) |
| `model` | `session_model_usage.model` |
| `sessionId` | `session_model_usage.session_id` |
| `inputTokens` | `session_model_usage.input_tokens` |
| `outputTokens` | `session_model_usage.output_tokens` |
| `cacheReadTokens` | `session_model_usage.cache_read_tokens` |
| `cacheWriteTokens` | `session_model_usage.cache_write_tokens` (observed 0 everywhere so far — keep the field) |

Filters / rules:

- Include only rows where `billing_provider = 'openai-codex'`.
  Other observed providers: `xai-oauth`, `github-copilot`, `copilot`,
  `custom`, `ollama-local`, `auto`, `openai-api`, `bedrock`, `` (empty) —
  all excluded in Phase 2.
- The `task` column splits a session's calls across buckets: main turn
  (empty string), `approval`, `background_review`, `title_generation`.
  Phase 2 decision: **sum all tasks** per session+model (they are real
  successful Codex calls), no exclusion.
- Missing/NULL numeric fields → normalize to `0`.
- Rows are aggregates, not per-call events; a row is one aggregate "record".
  Aggregated schema keeps the row shape (session/model/provider/timestamps)
  and lets the collector sum counts — equivalent for the UI summary.
- `reasoning_tokens`, costs, `billing_base_url`, `id=resp_...` are never
  surfaced in the Phase 2 contract.

## 5. Rotation / history behavior

- `logs/agent.log`: rotated at ~5 MB, keeps ~3 historical files per profile
  (`oracle` currently has `agent.log.1..3` spanning Aug–Sep). Older history
  is lost.
- `state.db`: no per-profile size cap observed (profile DBs range from
  ~10 MB to ~980 MB). Old sessions persist in the DB (rows from July/Aug
  still present in September data), so the DB outlives the logs, but the
  collector's 7-day lookback (Task 3) bounds the scan anyway.
- WAL: some profiles have live `state.db-wal`; use `?mode=ro` URI opens.

## 6. Success vs failure

- DB: only calls that completed and returned usage appear in
  `session_model_usage`; `failed`/`Retrying...` lines in the logs never add
  rows there. Sufficient for Phase 2's "successful calls" requirement.
- Logs: success = `API call #N:` INFO line with `in=/out=/total=`; failure =
  `API call failed (attempt X/Y)` WARNING lines. No overlap in line shape.

## 7. Uncertainties / risks

1. **Timestamps:** `first_seen`/`last_seen` in `session_model_usage` are 0 —
   unusable. `sessions.started_at` / `last_activity_at` are mostly valid
   epoch seconds, but some rows showed 0 in aggregate queries; a parser must
   treat 0/NULL as "absent" and fall back to `messages.timestamp`, then to
   omitting `lastActivityAt` for that group.
2. **task bucketing semantics:** `title_generation`/`approval`/
   `background_review` calls are auxiliary work counted against the same
   Codex subscription. Summing them is honest, but it means "42 calls" may
   include small non-conversation calls. Document as intended.
3. **profile `cloud`** shows DB usage with zero matching log lines — confirms
   DB-only approach; also means log-based fixtures must not be treated as
   ground truth.
4. **displayName source** (`profile.yaml`) is user-editable and may be
   absent; directory name is the stable identity.
5. **WAL visibility:** a concurrent write between open and query can move
   data; Phase 2 is advisory activity display, acceptable. Open mode is
   strictly read-only, no `-shm`/`-wal` writes.
6. DB format is an internal Hermes implementation (no public
   contract); a schema change in a Hermes update could break the parser.
   The parser must fail soft (empty/unavailable JSON, not a crash) and tests
   must run on fixtures, not the live DB.

## 8. Privacy verification

Inspection was read-only (`sqlite3 ... ?mode=ro`, targeted `grep`s).
No `messages.content`, no prompt/response bodies, no `auth.json`, no tokens,
no API keys were read or copied. The `id=resp_...` identifiers present in
log lines are deliberately excluded from all examples and the Phase 2
schema.

## 9. Read-only side effects (verified during Task 5 final validation, 2026-09-28)

Claim under test: "the collector never modifies Hermes state".

Method (all read-only observation plus one controlled copy experiment):

1. `sha256sum` + mtime of `state.db` and `state.db-wal` for several profiles,
   before and after a full collector run over all 9 profiles: **unchanged**.
2. File inventory of `~/.hermes/profiles` (depth 2) before/after a run:
   **same file count, no new files** — a `mode=ro` open does not create
   `-wal`/`-shm` even when they are absent (checked again on a copy of a
   WAL-mode profile with both files removed).
3. Controlled copy: `state.db`, `state.db-wal`, `state.db-shm` copied to
   `/tmp`, then opened with the collector's exact URI
   (`file:…?mode=ro`, `timeout=10`) and queried: **`-shm` mtime and content
   unchanged**. A read-only SQLite reader does not dirty the WAL index.
4. Live-tree observation over 45 s with **no** collector running: `-shm`
   mtimes moved on their own (all profiles at once, Hermes' own periodic
   cycle), which is why they also appeared to move during earlier scans.

Conclusion: Phase 2 opens Hermes databases strictly read-only and writes
nothing anywhere. **Correction to §7 item 5:** the intent was right (`mode=ro`,
no DB/WAL writes) but the wording implied the `-shm` files could be touched by
us; measurements show they are not — their mtime churn on a live tree is Hermes'
own activity, and their content checksum is stable across our scans.

Phase 3-relevant notes from the same pass:

- The live fleet is 9 profiles with `state.db` (`.deleted/` holds removed
  profiles and is correctly ignored: no `state.db` inside).
- `profile.yaml` has **no top-level `title:`** on this machine; the display name
  lives at `ui_meta.hermes-bots.title`. Profiles without `profile.yaml`
  (e.g. `diana`) fall back to the directory name, as designed.
- Hermes also keeps `state.db.fts_rebuild.lock` and
  `state.db.quarantine.lock` siblings — unrelated lock files, never opened.
- Output ordering, for the record: the collector emits `agents[]` in
  alphabetical profile order (deterministic; asserted by
  `test_agents_are_sorted_and_every_fixture_profile_present`) and models within
  an agent by `calls` desc then model name. "Busiest agent first" is a
  *display* decision in `HermesUsage.qml` (`totalCalls` desc, then display
  name), which also drops zero-call and errored agents from the rows. Phase 3
  correlation work must not depend on the display order.
- Hermes' own `hermes profile list` reports a *default* per-profile model
  (`gpt-6-terra`, `qwen3.6:35b`, `grok-4.7`, …) that has nothing to do with the
  per-session Codex usage rows we aggregate; do not confuse the two in Phase 3.

#!/usr/bin/env python3
"""Build the Agent Fleet Hermes test fixtures from scratch.

The fixtures are small, sanitized SQLite databases shaped like the
per-profile ``state.db`` files documented in ``docs/hermes-reference-notes.md``.
No live Hermes data, prompt content, credentials or real session metadata is
copied into the fixtures: every value below is invented.

Re-run after this file changes to refresh:

    python3 tests/make_hermes_fixtures.py
"""

import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TARGET = ROOT / "fixtures" / "hermes-profiles"

USAGE_TABLE = """
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
    estimated_cost_usd REAL NOT NULL DEFAULT 0,
    actual_cost_usd REAL NOT NULL DEFAULT 0,
    cost_status TEXT,
    cost_source TEXT,
    first_seen REAL,
    last_seen REAL,
    PRIMARY KEY (session_id, model, billing_provider, billing_base_url, billing_mode, task)
)"""

SESSIONS_TABLE = """
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    model TEXT,
    billing_provider TEXT,
    started_at REAL NOT NULL,
    last_activity_at REAL,
    parent_session_id TEXT
)"""

MESSAGES_TABLE = """
CREATE TABLE messages (
    id INTEGER PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    role TEXT NOT NULL,
    timestamp REAL NOT NULL
)"""

# 1790186xxx ~ 2026-09-23 18:0x UTC (2026-09-23 18:0x America/Guayaquil).
S1 = 1790186529.0            # session start (started_at)
S1_LAST = 1790219027.6      # last activity of the 20260923 session
S2 = 1790277498.0            # a later session
S2_LAST = 1790445989.0
LATER = 1790512345.0

USAGE_ROWS = [
    # (session_id, model, billing_provider, task, calls, in, out, cache_read, cache_write)
    # engineer: the openai-codex surface; all task buckets included; two sessions.
    ("20260923_180209_5d2a01", "gpt-6-astra", "openai-codex", "", 7, 45897, 2360, 168960, 0),
    ("20260923_180209_5d2a01", "gpt-6-astra", "openai-codex", "approval", 2, 1018, 14, 0, 0),
    ("20260923_180209_5d2a01", "gpt-6-astra", "openai-codex", "background_review", 3, 4740, 354, 86912, 0),
    ("20260923_180209_5d2a01", "gpt-6-astra", "openai-codex", "title_generation", 1, 281, 14, 0, 0),
    ("20260924_202338_a91b77", "gpt-6-sol", "openai-codex", "", 1, 7420, 183, 0, 0),
    # the same profile has other providers too: they must never surface.
    ("20260923_180209_5d2a01", "grok-4.7", "xai-oauth", "", 12, 90011, 4210, 120000, 0),
    ("20260924_202338_a91b77", "qwen3.6:35b", "custom", "", 5, 2210, 90, 0, 0),
    # source defaults: zero counters are values, not missing ones.
    ("20260924_202338_a91b77", "gpt-5.5", "openai-codex", "", 0, 0, 0, 0, 0),
]


def build_engineer(conn):
    conn.execute(
        f"""
        CREATE INDEX idx_usage_session ON session_model_usage(session_id)
        """)
    conn.execute(
        "INSERT INTO sessions VALUES (?, NULL, NULL, ?, ?, NULL)",
        ("20260923_180209_5d2a01", S1, S1_LAST))
    conn.execute(
        "INSERT INTO sessions VALUES (?, NULL, NULL, ?, ?, NULL)",
        ("20260924_202338_a91b77", S2, S2_LAST))
    for row in USAGE_ROWS:
        conn.execute(
            "INSERT INTO session_model_usage "
            "(session_id, model, billing_provider, billing_base_url, billing_mode, task, "
            " api_call_count, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens) "
            "VALUES (?, ?, ?, '', '', ?, ?, ?, ?, ?, ?)",
            row)


def write_profile(directory, builder, profile_yaml=None):
    directory.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(directory / "state.db")
    try:
        conn.execute(SESSIONS_TABLE)
        conn.execute(USAGE_TABLE)
        conn.execute(MESSAGES_TABLE)
        builder(conn)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.commit()
    finally:
        conn.close()
    if profile_yaml is not None:
        (directory / "profile.yaml").write_text(profile_yaml, encoding="utf-8")


def main():
    # Fresh, predictable tree.
    if TARGET.exists():
        for child in TARGET.rglob("*"):
            if child.is_file():
                child.unlink()
    for child in sorted(TARGET.glob("*"), reverse=True):
        if child.is_dir():
            child.rmdir()

    write_profile(
        TARGET / "engineer",
        build_engineer,
        profile_yaml=(
            "description: A capable agent profile.\n"
            "ui_meta:\n"
            "  hermes-bots:\n"
            "    shape: spark\n"
            "    color: '#5c7cfa'\n"
            "    title: \"Engineer\"\n"
            "    custom: true\n"
        ),
    )

    # oracle: Codex rows exist, but the session timestamps are all zero and
    # the session row itself is absent -> timestamps must be null, rows survive.
    def build_oracle(conn):
        conn.execute(
            "INSERT INTO session_model_usage "
            "(session_id, model, billing_provider, billing_base_url, billing_mode, task, "
            " api_call_count, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens) "
            "VALUES ('20260923_180209_000orx', 'gpt-6-astra', 'openai-codex', '', '', 'main', 4, 30210, 1455, 88000, 0)")
    write_profile(TARGET / "oracle", build_oracle)

    # scribe: timestamp only on the parent session.
    def build_scribe(conn):
        parent = "20260923_180209_parent"
        child = "20260923_180209_child"
        conn.execute(
            "INSERT INTO sessions VALUES (?, NULL, NULL, 0, 0, NULL)",
            (parent,))
        conn.execute(
            "INSERT INTO sessions VALUES (?, NULL, NULL, 0, ?, ?)",
            (child, LATER, parent))
        conn.execute(
            "INSERT INTO session_model_usage "
            "(session_id, model, billing_provider, billing_base_url, billing_mode, task, "
            " api_call_count, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens) "
            "VALUES (?, 'gpt-6-sol', 'openai-codex', '', '', 'main', 2, 5100, 210, 4096, 0)",
            (parent,))
        # The only usable timestamp lives on a single message; the other
        # row carries an unusable value (0): 1790480000 ~ 2026-09-25 06:13 UTC.
        conn.execute(
            "INSERT INTO messages (session_id, role, timestamp) VALUES (?, 'assistant', 1790480000.0)",
            (parent,))
        conn.execute(
            "INSERT INTO messages (session_id, role, timestamp) VALUES (?, 'user', 0)",
            (parent,))
    write_profile(TARGET / "scribe", build_scribe)

    # diana: profile.yaml is empty (no display name), and she has Codex-free
    # sessions with zero codex usage -> present, but with no records.
    def build_diana(conn):
        conn.execute(
            "INSERT INTO sessions VALUES (?, 'gpt-5.5', NULL, ?, NULL, NULL)",
            ("20260924_202338_dd1234", S2))
        conn.execute(
            "INSERT INTO session_model_usage "
            "(session_id, model, billing_provider, billing_base_url, billing_mode, task, "
            " api_call_count, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens) "
            "VALUES (?, 'gpt-5.5', 'github-copilot', '', '', 'main', 6, 12000, 900, 1500, 0)",
            ("20260924_202338_dd1234",))
    write_profile(TARGET / "diana", build_diana, profile_yaml="")

    print(f"wrote fixtures under {TARGET}")


if __name__ == "__main__":
    main()

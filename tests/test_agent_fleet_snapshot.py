#!/usr/bin/env python3
"""Agent Fleet observation snapshot tests (Phase 3, Task 2).

Runs fully offline: the store always lives in a temporary directory
(never the real state home, never ``~/.hermes``), the Hermes collector
reads the sanitized fixture profiles from
``tests/fixtures/hermes-profiles`` and the Codex collector reads the
fixture records from ``tests/fixtures``. ``--now`` is pinned so
``observedAt``, spacing and retention are deterministic, and the run is
pinned to a machine timezone so the ISO timestamps are stable:

    TZ=America/Guayaquil python3 -m unittest discover -s tests -p 'test_*.py' -v
"""

import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "agent-fleet-snapshot"
HERMES_SCRIPT = ROOT / "scripts" / "agent-fleet-hermes"
HERMES_FIXTURES = ROOT / "tests" / "fixtures" / "hermes-profiles"
CODEX_FIXTURES = ROOT / "tests" / "fixtures"
TZ = "America/Guayaquil"

NOV_1 = 1790480000.0      # 2026-09-26T22:33:20-05:00 (pinned "now")
DAY = 86400.0
COUNTER_KEYS = ("calls", "inputTokens", "outputTokens",
                "cacheReadTokens", "cacheWriteTokens")

_LOADER = SourceFileLoader("agent_fleet_hermes", str(HERMES_SCRIPT))
hermes_mod = module_from_spec(spec_from_loader(_LOADER.name, _LOADER))
_LOADER.exec_module(hermes_mod)


def expected_cumulative_models(profile_name):
    """Cumulative openai-codex counters straight from the fixture DB."""
    records = hermes_mod.load_profile(HERMES_FIXTURES / profile_name)
    if records is None:
        raise AssertionError(f"fixture profile {profile_name!r} did not load")
    models = {}
    for record in records:
        entry = models.setdefault(record["model"],
                                  {key: 0 for key in COUNTER_KEYS})
        for key in COUNTER_KEYS:
            entry[key] += record[key]
    return models


def load_snapshot_module(alias="af_snapshot_test"):
    loader = SourceFileLoader(alias, str(SCRIPT))
    mod = module_from_spec(spec_from_loader(loader.name, loader))
    loader.exec_module(mod)
    return mod


class SnapshotBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="af-snapshot-test-"))
        self.addCleanup(shutil.rmtree, str(self.tmp), ignore_errors=True)

    def state(self):
        return self.tmp / "observations.jsonl"

    def run_snapshot(self, state, codex_fixture="codex-normal.json",
                     hermes_root=HERMES_FIXTURES, now=NOV_1, extra=()):
        env = dict(os.environ, TZ=TZ)
        args = [sys.executable, str(SCRIPT),
                "--state", str(state),
                "--codex-input", str(CODEX_FIXTURES / codex_fixture)]
        if hermes_root is not None:
            args += ["--hermes-root", str(hermes_root)]
        args += ["--now", str(now), *extra]
        proc = subprocess.run(args, capture_output=True, text=True,
                              timeout=30, env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def lines(self, state):
        if not state.is_file():
            return []
        return [line for line in
                state.read_text(encoding="utf-8").splitlines() if line.strip()]


class FirstSnapshotSchemaTest(SnapshotBase):
    def test_schema_shape_is_normalized_counter_checkpoint(self):
        state = self.state()
        status = self.run_snapshot(state)
        self.assertEqual(status["status"], "written")
        self.assertIsNone(status["skippedBecause"])
        obs = json.loads(self.lines(state)[0])
        self.assertEqual(set(obs),
                         {"schemaVersion", "observedAt", "codex", "hermes"})
        self.assertEqual(obs["schemaVersion"], 1)
        self.assertIsNotNone(re.match(
            r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}$",
            obs["observedAt"]))

    def test_codex_section_shape(self):
        codex = self.first_obs()["codex"]
        self.assertEqual(set(codex),
                         {"available", "tier", "session", "weekly", "error"})
        self.assertTrue(codex["available"])
        self.assertEqual(codex["tier"], "plus")
        self.assertEqual(codex["session"],
                         {"usedPercent": 3.0,
                          "resetsAt": "2026-09-25T19:26:51+00:00"})
        self.assertEqual(codex["weekly"],
                         {"usedPercent": 100.0,
                          "resetsAt": "2026-09-26T18:40:25+00:00"})
        self.assertIsNone(codex["error"])

    def test_hermes_section_distinguishes_profile_states(self):
        obs = self.first_obs()
        hermes = obs["hermes"]
        self.assertEqual(set(hermes), {"available", "profiles"})
        self.assertTrue(hermes["available"])  # profiles root scanned
        for name, entry in hermes["profiles"].items():
            self.assertEqual(name, name.strip())
            self.assertEqual(set(entry), {"available", "models"})
            self.assertIsInstance(entry["available"], bool)
            if not entry["available"]:
                self.assertEqual(entry["models"], {})
                continue
            for model_name, counters in entry["models"].items():
                self.assertEqual(set(counters), set(COUNTER_KEYS))
                for key, value in counters.items():
                    self.assertIsInstance(value, int, key)
                    self.assertGreaterEqual(value, 0)
            expected = expected_cumulative_models(name)
            self.assertEqual(entry["models"], expected)

    def test_readable_zero_activity_profile_is_present(self):
        # diana exists, reads fine, has zero openai-codex activity:
        # present with an explicit positive flag, NOT dropped, NOT unreadable.
        entry = self.first_obs()["hermes"]["profiles"]["diana"]
        self.assertEqual(entry, {"available": True, "models": {}})

    def test_deterministic_same_input_same_line(self):
        a = self.tmp / "a.jsonl"
        b = self.tmp / "b.jsonl"
        self.run_snapshot(a)
        self.run_snapshot(b)
        self.assertEqual(self.lines(a)[0], self.lines(b)[0])

    def first_obs(self):
        if not self.state().is_file():
            self.run_snapshot(self.state())
        return json.loads(self.lines(self.state())[0])


class AppendAndDedupTest(SnapshotBase):
    def test_second_snapshot_appends_second_line(self):
        state = self.state()
        self.run_snapshot(state, now=NOV_1)
        status = self.run_snapshot(state, now=NOV_1 + 5 * DAY)
        self.assertEqual(status["status"], "written")
        obs = [json.loads(line) for line in self.lines(state)]
        self.assertEqual(len(obs), 2)
        self.assertLessEqual(obs[0]["observedAt"], obs[1]["observedAt"])

    def test_near_simultaneous_refresh_is_suppressed(self):
        state = self.state()
        self.run_snapshot(state, now=NOV_1)
        # 10 s later: inside the 60 s spacing -- no write at all.
        status = self.run_snapshot(state, now=NOV_1 + 10)
        self.assertEqual(status["status"], "skipped")
        self.assertEqual(status["skippedBecause"], "duplicate_window")
        self.assertEqual(len(self.lines(state)), 1)

    def test_outside_spacing_appends(self):
        state = self.state()
        self.run_snapshot(state, now=NOV_1)
        status = self.run_snapshot(state, now=NOV_1 + 61)
        self.assertEqual(status["status"], "written")
        self.assertEqual(len(self.lines(state)), 2)


class RetentionAndCorruptionTest(SnapshotBase):
    def test_lines_outside_retention_pruned_new_kept(self):
        state = self.state()
        self.run_snapshot(state, now=NOV_1)
        old_line = self.lines(state)[0]
        state.write_text(old_line + "\n", encoding="utf-8")
        # 16 days later: the 14-day retention window no longer covers
        # the old line, so it must be dropped by the pruning pass.
        status = self.run_snapshot(state, now=NOV_1 + 16 * DAY)
        self.assertEqual(status["status"], "written")
        self.assertEqual(status["pruned"], 1)
        lines = self.lines(state)
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0])["observedAt"],
                         datetime.fromtimestamp(
                             NOV_1 + 16 * DAY).astimezone()
                         .isoformat(timespec="seconds"))

    def test_line_just_inside_retention_kept(self):
        state = self.state()
        self.run_snapshot(state, now=NOV_1)
        state.write_text(self.lines(state)[0] + "\n", encoding="utf-8")
        # 13 days later: still inside retention.
        status = self.run_snapshot(state, now=NOV_1 + 13 * DAY)
        self.assertEqual(status["status"], "written")
        self.assertEqual(status["pruned"], 0)
        self.assertEqual(len(self.lines(state)), 2)

    def test_corrupt_line_is_tolerated_never_fatal(self):
        state = self.state()
        state.write_text(
            "this is not json at all\n"
            "\n"
            '{"schemaVersion":1,"observedAt":'
            '"2026-09-25T22:33:20-05:00","codex":{},"hermes":{}}\n',
            encoding="utf-8")
        status = self.run_snapshot(state, now=NOV_1)
        self.assertEqual(status["status"], "written")
        lines = self.lines(state)
        # The valid in-window line survives, the garbage is dropped,
        # the new observation is appended.
        self.assertEqual(len(lines), 2)
        self.assertNotIn("this is not json at all", lines)

    def test_naive_timestamp_line_is_not_trusted(self):
        state = self.state()
        state.write_text(
            '{"schemaVersion":1,"observedAt":"2026-09-26T22:33:20",'
            '"codex":{},"hermes":{}}\n',
            encoding="utf-8")
        status = self.run_snapshot(state, now=NOV_1)
        # Not counted toward spacing (written, not "duplicate") and
        # dropped on write because its stamp cannot be trusted.
        self.assertEqual(status["status"], "written")
        self.assertEqual(len(self.lines(state)), 1)


class AvailabilityIndependenceTest(SnapshotBase):
    def test_codex_unavailable_hermes_still_recorded(self):
        state = self.state()
        status = self.run_snapshot(state, codex_fixture="codex-unavailable.json")
        self.assertEqual(status["status"], "written")
        codex = json.loads(self.lines(state)[0])["codex"]
        self.assertFalse(codex["available"])
        self.assertIsNone(codex["tier"])
        self.assertIsNone(codex["session"])
        self.assertIsNone(codex["weekly"])
        self.assertIsNotNone(codex["error"])

    def test_hermes_unavailable_codex_still_recorded(self):
        missing = self.tmp / "no-such-hermes-root"
        state = self.state()
        status = self.run_snapshot(state, hermes_root=missing)
        self.assertEqual(status["status"], "written")
        obs = json.loads(self.lines(state)[0])
        self.assertFalse(obs["hermes"]["available"])
        self.assertEqual(obs["hermes"]["profiles"], {})
        self.assertTrue(obs["codex"]["available"])

    def test_both_unavailable_writes_nothing(self):
        missing = self.tmp / "no-such-hermes-root"
        state = self.state()
        status = self.run_snapshot(state, codex_fixture="codex-unavailable.json",
                                   hermes_root=missing)
        self.assertEqual(status["status"], "skipped")
        self.assertEqual(status["skippedBecause"], "empty_observation")
        self.assertFalse(state.exists(), "no store file may be created")


class PrivacyContractTest(SnapshotBase):
    def test_never_persist_sensitive_or_upstream_text(self):
        state = self.state()
        self.run_snapshot(state)
        # The unavailable Codex fixture carries usageStatusText and
        # authHelpText: neither may ever be persisted.
        self.run_snapshot(state, codex_fixture="codex-unavailable.json",
                          now=NOV_1 + 2 * DAY)
        text = state.read_text(encoding="utf-8")
        for forbidden in ("sessionId", "session_id", "resp_0", "task",
                          "displayName", "message", "authHelpText",
                          "usageStatusText", "prompts", "sessions",
                          "api_key", "usage_status"):
            self.assertNotIn(forbidden, text, forbidden)

    def test_stdout_is_exactly_one_json_document(self):
        state = self.state()
        env = dict(os.environ, TZ=TZ)
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "--state", str(state),
             "--hermes-root", str(HERMES_FIXTURES),
             "--codex-input", str(CODEX_FIXTURES / "codex-normal.json"),
             "--now", str(NOV_1)],
            capture_output=True, text=True, timeout=30, env=env)
        self.assertEqual(proc.stdout.count("\n"), 1, proc.stdout)
        json.loads(proc.stdout)


class PermissionsAndPathTest(SnapshotBase):
    def test_state_directory_0700_store_file_0600(self):
        state = self.tmp / "nested" / "dir" / "observations.jsonl"
        self.run_snapshot(state)
        dir_mode = stat.S_IMODE(state.parent.stat().st_mode)
        file_mode = stat.S_IMODE(state.stat().st_mode)
        self.assertEqual(dir_mode, 0o700)
        self.assertEqual(file_mode, 0o600)

    def test_xdg_state_home_and_fallback_resolution(self):
        # Compute the HOME-based fallback BEFORE altering the environment.
        fallback = (Path.home() / ".local" / "state" / "omarchy"
                    / "agent-fleet" / "observations.jsonl")
        snapshot = load_snapshot_module("af_snapshot_xdg")
        saved = dict(os.environ)
        try:
            os.environ["XDG_STATE_HOME"] = str(self.tmp / "xdg")
            self.assertEqual(
                snapshot.default_state_path(),
                self.tmp / "xdg" / "omarchy" / "agent-fleet"
                / "observations.jsonl")
            os.environ.pop("XDG_STATE_HOME", None)
            self.assertEqual(snapshot.default_state_path(), fallback)
            os.environ["XDG_STATE_HOME"] = "   "
            self.assertEqual(snapshot.default_state_path(), fallback)
        finally:
            os.environ.clear()
            os.environ.update(saved)


class RealStoreProtectionTest(unittest.TestCase):
    """Fixture runs must never materialize or touch the default store."""

    def setUp(self):
        self.home = Path(tempfile.mkdtemp(prefix="af-snapshot-home-"))
        self.addCleanup(shutil.rmtree, str(self.home), ignore_errors=True)
        self._real_home = os.environ.get("HOME")
        os.environ["HOME"] = str(self.home)
        os.environ.pop("XDG_STATE_HOME", None)
        self.snapshot = load_snapshot_module("af_snapshot_real")

    def tearDown(self):
        if self._real_home is not None:
            os.environ["HOME"] = self._real_home
        else:
            os.environ.pop("HOME", None)
        os.environ.pop("XDG_STATE_HOME", None)

    def test_explicit_store_never_touches_default(self):
        default = self.snapshot.default_state_path()
        self.assertEqual(
            default,
            self.home / ".local" / "state" / "omarchy"
            / "agent-fleet" / "observations.jsonl")

        section = {"available": True, "tier": "plus", "session": None,
                   "weekly": None, "error": None}
        state = self.home / "custom" / "observations.jsonl"
        status = self.snapshot.run(str(state), 1790480000.0, 60.0, 14.0,
                                   section, section)
        self.assertEqual(status["status"], "written")
        self.assertEqual(status["statePath"], str(state))
        self.assertTrue(state.is_file())
        self.assertFalse(default.exists(),
                         "explicit --state run must not create the default")

    def test_duplicate_and_empty_paths_return_before_any_write(self):
        default = self.snapshot.default_state_path()
        section = {"available": False, "tier": None, "session": None,
                   "weekly": None, "error": None}
        status = self.snapshot.run(str(default), 1790480000.0, 60.0, 14.0,
                                   section, section)
        self.assertEqual(status, {"status": "skipped",
                                  "statePath": str(default),
                                  "skippedBecause": "empty_observation",
                                  "observed": False})
        self.assertFalse(default.exists())


class ProfileObservabilityTest(SnapshotBase):
    """Checkpoint-2A contract: per-profile availability is explicit.

    A profile that is *readable with zero activity*, a profile that is
    *unreadable*, and a profile that *does not exist yet* must be
    distinguishable in stored observations, so an unreadable profile
    cannot disappear in snapshot A and reappear in snapshot B with
    lifetime counters that a later differ could misread as activity.
    (Task 3 will define: unreadable -> readable transition is NOT a
    measurable interval.)
    """

    def profiles(self, line):
        return json.loads(line)["hermes"]["profiles"]

    def make_profile(self, root, name, db_source):
        directory = root / name
        directory.mkdir(parents=True)
        shutil.copy(db_source, directory / "state.db")
        yaml_source = Path(db_source).parent / "profile.yaml"
        if yaml_source.is_file():
            shutil.copy(yaml_source, directory / "profile.yaml")
        return directory

    def test_readable_profile_with_zero_activity_is_present(self):
        # diana in the fixture root reads fine but has no Codex rows:
        # explicit available=true with empty models, not dropped.
        state = self.state()
        self.run_snapshot(state)
        self.assertEqual(self.profiles(self.lines(state)[0])["diana"],
                         {"available": True, "models": {}})

    def test_unreadable_profile_is_flagged_not_dropped(self):
        root = self.tmp / "root"
        self.make_profile(root, "healthy", HERMES_FIXTURES / "engineer" / "state.db")
        (root / "broken").mkdir()
        (root / "broken" / "state.db").write_bytes(b"not a sqlite database")

        state = self.state()
        self.run_snapshot(state, hermes_root=root)
        profiles = self.profiles(self.lines(state)[0])

        self.assertEqual(set(profiles), {"broken", "healthy"})
        self.assertEqual(profiles["broken"], {"available": False, "models": {}})
        self.assertTrue(profiles["healthy"]["available"])
        self.assertTrue(profiles["healthy"]["models"])

    def test_unreadable_profile_later_becomes_readable(self):
        root = self.tmp / "root"
        (root / "engineer").mkdir(parents=True)
        (root / "engineer" / "state.db").write_bytes(b"corrupt")

        state = self.state()
        self.run_snapshot(state, hermes_root=root, now=NOV_1)
        profiles_a = self.profiles(self.lines(state)[0])
        self.assertEqual(profiles_a["engineer"],
                         {"available": False, "models": {}})

        # Repair the profile, snapshot again.
        shutil.rmtree(root / "engineer")
        self.make_profile(root, "engineer", HERMES_FIXTURES / "engineer" / "state.db")
        self.run_snapshot(state, hermes_root=root, now=NOV_1 + 2 * DAY)
        profiles_b = self.profiles(self.lines(state)[1])

        self.assertTrue(profiles_b["engineer"]["available"])
        self.assertEqual(profiles_b["engineer"]["models"],
                         expected_cumulative_models("engineer"))
        # The two snapshots are distinguishable: A says unreadable,
        # B says readable-with-counters. Task 3 may NOT subtract A from B
        # (no baseline to subtract); this test only pins the contract.

    def test_newly_discovered_profile(self):
        root = self.tmp / "root"
        self.make_profile(root, "engineer", HERMES_FIXTURES / "engineer" / "state.db")

        state = self.state()
        self.run_snapshot(state, hermes_root=root, now=NOV_1)
        profiles_a = self.profiles(self.lines(state)[0])

        # A brand-new profile appears before the next snapshot.
        self.make_profile(root, "scribe", HERMES_FIXTURES / "scribe" / "state.db")
        self.run_snapshot(state, hermes_root=root, now=NOV_1 + 2 * DAY)
        profiles_b = self.profiles(self.lines(state)[1])

        self.assertNotIn("scribe", profiles_a,
                         "not-yet-observed profiles are ABSENT, not flagged")
        self.assertIn("scribe", profiles_b)
        self.assertEqual(profiles_b["scribe"],
                         {"available": True,
                          "models": expected_cumulative_models("scribe")})

    def test_unreadable_profile_persists_no_secrets_or_raw_errors(self):
        root = self.tmp / "root"
        (root / "broken").mkdir(parents=True)
        (root / "broken" / "state.db").write_bytes(b"garbage-not-sqlite-\x00")

        state = self.state()
        self.run_snapshot(state, hermes_root=root)

        profiles = self.profiles(self.lines(state)[0])
        entry = profiles["broken"]
        # Fixed-shape entry only: no free-text error field at all.
        self.assertEqual(set(entry), {"available", "models"})
        self.assertNotIn("error", entry)
        # No raw database error text / secrets anywhere in the store.
        text = state.read_text(encoding="utf-8")
        for forbidden in ("garbage-not-sqlite", "integrity_check",
                          "sqlite3", ".db", "Error", "exception",
                          "Traceback", "message", "/tmp"):
            self.assertNotIn(forbidden, text, forbidden)


if __name__ == "__main__":
    unittest.main()

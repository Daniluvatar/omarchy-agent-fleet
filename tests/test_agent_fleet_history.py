"""Unit/integration tests for `agent-fleet-history` (Phase 4 Task 2).

Run:  TZ=America/Guayaquil python3 -m unittest discover -s tests -p 'test_*.py' -v

Fixtures use the REAL Phase 2/3 data contract:
- Codex windows: {"usedPercent": float, "resetsAt": iso} | None;
- Hermes profiles: cumulative per-model counters (calls and token
  counters), which the interval layer differens into per-interval
  activity. Counters are CUMULATIVE: every later observation carries
  them at equal or greater values.
- All timestamps carry explicit UTC offsets (naive rejected upstream).

These tests never touch the real XDG state directory; every run passes
--state/--segments explicitly.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
HISTORY = SCRIPTS / "agent-fleet-history"

ENV = dict(os.environ)
ENV["TZ"] = "America/Guayaquil"  # deterministic local rendering of
    # segment boundaries (the Phase 3 layer renders ISO local time).

def load_module(path, alias):
    loader = SourceFileLoader(alias, str(path))
    spec = spec_from_loader(loader.name, loader)
    module = module_from_spec(spec)
    sys.modules[alias] = module
    loader.exec_module(module)
    return module

hist = load_module(HISTORY, "af_history_under_test")


# --- Real-shape fixtures --------------------------------------------------

def t(minute):
    """Timestamp for the fixture timeline: 12:00-05:00 + minute, so
    that the pinned TZ renders it back to exactly this string."""
    minutes = minute + 12 * 60
    hour, rem = divmod(minutes, 60)
    return f"2026-09-26T{hour:02d}:{rem:02d}:00-05:00"


NOW = 1800000000.0  # 2027-01-15T08:00:00+00:00


def counters(calls):
    return {"calls": calls, "inputTokens": calls * 2,
            "outputTokens": calls, "cacheReadTokens": 0,
            "cacheWriteTokens": 0}


def profile(agent, models):
    """models: {model: cumulative calls} -> one profile entry."""
    return {"available": True,
            "models": {model: counters(calls) for model, calls in
                       models.items()}}


def hermes_sec(agents):
    """agents: {agent: {model: cumulative calls}} -> hermes section."""
    return {"available": True,
            "profiles": {agent: profile(agent, models)
                         for agent, models in agents.items()}}


def win(used_percent, resets_at):
    return {"usedPercent": float(used_percent), "resetsAt": resets_at}


def obs(minute, session=None, weekly=None, hermes=None, **junk):
    row = {
        "schemaVersion": 1,
        "observedAt": t(minute),
        "codex": {
            "available": session is not None or weekly is not None,
            "tier": "plus",
            "session": session,
            "weekly": weekly,
            "error": None,
        },
        "hermes": hermes if hermes is not None
        else {"available": True, "profiles": {}},
    }
    row.update(junk)
    return row


def one_agent(count):
    return {"engineer": {"gpt-6-sol": count}}


# Timeline: W1 is closed by a reset at t90; W2 is current.
WEEKLY_OBS = [
    obs(0, weekly=win(50, "W1"), hermes=hermes_sec(one_agent(0))),
    obs(30, weekly=win(62, "W1"), hermes=hermes_sec(one_agent(12))),
    obs(60, weekly=win(70, "W1"), hermes=hermes_sec(one_agent(20))),
    obs(90, weekly=win(5, "W2"), hermes=hermes_sec(one_agent(20))),
    obs(120, weekly=win(20, "W2"), hermes=hermes_sec(one_agent(35))),
]
# W1 run: +12 (activity 12) and +8 (activity 8) -> single 20.0 total.
# W2: in-progress (+15) -> must never be persisted.

SESSION_OBS = [
    obs(0, session=win(50, "S1"), hermes=hermes_sec({"scribe": {"gpt-6-sol": 0}})),
    obs(30, session=win(75, "S1"), hermes=hermes_sec({"scribe": {"gpt-6-sol": 25}})),
    obs(60, session=win(10, "S2"), hermes=hermes_sec({"scribe": {"gpt-6-sol": 25}})),
    obs(90, session=win(30, "S2"), hermes=hermes_sec({"scribe": {"gpt-6-sol": 45}})),
]
# S1: +25 observed, all single-attributed to scribe. S2 in-progress.

UNATTRIBUTED_OBS = [
    obs(0, weekly=win(50, "W1"), hermes=hermes_sec(one_agent(0))),
    obs(30, weekly=win(62, "W1"), hermes=hermes_sec(one_agent(0))),
    obs(60, weekly=win(70, "W1"), hermes=hermes_sec(one_agent(8))),
    obs(90, weekly=win(5, "W2"), hermes=hermes_sec(one_agent(8))),
]
# I0: +12, complete observability but NO activity -> noHermes 12.
# I1: +8, activity 8 -> attributed 8. observed 20, attributed 8, 40.0%.

BREAKDOWN_OBS = [
    obs(0, weekly=win(50, "W1"),
        hermes=hermes_sec({"engineer": {"gpt-6-sol": 0},
                           "oracle": {"gpt-5.6-sol": 0}})),
    obs(30, weekly=win(70, "W1"),
        hermes=hermes_sec({"engineer": {"gpt-6-sol": 12},
                           "oracle": {"gpt-5.6-sol": 8}})),
    obs(60, weekly=win(80, "W1"),
        hermes=hermes_sec({"engineer": {"gpt-6-sol": 22},
                           "oracle": {"gpt-5.6-sol": 8}})),
    obs(90, weekly=win(5, "W2"), hermes=hermes_sec(one_agent(22))),
]
# I0: +20 shared by calls 12/8 -> engineer 12.0, oracle 8.0.
# I1: +10, only engineer active -> single 10.0.
# engineer: single 10.0 + shared 12.0 + unattributed 0; total 22.0.

SAME_IDENTITY_OBS = [
    obs(0, session=win(50, "IDENT-SAME"), weekly=win(50, "IDENT-SAME"),
        hermes=hermes_sec(one_agent(0))),
    obs(30, session=win(75, "IDENT-SAME"), weekly=win(75, "IDENT-SAME"),
        hermes=hermes_sec(one_agent(25))),
    obs(60, session=win(10, "IDENT-NEXT"), weekly=win(10, "IDENT-NEXT"),
        hermes=hermes_sec(one_agent(25))),
]
# Both windows reset at the same observed identity -> two independent
# records (session + weekly) that may share the same resetsAt string.

ZERO_OBSERVED_OBS = [
    obs(0, weekly=win(50, "ZA"), hermes=hermes_sec(one_agent(0))),
    obs(30, weekly=win(50, "ZA"), hermes=hermes_sec(one_agent(5))),
    obs(60, weekly=win(5, "ZB"), hermes=hermes_sec(one_agent(5))),
]
# Closed window ZA with ZERO observed movement -> skipped, no store.


# --- Helper ---------------------------------------------------------------

class HistoryTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="agent-fleet-hist-")
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.state = self.tmp / "observations.jsonl"
        self.segments = self.tmp / "segments.jsonl"

    def write_obs(self, rows, path=None):
        path = path or self.state
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(row) + "\n" for row in rows),
                        encoding="utf-8")
        return path

    def run_history(self, state=None, segments=None, extra=None):
        cmd = [sys.executable, str(HISTORY)]
        cmd += ["--state", str(state or self.state),
                "--segments", str(segments or self.segments),
                "--now", str(NOW)]
        cmd += extra or []
        return subprocess.run(cmd, capture_output=True, text=True, env=ENV)

    def store_records(self, path=None):
        path = path or self.segments
        if not path.is_file():
            return []
        rows = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                rows.append({"<malformed>": line})
        return rows

    def keys(self, rows=None):
        return {(row.get("window"), row.get("resetsAt"))
                for row in (rows if rows is not None
                            else self.store_records())}

    def existing_line(self, window, identity, ended_seconds):
        return json.dumps({
            "schemaVersion": 1,
            "window": window,
            "resetsAt": identity,
            "startedAt": datetime.fromtimestamp(
                ended_seconds - 7200, tz=timezone.utc).isoformat(),
            "endedAt": datetime.fromtimestamp(
                ended_seconds, tz=timezone.utc).isoformat(),
            "observedPoints": 10.0,
            "attributedPoints": 10.0,
            "unattributedPoints": 0.0,
            "coveragePercent": 100.0,
            "agents": [],
            "unattributed": {
                "noHermesActivityPoints": 0.0,
                "incompleteHermesObservabilityPoints": 0.0,
                "noCallableActivityPoints": 0.0},
        })

    def stdout_payload(self, proc):
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)


class TestCompletedSegments(HistoryTestBase):
    def test_completed_weekly_segment_persisted(self):
        self.write_obs(WEEKLY_OBS)
        payload = self.stdout_payload(self.run_history())
        rows = self.store_records()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        # Exact key set (fixed schema, nothing extra).
        self.assertEqual(
            set(row),
            {"schemaVersion", "window", "resetsAt", "startedAt",
             "endedAt", "observedPoints", "attributedPoints",
             "unattributedPoints", "coveragePercent", "agents",
             "unattributed"})
        self.assertEqual(row["schemaVersion"], 1)
        self.assertEqual(row["window"], "weekly")
        self.assertEqual(row["resetsAt"], "W1")
        # Evidence envelope = the run's first/last interval boundaries.
        self.assertEqual(row["startedAt"], t(0))
        self.assertEqual(row["endedAt"], t(60))
        # Counts are full precision and internally consistent.
        self.assertEqual(row["observedPoints"], 20.0)
        self.assertEqual(row["attributedPoints"], 20.0)
        self.assertEqual(row["unattributedPoints"], 0.0)
        self.assertEqual(row["coveragePercent"], 100.0)
        # Agent+model breakdown, sorted, no identity beyond name+model.
        self.assertEqual(row["agents"], [{
            "agent": "engineer",
            "models": [{
                "model": "gpt-6-sol",
                "observedSinglePoints": 20.0,
                "estimatedSharedPoints": 0.0,
                "totalAttributedPoints": 20.0,
            }],
            "totalAttributedPoints": 20.0,
        }])
        self.assertEqual(row["unattributed"], {
            "noHermesActivityPoints": 0.0,
            "incompleteHermesObservabilityPoints": 0.0,
            "noCallableActivityPoints": 0.0,
        })
        # Live in-progress segment (W2) is NOT persisted.
        self.assertNotIn(("weekly", "W2"), self.keys(rows))
        # stdout contract
        self.assertEqual(payload["appended"], 1)
        self.assertEqual(payload["appendedSegments"], [["weekly", "W1"]])
        self.assertEqual(payload["status"], "written")
        self.assertEqual(payload["segmentsPath"], str(self.segments))

    def test_completed_session_segment_persisted(self):
        self.write_obs(SESSION_OBS)
        self.run_history()
        rows = self.store_records()
        self.assertEqual(self.keys(rows), {("session", "S1")})
        row = rows[0]
        self.assertEqual(row["observedPoints"], 25.0)
        self.assertEqual(row["attributedPoints"], 25.0)
        self.assertEqual(row["unattributedPoints"], 0.0)
        self.assertEqual(row["coveragePercent"], 100.0)
        self.assertEqual(row["agents"][0]["agent"], "scribe")
        # Weekly is absent in this dataset -> no weekly record, and no
        # session/weekly mixing of any kind.
        self.assertNotIn(("weekly", "S1"), self.keys(rows))

    def test_window_independence_same_identity(self):
        self.write_obs(SAME_IDENTITY_OBS)
        self.run_history()
        rows = {row["window"]: row for row in self.store_records()}
        self.assertEqual(set(rows), {"session", "weekly"})
        for window in ("session", "weekly"):
            row = rows[window]
            self.assertEqual(row["resetsAt"], "IDENT-SAME")
            self.assertEqual(row["observedPoints"], 25.0)
            self.assertEqual(row["attributedPoints"], 25.0)
        # Two independent compact records (same identity string, two
        # windows, never a merged "both windows" record).
        self.assertNotIn(("both", "IDENT-SAME"), self.keys(list(rows.values())))

    def test_unattributed_buckets_present(self):
        self.write_obs(UNATTRIBUTED_OBS)
        self.run_history()
        row = self.store_records()[0]
        self.assertEqual(row["observedPoints"], 20.0)
        self.assertEqual(row["attributedPoints"], 8.0)
        self.assertEqual(row["unattributedPoints"], 12.0)
        self.assertEqual(row["coveragePercent"], 40.0)
        self.assertEqual(row["unattributed"], {
            "noHermesActivityPoints": 12.0,
            "incompleteHermesObservabilityPoints": 0.0,
            "noCallableActivityPoints": 0.0,
        })
        row_agents = row["agents"][0]
        self.assertEqual(row_agents["agent"], "engineer")
        self.assertEqual(row_agents["totalAttributedPoints"], 8.0)

    def test_agent_model_breakdown_across_kinds(self):
        self.write_obs(BREAKDOWN_OBS)
        self.run_history()
        row = self.store_records()[0]
        self.assertEqual(row["observedPoints"], 30.0)
        self.assertEqual(row["attributedPoints"], 30.0)
        self.assertEqual(row["coveragePercent"], 100.0)
        agents = {a["agent"]: a for a in row["agents"]}
        self.assertEqual(set(agents), {"engineer", "oracle"})
        self.assertEqual(agents["engineer"]["totalAttributedPoints"], 22.0)
        eng_model = agents["engineer"]["models"][0]
        self.assertEqual(eng_model["observedSinglePoints"], 10.0)
        self.assertEqual(eng_model["estimatedSharedPoints"], 12.0)
        or_model = agents["oracle"]["models"][0]
        self.assertEqual(or_model["observedSinglePoints"], 0.0)
        self.assertEqual(or_model["estimatedSharedPoints"], 8.0)

    def test_no_secrets_in_persisted_record(self):
        rows_src = [
            dict(r, promptBody="SECRET-PROMPT", responseBody="SECRET-RESPONSE",
                 sessionID="SECRET-SID")
            for r in WEEKLY_OBS]
        self.write_obs(rows_src)
        self.run_history()
        text = self.segments.read_text(encoding="utf-8")
        for secret in ("SECRET-PROMPT", "SECRET-RESPONSE", "SECRET-SID"):
            self.assertNotIn(secret, text)


class TestIncompleteOrMissing(HistoryTestBase):
    def test_zero_observed_completed_segment_is_not_persisted(self):
        self.write_obs(ZERO_OBSERVED_OBS)
        payload = self.stdout_payload(self.run_history())
        self.assertEqual(payload["status"], "skipped")
        self.assertEqual(payload["zeroObservedSkipped"], 1)
        self.assertFalse(self.segments.is_file())

    def test_missing_or_blank_identity_is_not_persisted(self):
        # Unit level: build_record must refuse blank/missing identities.
        interval = {
            "schemaVersion": 1,
            "startAt": t(0),
            "endAt": t(30),
            "codex": {
                "session": {"status": "gap", "deltaPoints": None},
                "weekly": {"status": "ok", "deltaPoints": 5.0}},
            "hermesKnown": True,
            "activity": [{
                "agent": "engineer", "model": "gpt-6-sol",
                "deltaCalls": 5, "deltaInputTokens": 10,
                "deltaOutputTokens": 5, "deltaCacheReadTokens": 0,
                "deltaCacheWriteTokens": 0}],
            "unknownProfiles": [],
            "unknownIdentities": [],
            "status": "partial",
        }
        run = [(interval, None, None)]
        self.assertIsNotNone(hist.build_record("weekly", "W1", run))
        self.assertIsNone(hist.build_record("weekly", None, run))
        self.assertIsNone(hist.build_record("weekly", "", run))
        self.assertIsNone(hist.build_record("weekly", "   ", run))
        # resets_at is None when the endpoint lacks a usable identity.
        self.assertIsNone(
            hist.resets_at(obs(0, weekly=win(50, None)), "weekly"))
        self.assertIsNone(hist.resets_at(obs(0), "weekly"))
        self.assertIsNone(hist.resets_at(
            obs(0, weekly={"usedPercent": 50.0, "resetsAt": "   "}),
            "weekly"))

    def test_no_observations_means_no_store(self):
        self.state.write_text("", encoding="utf-8")
        payload = self.stdout_payload(self.run_history())
        self.assertEqual(payload["status"], "skipped")
        self.assertFalse(self.segments.is_file())


class TestStoreSemantics(HistoryTestBase):
    def test_first_write_wins(self):
        existing = self.existing_line(
            "weekly", "W1", float(int(NOW) - 3600))
        self.segments.write_text(existing + "\n", encoding="utf-8")
        self.write_obs(WEEKLY_OBS)
        payload = self.stdout_payload(self.run_history())
        rows = self.store_records()
        self.assertEqual(self.keys(rows), {("weekly", "W1")})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["resetsAt"], "W1")
        # Original bytes preserved (existing row kept verbatim).
        self.assertTrue(self.segments.read_text(encoding="utf-8")
                        .startswith(existing))
        self.assertEqual(payload["duplicatesSkipped"], 1)
        self.assertEqual(payload["appended"], 0)

    def test_malformed_existing_line_is_dropped(self):
        self.segments.write_text(
            'MALFORMED{"broken": true\n' +
            self.existing_line("weekly", "OLD-IN-RETENTION",
                               float(int(NOW) - 86400 * 2)) + "\n",
            encoding="utf-8")
        self.write_obs(WEEKLY_OBS)
        payload = self.stdout_payload(self.run_history())
        rows = self.store_records()
        self.assertEqual(self.keys(rows),
                         {("weekly", "OLD-IN-RETENTION"),
                          ("weekly", "W1")})
        self.assertEqual(payload["pruned"], 1)
        for row in rows:
            self.assertNotIn("<malformed>", json.dumps(row))

    def test_retention_cutoff_write_time_only(self):
        old_out = self.existing_line(
            "weekly", "OLD-100", float(int(NOW) - 86400 * 100))
        old_in = self.existing_line(
            "weekly", "OLD-30", float(int(NOW) - 86400 * 30))
        bad = self.existing_line("weekly", "OLD-BAD", 123.0)
        bad = json.loads(bad)
        bad["endedAt"] = "not-a-time"
        bad = json.dumps(bad)
        self.segments.write_text(
            "\n".join([old_out, old_in, bad]) + "\n", encoding="utf-8")
        self.write_obs(WEEKLY_OBS)
        payload = self.stdout_payload(self.run_history())
        rows = self.store_records()
        self.assertEqual(self.keys(rows),
                         {("weekly", "OLD-30"), ("weekly", "W1")})
        self.assertEqual(payload["pruned"], 2)

    def test_new_records_are_not_retention_filtered(self):
        # New derivations are appended as-is; retention applies to
        # existing rows at write time only (documented semantics).
        self.write_obs(WEEKLY_OBS)
        payload = self.stdout_payload(self.run_history())
        self.assertIn(("weekly", "W1"), self.keys())
        self.assertEqual(payload["appended"], 1)


class TestContractAndDeterminism(HistoryTestBase):
    def test_stdout_exactly_one_sorted_json_object(self):
        self.write_obs(WEEKLY_OBS)
        proc = self.run_history()
        payload = self.stdout_payload(proc)
        self.assertEqual(
            set(payload),
            {"appended", "appendedSegments",
             "duplicatesSkipped", "missingIdentitySkipped", "pruned",
             "retentionDays", "schemaVersion", "segmentsPath", "status",
             "zeroObservedSkipped"})
        expected = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        self.assertEqual(proc.stdout, expected + "\n")

    def test_default_paths_via_xdg_state_home(self):
        isolated = self.tmp / "xdg"
        state_dir = isolated / "omarchy" / "agent-fleet"
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "observations.jsonl").write_text(
            "".join(json.dumps(r) + "\n" for r in WEEKLY_OBS),
            encoding="utf-8")
        env = dict(ENV, XDG_STATE_HOME=str(isolated))
        proc = subprocess.run(
            [sys.executable, str(HISTORY), "--now", str(NOW)],
            capture_output=True, text=True, env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["segmentsPath"],
                         str(state_dir / "segments.jsonl"))
        self.assertEqual(payload["appended"], 1)
        self.assertTrue((state_dir / "segments.jsonl").is_file())

    def test_store_permissions(self):
        self.write_obs(WEEKLY_OBS)
        self.run_history()
        self.assertEqual(self.segments.stat().st_mode & 0o777, 0o600)
        self.assertEqual(
            self.segments.parent.stat().st_mode & 0o777, 0o700)

    def test_deterministic_byte_identical_output(self):
        dirs = []
        for i in range(3):
            d = Path(tempfile.mkdtemp(prefix="af-hist-det-"))
            self.addCleanup(shutil.rmtree, d, ignore_errors=True)
            (d / "observations.jsonl").write_text(
                "".join(json.dumps(r) + "\n" for r in WEEKLY_OBS),
                encoding="utf-8")
            p = subprocess.run(
                [sys.executable, str(HISTORY),
                 "--state", str(d / "observations.jsonl"),
                 "--segments", str(d / "segments.jsonl"),
                 "--now", str(NOW)],
                capture_output=True, text=True, env=ENV)
            self.assertEqual(p.returncode, 0, p.stderr)
            dirs.append(d)
        a = (dirs[0] / "segments.jsonl").read_bytes()
        self.assertEqual((dirs[1] / "segments.jsonl").read_bytes(), a)
        self.assertEqual((dirs[2] / "segments.jsonl").read_bytes(), a)

    def test_existing_bytes_preserved_and_appended_sorted(self):
        prefix = self.existing_line(
            "weekly", "A-Z-KEEP", float(int(NOW) - 86400)) + "\n"
        self.segments.write_text(prefix, encoding="utf-8")
        self.write_obs(WEEKLY_OBS)
        content = subprocess.run(
            [sys.executable, str(HISTORY),
             "--state", str(self.state), "--segments", str(self.segments),
             "--now", str(NOW)],
            capture_output=True, text=True, env=ENV)
        text = self.segments.read_text(encoding="utf-8")
        self.assertTrue(text.startswith(prefix))
        self.assertEqual(self.keys(), {("weekly", "A-Z-KEEP"),
                                       ("weekly", "W1")})


class TestListMode(HistoryTestBase):
    """Phase 5 Task 6: the read-only ``--list`` mode that feeds the panel's
    Recent Segments section. The contract under test: newest-first order,
    both windows coexisting, persisted fidelity, malformed lines ignored,
    strictly read-only behavior, and a single normalized JSON document on
    stdout. The command here NEVER passes ``--state`` — the list mode must
    not need or touch the observations store."""

    def run_list(self, segments=None, extra=None):
        cmd = [sys.executable, str(HISTORY), "--list",
               "--segments", str(segments or self.segments)]
        cmd += extra or []
        return subprocess.run(cmd, capture_output=True, text=True, env=ENV)

    def payload(self, proc):
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def row(self, **overrides):
        base = {
            "schemaVersion": 1,
            "window": "weekly",
            "resetsAt": "W1",
            "startedAt": "2026-09-22T00:00:00-05:00",
            "endedAt": "2026-09-29T00:00:00-05:00",
            "observedPoints": 42.0,
            "attributedPoints": 35.0,
            "unattributedPoints": 7.0,
            "coveragePercent": 83.33333333333334,
            "agents": [],
            "unattributed": {
                "noHermesActivityPoints": 7.0,
                "incompleteHermesObservabilityPoints": 0.0,
                "noCallableActivityPoints": 0.0},
        }
        base.update(overrides)
        return base

    def write_store(self, rows):
        self.segments.write_text(
            "".join(json.dumps(r) + "\n" if isinstance(r, dict)
                    else r + "\n" for r in rows),
            encoding="utf-8")

    def test_missing_store_is_normal_empty(self):
        target = self.tmp / "elsewhere" / "segments.jsonl"
        proc = self.run_list(segments=target)
        payload = self.payload(proc)
        self.assertEqual(payload["records"], [])
        self.assertEqual(payload["total"], 0)
        self.assertEqual(payload["segmentsPath"], str(target))
        # No store — and no parent directory — is created by listing.
        self.assertFalse(target.exists())
        self.assertFalse((self.tmp / "elsewhere").exists())

    def test_newest_first_and_windows_coexist(self):
        oldest_week = self.row(resetsAt="W-OLD",
                               startedAt="2026-09-15T00:00:00-05:00",
                               endedAt="2026-09-22T00:00:00-05:00")
        mid_session = self.row(window="session", resetsAt="S-MID",
                               startedAt="2026-09-26T08:30:00-05:00",
                               endedAt="2026-09-26T13:30:00-05:00")
        newest_week = self.row()  # ended 2026-09-29
        self.write_store([newest_week, mid_session, oldest_week])
        payload = self.payload(self.run_list())
        self.assertEqual(
            [(r["window"], r["resetsAt"]) for r in payload["records"]],
            [("weekly", "W1"), ("session", "S-MID"), ("weekly", "W-OLD")])
        self.assertEqual(payload["total"], 3)

    def test_persisted_fidelity_no_rederivation(self):
        self.write_store([self.row()])
        payload = self.payload(self.run_list())
        self.assertEqual(payload["records"], [self.row()])
        # High-precision floats are rendered verbatim, full precision.
        self.assertEqual(
            payload["records"][0]["coveragePercent"], 83.33333333333334)

    def test_ignores_malformed_and_incomplete_lines(self):
        good = self.row()
        no_window = dict(self.row())
        del no_window["window"]
        blank_identity = self.row()
        blank_identity["resetsAt"] = "   "
        no_started = dict(self.row())
        del no_started["startedAt"]
        no_ended = dict(self.row())
        del no_ended["endedAt"]
        bad_ended = self.row(endedAt="not-a-time")
        no_observed = dict(self.row())
        del no_observed["observedPoints"]
        self.write_store(["GARBAGE{\"broken\": true",
                          "[1, 2, 3]",
                          no_window, blank_identity, no_started, no_ended,
                          bad_ended, no_observed, good])
        payload = self.payload(self.run_list())
        self.assertEqual(payload["records"], [good])
        self.assertEqual(payload["total"], 1)

    def test_read_only_store_bytes_and_mtime_untouched(self):
        self.write_store([self.row(),
                          self.row(window="session", resetsAt="S1",
                                   startedAt="2026-09-29T08:30:00-05:00",
                                   endedAt="2026-09-29T13:30:00-05:00",
                                   observedPoints=18.0,
                                   attributedPoints=18.0,
                                   unattributedPoints=0.0,
                                   coveragePercent=100.0)])
        before_bytes = self.segments.read_bytes()
        before_mtime = self.segments.stat().st_mtime_ns
        self.payload(self.run_list())
        self.assertEqual(self.segments.read_bytes(), before_bytes)
        self.assertEqual(self.segments.stat().st_mtime_ns, before_mtime)

    def test_no_observations_store_involved(self):
        self.write_store([self.row()])
        # No observations file at all in the temp tree; listing must
        # succeed without one and must not create one.
        self.assertFalse(self.state.exists())
        proc = self.run_list()
        payload = self.payload(proc)
        self.assertEqual(payload["total"], 1)
        self.assertFalse(self.state.exists())

    def test_ties_keep_stable_file_order(self):
        a = self.row(resetsAt="TIE-A")
        b = self.row(resetsAt="TIE-B")
        self.write_store([a, b])
        payload = self.payload(self.run_list())
        self.assertEqual([r["resetsAt"] for r in payload["records"]],
                         ["TIE-A", "TIE-B"])

    def test_retention_is_write_time_only_list_shows_all(self):
        # A record older than the 90-day retention window is still shown:
        # retention is a write-time write-policy, never a read-time filter.
        old = self.existing_line(
            "weekly", "OLD-100D", float(int(NOW) - 86400 * 100))
        self.segments.write_text(old + "\n", encoding="utf-8")
        payload = self.payload(self.run_list())
        self.assertEqual([r["resetsAt"]
                          for r in payload["records"]], ["OLD-100D"])

    def test_single_sorted_json_document(self):
        self.write_store([self.row()])
        proc = self.run_list()
        payload = self.payload(proc)
        self.assertEqual(set(payload), {"records", "segmentsPath", "total"})
        expected = json.dumps(payload, separators=(",", ":"),
                              sort_keys=True)
        self.assertEqual(proc.stdout, expected + "\n")
        self.assertEqual("", proc.stderr)


if __name__ == "__main__":
    unittest.main()

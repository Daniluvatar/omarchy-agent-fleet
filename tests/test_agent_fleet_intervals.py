#!/usr/bin/env python3
"""Agent Fleet interval builder tests (Phase 3, Task 3).

Pure, fully offline: builds interval records from in-memory
observations shaped like real ``agent-fleet-snapshot`` lines. No store
files, no network, no live Hermes/Codex.

    TZ=America/Guayaquil python3 -m unittest discover -s tests -p 'test_*.py' -v
"""

import json
import subprocess
import sys
import tempfile
import unittest
import shutil
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "agent-fleet-intervals"

T0 = "2026-09-26T12:00:00-05:00"
T1 = "2026-09-26T12:10:00-05:00"
RESET_SESSION = "2026-09-26T19:06:35+00:00"
RESET_WEEKLY = "2026-10-01T19:06:35+00:00"


def make_intervals_module(alias):
    loader = SourceFileLoader(alias, str(SCRIPT))
    mod = module_from_spec(spec_from_loader(loader.name, loader))
    loader.exec_module(mod)
    return mod


iv = make_intervals_module("af_intervals_under_test")

SESSION = 10.0
WEEKLY = 50.0


def codex(available=True, session=(SESSION, RESET_SESSION),
          weekly=(WEEKLY, RESET_WEEKLY)):
    def win(shape):
        if shape is None:
            return None
        return {"usedPercent": shape[0], "resetsAt": shape[1]}
    return {
        "available": bool(available),
        "tier": "plus" if available else None,
        "session": win(session) if available else None,
        "weekly": win(weekly) if available else None,
        "error": None if available else "CODEX_UNAVAILABLE",
    }


def counters(*values):
    order = ("calls", "inputTokens", "outputTokens",
             "cacheReadTokens", "cacheWriteTokens")
    return {key: value for key, value in zip(order, values)}


def profile(available, models):
    return {"available": bool(available), "models": models}


def hermes(available=True, profiles=None):
    return {
        "available": bool(available),
        "profiles": {} if profiles is None else profiles,
    }


def observation(at, codex_section=None, hermes_section=None):
    return {
        "schemaVersion": 1,
        "observedAt": at,
        "codex": codex() if codex_section is None else codex_section,
        "hermes": (hermes() if hermes_section is None
                   else hermes_section),
    }


def both_readable(models_a, models_b, agent="engineer"):
    return (
        hermes(True, {agent: profile(True, models_a)}),
        hermes(True, {agent: profile(True, models_b)}),
    )


class IntervalContractTest(unittest.TestCase):
    def interval(self, hermes_a, hermes_b, codex_a=None, codex_b=None,
                 at_a=T0, at_b=T1):
        obs_a = observation(at_a, codex_a, hermes_a)
        obs_b = observation(at_b, codex_b, hermes_b)
        return iv.build_interval(obs_a, obs_b)

    # 1. ordinary positive delta
    def test_ordinary_positive_delta(self):
        models_a = {"gpt-6-sol": counters(4, 1000, 80, 10, 0)}
        models_b = {"gpt-6-sol": counters(9, 3200, 210, 10, 0)}
        record = self.interval(
            *both_readable(models_a, models_b),
            codex_a=codex(), codex_b=codex(session=(16.0, RESET_SESSION)))
        self.assertIsNotNone(record)
        self.assertEqual(record["codex"]["session"],
                         {"status": "ok", "deltaPoints": 6.0})
        self.assertEqual(record["codex"]["weekly"],
                         {"status": "ok", "deltaPoints": 0.0})
        self.assertEqual(record["activity"], [
            {"agent": "engineer", "model": "gpt-6-sol",
             "deltaCalls": 5, "deltaInputTokens": 2200,
             "deltaOutputTokens": 130, "deltaCacheReadTokens": 0,
             "deltaCacheWriteTokens": 0}])
        self.assertEqual(record["unknownProfiles"], [])
        self.assertEqual(record["unknownIdentities"], [])
        self.assertEqual(record["status"], "complete")
        self.assertEqual(record["startAt"], T0)
        self.assertEqual(record["endAt"], T1)

    # 2. zero Codex delta
    def test_zero_codex_delta(self):
        record = self.interval(*both_readable({}, {}))
        self.assertEqual(record["codex"]["session"],
                         {"status": "ok", "deltaPoints": 0.0})
        self.assertEqual(record["codex"]["weekly"],
                         {"status": "ok", "deltaPoints": 0.0})
        self.assertEqual(record["status"], "complete")

    # 3. missing Codex at start
    def test_missing_codex_at_start(self):
        record = self.interval(*both_readable({}, {}),
                               codex_a=codex(available=False))
        self.assertEqual(record["codex"]["session"],
                         {"status": "gap", "deltaPoints": None})
        self.assertEqual(record["codex"]["weekly"],
                         {"status": "gap", "deltaPoints": None})
        # Hermes is still diffable -> partial, not unknown.
        self.assertEqual(record["status"], "partial")

    # 4. missing Codex at end
    def test_missing_codex_at_end(self):
        record = self.interval(*both_readable({}, {}),
                               codex_b=codex(available=False))
        self.assertEqual(record["codex"]["session"]["status"], "gap")
        self.assertEqual(record["codex"]["weekly"]["status"], "gap")
        self.assertEqual(record["status"], "partial")

    # 5. weekly reset
    def test_weekly_reset(self):
        new_weekly = (0.0, RESET_SESSION)  # new window + counter restart
        record = self.interval(
            *both_readable({}, {}),
            codex_b=codex(weekly=new_weekly))
        self.assertEqual(record["codex"]["weekly"],
                         {"status": "reset_boundary", "deltaPoints": None})
        # Session window unaffected -> independent statuses.
        self.assertEqual(record["codex"]["session"],
                         {"status": "ok", "deltaPoints": 0.0})
        self.assertEqual(record["status"], "partial")

    # 6. 5-hour / session reset
    def test_session_reset(self):
        record = self.interval(
            *both_readable({}, {}),
            codex_b=codex(session=(1.0, RESET_WEEKLY)))  # new reset window
        self.assertEqual(record["codex"]["session"],
                         {"status": "reset_boundary", "deltaPoints": None})
        self.assertEqual(record["codex"]["weekly"]["status"], "ok")
        self.assertEqual(record["status"], "partial")

    def test_session_percentage_decrease_is_boundary(self):
        record = self.interval(
            *both_readable({}, {}),
            codex_b=codex(session=(4.0, RESET_SESSION)))
        self.assertEqual(record["codex"]["session"],
                         {"status": "reset_boundary", "deltaPoints": None})

    # 7. Hermes counter increase
    def test_hermes_counter_increase(self):
        models_a = {"gpt-6-sol": counters(1, 10, 2, 0, 0)}
        models_b = {"gpt-6-sol": counters(2, 11, 3, 1, 0)}
        record = self.interval(*both_readable(models_a, models_b))
        entry = record["activity"][0]
        self.assertEqual(entry["agent"], "engineer")
        self.assertEqual(entry["model"], "gpt-6-sol")
        self.assertEqual((entry["deltaCalls"], entry["deltaInputTokens"],
                          entry["deltaOutputTokens"],
                          entry["deltaCacheReadTokens"],
                          entry["deltaCacheWriteTokens"]),
                         (1, 1, 1, 1, 0))

    # 8. unchanged counters -> no activity, not unknown
    def test_unchanged_counters_emit_nothing(self):
        models = {"gpt-6-sol": counters(7, 100, 5, 2, 1)}
        record = self.interval(
            *both_readable(models, dict(models)))
        self.assertEqual(record["activity"], [])
        self.assertEqual(record["unknownIdentities"], [])
        self.assertEqual(record["unknownProfiles"], [])
        self.assertEqual(record["status"], "complete")

    # 9. counter decrease -> continuity unknown, never negative
    def test_counter_decrease_is_continuity_unknown(self):
        models_a = {"gpt-6-sol": counters(9, 500, 40, 5, 0)}
        models_b = {"gpt-6-sol": counters(2, 100, 10, 1, 0)}  # decrease
        record = self.interval(*both_readable(models_a, models_b))
        # No fabricated/negative deltas for that identity.
        self.assertEqual(record["activity"], [])
        self.assertEqual(record["unknownIdentities"],
                         ["engineer/gpt-6-sol"])
        self.assertEqual(record["status"], "partial")

    # 10. unreadable -> readable profile
    def test_unreadable_then_readable_profile_is_unknown(self):
        readable = {"gpt-6-sol": counters(3, 90, 5, 1, 0)}
        record = self.interval(
            hermes(True, {"oracle": profile(False, {})}),
            hermes(True, {"oracle": profile(True, readable)}))
        self.assertEqual(record["unknownProfiles"], ["oracle"])
        self.assertEqual(record["activity"], [])
        self.assertEqual(record["status"], "partial")

    # 11. readable -> unreadable profile
    def test_readable_then_unreadable_profile_is_unknown(self):
        record = self.interval(
            hermes(True, {"oracle": profile(True,
                                            {"gpt-6-sol": counters(3, 90, 5, 1, 0)})}),
            hermes(True, {"oracle": profile(False, {})}))
        self.assertEqual(record["unknownProfiles"], ["oracle"])
        self.assertEqual(record["activity"], [])
        self.assertEqual(record["status"], "partial")

    # 12. newly discovered profile at B -> baseline only
    def test_newly_discovered_profile_is_baseline(self):
        record = self.interval(
            hermes(True, {}),
            hermes(True, {"scribe": profile(True,
                                            {"gpt-6-sol": counters(12, 400, 30, 0, 0)})}))
        self.assertEqual(record["unknownProfiles"], ["scribe"])
        self.assertEqual(record["activity"], [],
                         "B's lifetime counters are NOT interval activity")
        self.assertEqual(record["status"], "partial")

    # 13. profile disappearing at B
    def test_disappearing_profile_is_unknown(self):
        record = self.interval(
            hermes(True, {"diana": profile(True,
                                           {"gpt-6-sol": counters(1, 10, 1, 0, 0)})}),
            hermes(True, {}))
        self.assertEqual(record["unknownProfiles"], ["diana"])
        self.assertEqual(record["activity"], [])
        self.assertEqual(record["status"], "partial")

    # 14. new model under an already-readable profile
    def test_new_model_under_readable_profile_is_activity(self):
        models_a = {"gpt-6-sol": counters(4, 100, 10, 0, 0)}
        models_b = dict(
            models_a,
            **{"gpt-5.6-luna": counters(2, 80, 7, 3, 0)})
        models_b["gpt-6-sol"] = dict(models_a["gpt-6-sol"])  # unchanged
        record = self.interval(*both_readable(models_a, models_b))
        self.assertEqual(len(record["activity"]), 1)
        entry = record["activity"][0]
        self.assertEqual(entry["model"], "gpt-5.6-luna")
        self.assertEqual((entry["deltaCalls"], entry["deltaInputTokens"],
                          entry["deltaOutputTokens"],
                          entry["deltaCacheReadTokens"],
                          entry["deltaCacheWriteTokens"]),
                         (2, 80, 7, 3, 0))
        self.assertEqual(record["unknownIdentities"], [])
        self.assertEqual(record["status"], "complete")

    def test_model_row_missing_at_b_is_identity_unknown(self):
        record = self.interval(
            *both_readable({"gpt-6-sol": counters(1, 10, 1, 0, 0)}, {}))
        self.assertEqual(record["unknownIdentities"],
                         ["engineer/gpt-6-sol"])
        self.assertEqual(record["activity"], [])

    # 15. same model under two agents stays separate
    def test_same_model_two_agents_stays_separate(self):
        a = {"gpt-6-sol": counters(1, 10, 1, 0, 0)}
        b = {"gpt-6-sol": counters(2, 20, 2, 0, 0)}
        record = self.interval(
            hermes(True, {"engineer": profile(True, a),
                          "oracle": profile(True, a)}),
            hermes(True, {"engineer": profile(
                             True, {"gpt-6-sol": counters(3, 30, 3, 0, 0)}),
                          "oracle": profile(
                             True, {"gpt-6-sol": counters(9, 90, 9, 0, 0)})}))
        self.assertEqual(len(record["activity"]), 2)
        by_agent = {entry["agent"]: entry for entry in record["activity"]}
        self.assertEqual(by_agent["engineer"]["deltaCalls"], 2)
        self.assertEqual(by_agent["oracle"]["deltaCalls"], 8)
        self.assertEqual(record["status"], "complete")

    # 16. duplicate observations
    def test_duplicate_or_reversed_observation_yields_no_interval(self):
        record = self.interval(*both_readable({}, {}), at_a=T0, at_b=T0)
        self.assertIsNone(record)
        obs_a = observation(T0)
        self.assertIsNone(iv.build_interval(obs_a, obs_a))
        # Reversed order also yields no interval.
        self.assertIsNone(self.interval(
            *both_readable({}, {}), at_a=T1, at_b=T0))

    # 17. null / invalid timestamps
    def test_null_or_invalid_timestamps_yield_no_interval(self):
        for bad in (None, "", "  ", "not-a-time", "2026-09-26T12:00:00",
                    "2026-13-45T99:99:99+00:00"):
            self.assertIsNone(
                self.interval(*both_readable({}, {}), at_a=bad), bad)
            self.assertIsNone(
                self.interval(*both_readable({}, {}), at_b=bad), bad)
        obs_b = observation(None)
        self.assertIsNone(iv.build_interval(observation(T0), obs_b))

    def test_invalid_structure_yields_no_interval(self):
        broken = {"observedAt": T0, "codex": "nope",
                  "hermes": {"available": True, "profiles": {}}}
        self.assertIsNone(iv.build_interval(broken, observation(T1)))
        missing = {"observedAt": T0, "hermes": {
            "available": True, "profiles": {}}}
        self.assertIsNone(iv.build_interval(missing, observation(T1)))

    def test_hermes_section_unavailable_endpoints(self):
        record_a = observation(T0, None, hermes(False, None))
        record_b = observation(T1, None, hermes(True, {}))
        record = iv.build_interval(record_a, record_b)
        self.assertFalse(record["hermesKnown"])
        self.assertEqual(record["activity"], [])
        # Codex fully missing too -> total unknown.
        both = iv.build_interval(
            observation(T0, codex(available=False), hermes(False, None)),
            observation(T1, codex(available=False), hermes(False, None)))
        self.assertEqual(both["status"], "unknown")


class BuildIntervalsSequenceTest(unittest.TestCase):
    def observations(self):
        base = {"gpt-6-sol": counters(1, 10, 1, 0, 0)}
        grown = {"gpt-6-sol": counters(3, 30, 9, 2, 0)}
        return [
            observation("2026-09-26T10:00:00-05:00", None,
                        hermes(True, {"engineer": profile(True, base)})),
            observation("2026-09-26T11:00:00-05:00", None,
                        hermes(True, {"engineer": profile(True, grown)})),
            observation("2026-09-26T12:00:00-05:00",
                        codex(available=False),
                        hermes(True, {"engineer": profile(True, grown)})),
        ]

    def test_consecutive_pairs_produce_records_in_order(self):
        intervals = iv.build_intervals(self.observations())
        self.assertEqual(len(intervals), 2)
        self.assertEqual(
            [entry["agent"] for entry in intervals[0]["activity"]],
            ["engineer"])
        self.assertEqual(intervals[1]["codex"]["session"]["status"], "gap")
        self.assertEqual(intervals[1]["activity"], [])
        self.assertEqual(intervals[1]["status"], "partial")

    def test_malformed_observation_breaks_both_boundaries(self):
        observations = self.observations()
        observations[1] = {"observedAt": None}
        intervals = iv.build_intervals(observations)
        self.assertEqual(intervals, [])
        # A malformed middle observation can never merge 0 -> 2: neither
        # boundary around it is measurable.
        self.assertIsNone(iv.build_interval(observations[0], observations[1]))
        self.assertIsNone(iv.build_interval(observations[1], observations[2]))

    def test_non_list_input(self):
        self.assertEqual(iv.build_intervals(None), [])
        self.assertEqual(iv.build_intervals({}), [])


class CliOfflineTest(unittest.TestCase):
    def stdout_contracts(self):
        script = ROOT / "scripts" / "agent-fleet-intervals"
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "observations.jsonl"
            a = observation(T0, None,
                            hermes(True, {"engineer":
                                         profile(True, counters(1, 1, 1, 0, 0))}))
            b = observation(T1, None,
                            hermes(True, {"engineer":
                                         profile(True, counters(2, 2, 2, 0, 0))}))
            state.write_text(
                "\n" + json.dumps(a) + "\n" + json.dumps(b) + "\n",
                encoding="utf-8")
            proc = subprocess.run(
                [sys.executable, str(script), "--state", str(state)],
                capture_output=True, text=True, timeout=30)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            # Exactly one JSON document on stdout.
            self.assertEqual(proc.stdout.count("\n"), 1)
            payload = json.loads(proc.stdout)
            self.assertEqual(len(payload["intervals"]), 1)
            self.assertEqual(payload["intervals"][0]["activity"][0],
                             {"agent": "engineer", "model": "gpt-6-sol",
                              "deltaCalls": 1, "deltaInputTokens": 1,
                              "deltaOutputTokens": 1,
                              "deltaCacheReadTokens": 0,
                              "deltaCacheWriteTokens": 0})
            # Missing state file: still exactly one JSON document.
            missing = Path(tmp) / "nope" / "observations.jsonl"
            proc = subprocess.run(
                [sys.executable, str(script), "--state", str(missing)],
                capture_output=True, text=True, timeout=30)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(json.loads(proc.stdout), {"intervals": []})


if __name__ == "__main__":
    unittest.main()

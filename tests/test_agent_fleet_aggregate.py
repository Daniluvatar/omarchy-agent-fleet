#!/usr/bin/env python3
"""Agent Fleet attribution aggregation tests (Phase 3, Task 5).

Pure, fully offline: aggregates Task 3 interval records (which the
aggregation layer attributes itself via the frozen Task 4 engine).
No store access inside `summarize`, no UI, no refresh/snapshot wiring.

    TZ=America/Guayaquil python3 -m unittest discover -s tests -p 'test_*.py' -v
"""

import json
import math
import subprocess
import sys
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "agent-fleet-aggregate"


def make_module(alias):
    loader = SourceFileLoader(alias, str(SCRIPT))
    mod = module_from_spec(spec_from_loader(loader.name, loader))
    loader.exec_module(mod)
    return mod


agg = make_module("af_aggregate_under_test")


def t(minute):
    return f"2026-09-26T{12 + minute // 60:02d}:{minute % 60:02d}:00-05:00"


class AggregationContractTest(unittest.TestCase):
    def interval(self, n, session=("gap", None), weekly=("gap", None),
                 activity=None, hermes_known=True, unknown_profiles=None,
                 unknown_identities=None):
        return {
            "schemaVersion": 1,
            "startAt": t(30 * n),
            "endAt": t(30 * n + 30),
            "codex": {
                "session": {"status": session[0], "deltaPoints": session[1]},
                "weekly": {"status": weekly[0], "deltaPoints": weekly[1]},
            },
            "hermesKnown": bool(hermes_known),
            "activity": list(activity or []),
            "unknownProfiles": list(unknown_profiles or []),
            "unknownIdentities": list(unknown_identities or []),
            "status": "partial",
        }

    def act(self, agent, model, calls=0, in_tok=0):
        return {"agent": agent, "model": model, "deltaCalls": calls,
                "deltaInputTokens": in_tok, "deltaOutputTokens": 1,
                "deltaCacheReadTokens": 0, "deltaCacheWriteTokens": 0}

    # 1. only observed_single
    def test_only_observed_single(self):
        intervals = [
            self.interval(
                0, weekly=("ok", 12.0),
                activity=[self.act("engineer", "gpt-6-sol", calls=5)]),
            self.interval(
                1, weekly=("ok", 10.0),
                activity=[self.act("tester", "gpt-5.5", calls=2)]),
        ]
        s = agg.summarize("weekly", intervals)
        self.assertEqual(s["observedPoints"], 22.0)
        self.assertEqual(s["attributedPoints"], 22.0)
        self.assertEqual(s["unattributedPoints"], 0.0)
        self.assertEqual(s["coveragePercent"], 100.0)
        self.assertEqual(s["evidence"]["observedSinglePoints"], 22.0)
        self.assertEqual(s["evidence"]["estimatedSharedPoints"], 0.0)
        self.assertEqual(len(s["agents"]), 2)

    # 2. only estimated_shared
    def test_only_estimated_shared(self):
        intervals = [self.interval(
            0, weekly=("ok", 37.0),
            activity=[self.act("engineer", "gpt-6-sol", calls=2, in_tok=9),
                      self.act("oracle", "gpt-5.6-sol", calls=6)])]
        s = agg.summarize("weekly", intervals)
        self.assertEqual(s["attributedPoints"], 37.0)
        by = {(a["agent"], m["model"]): m["estimatedSharedPoints"]
              for a in s["agents"] for m in a["models"]}
        self.assertEqual(by[("engineer", "gpt-6-sol")], 9.25)
        self.assertEqual(by[("oracle", "gpt-5.6-sol")], 27.75)
        self.assertEqual(s["evidence"]["estimatedSharedPoints"], 37.0)

    # 3. mixture of observed + estimated (matches checkpoint example)
    def test_mixture_of_kinds(self):
        intervals = [
            self.interval(
                0, weekly=("ok", 12.0),
                activity=[self.act("engineer", "gpt-6-sol", calls=3)]),
            self.interval(
                1, weekly=("ok", 18.0),
                activity=[self.act("oracle", "gpt-5.6-sol", calls=1,
                                   in_tok=1000),
                          self.act("scribe", "gpt-6-sol", calls=1)]),
            self.interval(
                2, weekly=("ok", 4.0),
                activity=[self.act("engineer", "gpt-6-sol", calls=1)],
                unknown_profiles=["reviewer"]),
            self.interval(
                3, weekly=("ok", 3.0),
                activity=[]),
        ]
        s = agg.summarize("weekly", intervals)
        self.assertEqual(s["observedPoints"], 37.0)
        self.assertEqual(s["attributedPoints"], 30.0)
        self.assertEqual(s["unattributedPoints"], 7.0)
        self.assertEqual(
            s["coveragePercent"], 30.0 / 37.0 * 100.0)
        self.assertEqual(
            s["unattributed"],
            {"noHermesActivityPoints": 3.0,
             "incompleteHermesObservabilityPoints": 4.0,
             "noCallableActivityPoints": 0.0})
        self.assertEqual(s["evidence"],
                         {"observedSinglePoints": 12.0,
                          "estimatedSharedPoints": 18.0})

    # 4. unattributed / no Hermes activity bucket stands alone
    def test_no_hermes_activity_bucket(self):
        s = agg.summarize(
            "weekly",
            [self.interval(0, weekly=("ok", 5.0), activity=[])])
        self.assertEqual(s["observedPoints"], 5.0)
        self.assertEqual(s["attributedPoints"], 0.0)
        self.assertEqual(s["unattributedPoints"], 5.0)
        self.assertEqual(
            s["unattributed"]["noHermesActivityPoints"], 5.0)
        self.assertEqual(s["coveragePercent"], 0.0)
        self.assertEqual(s["agents"], [])

    # 5. incomplete observability bucket
    def test_incomplete_observability_bucket(self):
        s = agg.summarize(
            "weekly",
            [self.interval(
                0, weekly=("ok", 9.0),
                activity=[self.act("engineer", "gpt-6-sol", calls=1)],
                unknown_identities=["engineer/gpt-5.5"])])
        self.assertEqual(
            s["unattributed"]["incompleteHermesObservabilityPoints"], 9.0)
        self.assertEqual(s["attributedPoints"], 0.0)
        self.assertEqual(s["observedPoints"], 9.0)

    # 6. no callable activity bucket
    def test_no_callable_activity_bucket(self):
        s = agg.summarize(
            "weekly",
            [self.interval(
                0, weekly=("ok", 6.0),
                activity=[self.act("engineer", "gpt-6-sol", calls=0,
                                   in_tok=400)])])
        self.assertEqual(s["unattributed"]["noCallableActivityPoints"], 6.0)
        self.assertEqual(s["attributedPoints"], 0.0)
        self.assertEqual(s["observedPoints"], 6.0)

    # 7. gaps are ignored without creating fake deltas
    def test_gap_inside_segment_is_evidence_reducer_only(self):
        intervals = [
            self.interval(
                0, weekly=("ok", 10.0),
                activity=[self.act("engineer", "gpt-6-sol", calls=1)]),
            self.interval(1, weekly=("gap", None),
                          activity=[self.act("engineer",
                                             "gpt-6-sol", calls=99)]),
            self.interval(
                2, weekly=("ok", 5.0),
                activity=[self.act("oracle", "gpt-5.6-sol", calls=4)]),
        ]
        s = agg.summarize("weekly", intervals)
        self.assertEqual(s["observedPoints"], 15.0)
        self.assertEqual(s["attributedPoints"], 15.0)
        # The gap interval contributed NOTHING (no fake 99-call delta).
        self.assertEqual(s["unattributedPoints"], 0.0)
        self.assertEqual(s["coveragePercent"], 100.0)

    # 8. reset starts a new aggregation segment
    def test_reset_starts_new_segment(self):
        intervals = [
            self.interval(
                0, weekly=("ok", 10.0),
                activity=[self.act("engineer", "gpt-6-sol", calls=1)]),
            self.interval(1, weekly=("reset_boundary", None)),
            self.interval(
                2, weekly=("ok", 6.0),
                activity=[self.act("oracle", "gpt-5.6-sol", calls=1),
                          self.act("scribe", "gpt-6-sol", calls=1)]),
            self.interval(
                3, weekly=("ok", 4.0),
                activity=[self.act("tester", "gpt-5.5", calls=8)]),
        ]
        s = agg.summarize("weekly", intervals)
        self.assertEqual(s["observedPoints"], 10.0)
        self.assertEqual(s["attributedPoints"], 10.0)
        self.assertEqual(s["segmentStartAt"], t(60))
        self.assertEqual(s["segmentEndAt"], t(120))
        agents = {a["agent"] for a in s["agents"]}
        self.assertEqual(agents, {"oracle", "scribe", "tester"})

    def test_reset_with_nothing_after_it(self):
        intervals = [
            self.interval(
                0, weekly=("ok", 3.0),
                activity=[self.act("engineer", "gpt-6-sol", calls=1)]),
            self.interval(1, weekly=("reset_boundary", None)),
        ]
        s = agg.summarize("weekly", intervals)
        self.assertEqual(s["observedPoints"], 0.0)
        self.assertIsNone(s["coveragePercent"])
        self.assertEqual(s["agents"], [])

    # 9. session and weekly produce different summaries
    def test_session_and_weekly_independent(self):
        intervals = [self.interval(
            0,
            session=("ok", 4.0),
            weekly=("ok", 30.0),
            activity=[self.act("engineer", "gpt-6-sol", calls=1, in_tok=3),
                      self.act("oracle", "gpt-5.6-sol", calls=2)])]
        session = agg.summarize("session", intervals)
        weekly = agg.summarize("weekly", intervals)
        self.assertEqual(session["window"], "session")
        self.assertEqual(weekly["window"], "weekly")
        self.assertEqual(session["observedPoints"], 4.0)
        self.assertEqual(weekly["observedPoints"], 30.0)
        self.assertEqual(session["evidence"]["observedSinglePoints"], 0.0)
        self.assertEqual(session["evidence"]["estimatedSharedPoints"], 4.0)
        self.assertEqual(weekly["evidence"]["estimatedSharedPoints"], 30.0)

    # 10. same model under two agents stays separate
    def test_same_model_two_agents(self):
        s = agg.summarize(
            "weekly",
            [self.interval(
                0, weekly=("ok", 100.0),
                activity=[self.act("engineer", "gpt-6-sol", calls=3),
                          self.act("tester", "gpt-6-sol", calls=9)])])
        self.assertEqual(len(s["agents"]), 2)
        by = {a["agent"]: a["models"][0]["model"] for a in s["agents"]}
        self.assertEqual(by, {"engineer": "gpt-6-sol",
                              "tester": "gpt-6-sol"})
        totals = {a["agent"]: a["models"][0]["estimatedSharedPoints"]
                  for a in s["agents"]}
        self.assertEqual(totals, {"engineer": 25.0, "tester": 75.0})

    # 11. one agent using two models stays separate
    def test_one_agent_two_models(self):
        s = agg.summarize(
            "weekly",
            [self.interval(
                0, weekly=("ok", 20.0),
                activity=[self.act("scribe", "gpt-6-sol", calls=1),
                          self.act("scribe", "gpt-5.6-luna", calls=3)])])
        self.assertEqual(len(s["agents"]), 1)
        agent = s["agents"][0]
        self.assertEqual(len(agent["models"]), 2)
        by = {m["model"]: m["estimatedSharedPoints"]
              for m in agent["models"]}
        self.assertEqual(by, {"gpt-6-sol": 5.0, "gpt-5.6-luna": 15.0})

    # 12. agent rollups reconcile with model rollups
    def test_agent_rollups_reconcile(self):
        intervals = [
            self.interval(
                0, weekly=("ok", 12.0),
                activity=[self.act("engineer", "gpt-6-sol", calls=3)]),
            self.interval(
                1, weekly=("ok", 18.0),
                activity=[self.act("engineer", "gpt-5.6-luna", calls=1),
                          self.act("oracle", "gpt-5.6-sol", calls=1)]),
        ]
        s = agg.summarize("weekly", intervals)
        for agent in s["agents"]:
            model_sum = sum(m["totalAttributedPoints"]
                            for m in agent["models"])
            self.assertEqual(agent["totalAttributedPoints"], model_sum)
        self.assertEqual(
            sum(a["totalAttributedPoints"] for a in s["agents"]),
            s["attributedPoints"])

    # 13. attributed + unattributed == observed (exact, with odd splits)
    def test_reconciliation_invariant(self):
        intervals = [
            self.interval(
                0, weekly=("ok", 10.0),
                activity=[self.act("a1", "m1", calls=1),
                          self.act("a2", "m2", calls=2),
                          self.act("a3", "m3", calls=4)]),
            self.interval(
                1, weekly=("ok", 7.5),
                activity=[self.act("a1", "m1", calls=1)],
                hermes_known=False),
        ]
        s = agg.summarize("weekly", intervals)
        total = s["attributedPoints"] + s["unattributedPoints"]
        self.assertTrue(math.isclose(total, s["observedPoints"],
                                     rel_tol=1e-9, abs_tol=1e-12), s)
        self.assertEqual(s["observedPoints"], 17.5)
        self.assertEqual(s["unattributedPoints"], 7.5)

    # 14. coverage calculation (full precision, no display rounding)
    def test_coverage_full_precision(self):
        s = agg.summarize("weekly", [
            self.interval(0, weekly=("ok", 10.0),
                          activity=[self.act("a", "m", calls=1)]),
            self.interval(1, weekly=("ok", 10.0),
                          activity=[]),
            self.interval(2, weekly=("ok", 10.0),
                          activity=[]),
        ])
        # Full precision: exactly the float result of the division, not a
        # display-rounded 33.33.
        self.assertEqual(s["coveragePercent"], 10.0 / 30.0 * 100.0)
        self.assertNotEqual(s["coveragePercent"], 33.33)
        self.assertTrue(math.isclose(s["coveragePercent"], 100.0 / 3.0,
                                     rel_tol=1e-12))

    # 15. zero observed points -> coverage is null, not 0% or 100%
    def test_zero_observed_points_coverage_null(self):
        s = agg.summarize("weekly", [
            self.interval(0, weekly=("gap", None)),
            self.interval(1, weekly=("ok", 0.0),
                          activity=[self.act("a", "m", calls=2)]),
        ])
        self.assertEqual(s["observedPoints"], 0.0)
        self.assertIsNone(s["coveragePercent"])
        self.assertEqual(s["attributedPoints"], 0.0)
        self.assertEqual(s["unattributedPoints"], 0.0)

    # 16. deterministic ordering regardless of input order
    def test_deterministic_ordering(self):
        intervals = [self.interval(
            0, weekly=("ok", 30.0),
            activity=[self.act("zzz", "model-b", calls=1, in_tok=1),
                      self.act("aaa", "model-z", calls=2),
                      self.act("mmm", "model-a", calls=3)])]
        s = agg.summarize("weekly", intervals)
        self.assertEqual([a["agent"] for a in s["agents"]],
                         ["aaa", "mmm", "zzz"])
        # A second interval with interleaved models: sorted per agent.
        intervals.append(self.interval(
            1, weekly=("ok", 5.0),
            activity=[self.act("aaa", "model-q", calls=1),
                      self.act("aaa", "model-a", calls=1)]))
        s = agg.summarize("weekly", intervals)
        aaa = next(a for a in s["agents"] if a["agent"] == "aaa")
        self.assertEqual([m["model"] for m in aaa["models"]],
                         ["model-a", "model-q", "model-z"])

    # 17. no normalization to 100% of observed
    def test_no_normalization(self):
        s = agg.summarize("weekly", [
            self.interval(
                0, weekly=("ok", 10.0),
                activity=[self.act("engineer", "gpt-6-sol", calls=2,
                                   in_tok=50),
                          self.act("oracle", "gpt-5.6-sol", calls=6,
                                   in_tok=1)]),
            self.interval(1, weekly=("ok", 15.0), activity=[]),
        ])
        self.assertEqual(s["attributedPoints"], 10.0)
        self.assertEqual(s["unattributedPoints"], 15.0)
        self.assertEqual(s["observedPoints"], 25.0)
        self.assertEqual(
            sum(a["totalAttributedPoints"] for a in s["agents"]),
            s["attributedPoints"])      # == 10.0, NOT 25.0
        self.assertNotEqual(
            sum(a["totalAttributedPoints"] for a in s["agents"]),
            s["observedPoints"])


class CliOfflineTest(unittest.TestCase):
    def test_cli_outputs_one_json_document(self):
        def obs(at, used, models):
            return {"schemaVersion": 1, "observedAt": at,
                    "codex": {"available": True, "tier": "plus",
                              "session": None,
                              "weekly": {"usedPercent": used,
                                         "resetsAt": "2026-10-02T01:02:00+00:00"},
                              "error": None},
                    "hermes": {"available": True, "profiles": models}}

        def counters(calls):
            return {"calls": calls, "inputTokens": calls * 100,
                    "outputTokens": 1, "cacheReadTokens": 0,
                    "cacheWriteTokens": 0}

        a = obs("2026-09-26T10:00:00-05:00", 30.0,
                {"engineer": {"available": True,
                              "models": {"gpt-6-sol": counters(1)}}})
        b = obs("2026-09-26T10:30:00-05:00", 32.0,
                {"engineer": {"available": True,
                              "models": {"gpt-6-sol": counters(3)}}})
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "o.jsonl"
            state.write_text(json.dumps(a) + "\n" + json.dumps(b) + "\n",
                             encoding="utf-8")
            proc = subprocess.run(
                [sys.executable, str(SCRIPT), "--state", str(state),
                 "--window", "weekly", "--pretty"],
                capture_output=True, text=True, timeout=30)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["window"], "weekly")
            self.assertEqual(payload["observedPoints"], 2.0)
            self.assertEqual(payload["attributedPoints"], 2.0)
            self.assertEqual(payload["coveragePercent"], 100.0)


if __name__ == "__main__":
    unittest.main()

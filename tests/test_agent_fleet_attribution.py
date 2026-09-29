#!/usr/bin/env python3
"""Agent Fleet attribution engine tests (Phase 3, Task 4).

Pure, fully offline: attributes synthetic interval records shaped
exactly like ``agent-fleet-intervals`` output. No store files, no
network, no live Hermes/Codex.

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
SCRIPT = ROOT / "scripts" / "agent-fleet-attribution"


def make_module(alias):
    loader = SourceFileLoader(alias, str(SCRIPT))
    mod = module_from_spec(spec_from_loader(loader.name, loader))
    loader.exec_module(mod)
    return mod


at = make_module("af_attribution_under_test")

T0 = "2026-09-26T12:00:00-05:00"
T1 = "2026-09-26T12:30:00-05:00"


def act(agent, model, calls=0, in_tok=0, out_tok=0, cr=0, cw=0):
    return {"agent": agent, "model": model, "deltaCalls": calls,
            "deltaInputTokens": in_tok, "deltaOutputTokens": out_tok,
            "deltaCacheReadTokens": cr, "deltaCacheWriteTokens": cw}


def interval(session=("ok", 25.0), weekly=("ok", 25.0), activity=None,
             hermes_known=True, unknown_profiles=None, unknown_identities=None):
    return {
        "schemaVersion": 1,
        "startAt": T0,
        "endAt": T1,
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


def window(record, name):
    return record["codex"][name]


class AttributionContractTest(unittest.TestCase):
    # 1. one active identity -> observed_single, full delta allocated
    def test_one_active_identity(self):
        record = interval(("ok", 10.0), ("ok", 10.0),
                          activity=[act("engineer", "gpt-6-sol",
                                        calls=5, in_tok=900)])
        out = at.attribute(record)
        win = window(out, "session")
        self.assertEqual(win["kind"], "observed_single")
        self.assertEqual(win["allocations"],
                         [{"agent": "engineer", "model": "gpt-6-sol",
                           "allocatedPoints": 10.0}])
        # estimated_shared marker must not leak.
        self.assertNotIn("reason", win)

    # 2. multiple identities -> estimated_shared by deltaCalls
    def test_multiple_identities(self):
        record = interval(
            ("ok", 40.0), ("ok", 0.0),
            activity=[act("engineer", "gpt-6-sol", calls=2),
                      act("oracle", "gpt-5.6-sol", calls=6)])
        win = window(at.attribute(record), "session")
        self.assertEqual(win["kind"], "estimated_shared")
        by_identity = {(a["agent"], a["model"]): a["allocatedPoints"]
                       for a in win["allocations"]}
        self.assertEqual(by_identity[("engineer", "gpt-6-sol")], 10.0)
        self.assertEqual(by_identity[("oracle", "gpt-5.6-sol")], 30.0)

    # 3. same model under different agents stays separate identities
    def test_same_model_different_agents(self):
        record = interval(
            ("ok", 100.0), ("ok", 0.0),
            activity=[act("engineer", "gpt-6-sol", calls=3),
                      act("tester", "gpt-6-sol", calls=9)])
        win = window(at.attribute(record), "session")
        self.assertEqual(win["kind"], "estimated_shared")
        by_agent = {a["agent"]: a["allocatedPoints"] for a in win["allocations"]}
        self.assertEqual(by_agent, {"engineer": 25.0, "tester": 75.0})

    # 4. one agent using multiple models
    def test_one_agent_multiple_models(self):
        record = interval(
            ("ok", 20.0), ("ok", 0.0),
            activity=[act("scribe", "gpt-6-sol", calls=1),
                      act("scribe", "gpt-5.6-luna", calls=3)])
        win = window(at.attribute(record), "session")
        self.assertEqual(win["kind"], "estimated_shared")
        by_model = {a["model"]: a["allocatedPoints"] for a in win["allocations"]}
        self.assertEqual(by_model, {"gpt-6-sol": 5.0, "gpt-5.6-luna": 15.0})

    # 5. no Hermes activity -> unattributed/no_hermes_activity
    def test_no_hermes_activity(self):
        record = interval(("ok", 15.0), ("ok", 0.0), activity=[])
        win = window(at.attribute(record), "session")
        self.assertEqual(win, {"kind": "unattributed",
                               "reason": "no_hermes_activity"})
        self.assertNotIn("allocations", win)

    # 6. incomplete profile observability blocks ALL allocation
    def test_incomplete_profile_observability(self):
        record = interval(
            ("ok", 30.0), ("ok", 30.0),
            activity=[act("engineer", "gpt-6-sol", calls=1)],
            unknown_profiles=["oracle"])
        out = at.attribute(record)
        for name in ("session", "weekly"):
            self.assertEqual(
                window(out, name),
                {"kind": "unattributed",
                 "reason": "incomplete_hermes_observability"})
            self.assertNotIn("allocations", window(out, name))

    # 7. incomplete identity observability blocks ALL allocation
    def test_incomplete_identity_observability(self):
        record = interval(
            ("ok", 30.0), ("ok", 30.0),
            activity=[act("engineer", "gpt-6-sol", calls=1)],
            unknown_identities=["engineer/gpt-5.5"])
        out = at.attribute(record)
        for name in ("session", "weekly"):
            self.assertEqual(
                window(out, name)["reason"], "incomplete_hermes_observability")

    # 8. hermesKnown=false blocks ALL allocation
    def test_hermes_known_false(self):
        record = interval(
            ("ok", 12.0), ("ok", 12.0),
            activity=[act("engineer", "gpt-6-sol", calls=4)],
            hermes_known=False)
        out = at.attribute(record)
        for name in ("session", "weekly"):
            self.assertEqual(
                window(out, name),
                {"kind": "unattributed",
                 "reason": "incomplete_hermes_observability"})

    # 9. zero allowance delta -> no_allowance_delta, no cost inference
    def test_zero_allowance_delta(self):
        record = interval(
            ("ok", 0.0), ("ok", 0.0),
            activity=[act("engineer", "gpt-6-sol", calls=3, in_tok=500)])
        win = window(at.attribute(record), "session")
        self.assertEqual(win, {"kind": "no_allowance_delta"})
        for key in ("allocations", "reason", "providerCost",
                    "zeroCostInferred"):
            self.assertNotIn(key, win)

    # 10. Codex gap
    def test_codex_gap(self):
        record = interval(("gap", None), ("gap", None),
                          activity=[act("engineer", "gpt-6-sol", calls=1)])
        out = at.attribute(record)
        self.assertEqual(window(out, "session"), {"kind": "gap"})
        self.assertEqual(window(out, "weekly"), {"kind": "gap"})

    # 11. reset boundary
    def test_reset_boundary(self):
        record = interval(("reset_boundary", None), ("reset_boundary", None))
        out = at.attribute(record)
        self.assertEqual(window(out, "session"),
                         {"kind": "reset_boundary"})
        self.assertEqual(window(out, "weekly"),
                         {"kind": "reset_boundary"})

    # 12. session and weekly can produce DIFFERENT kinds from same interval
    def test_session_and_weekly_independent_kinds(self):
        record = interval(
            ("ok", 8.0), ("gap", None),
            activity=[act("engineer", "gpt-6-sol", calls=1)])
        out = at.attribute(record)
        self.assertEqual(window(out, "session")["kind"], "observed_single")
        self.assertEqual(window(out, "weekly")["kind"], "gap")

        record = interval(
            ("ok", 8.0), ("reset_boundary", None),
            activity=[act("engineer", "gpt-6-sol", calls=1),
                      act("oracle", "gpt-5.6-sol", calls=1)])
        out = at.attribute(record)
        self.assertEqual(window(out, "session")["kind"], "estimated_shared")
        self.assertEqual(window(out, "weekly")["kind"], "reset_boundary")

    # 13. zero-call rows are ignored for attribution
    def test_zero_call_rows_ignored(self):
        # Zero-call row must not receive (or block) allocation.
        record = interval(
            ("ok", 6.0), ("ok", 0.0),
            activity=[act("engineer", "gpt-6-sol", calls=0, in_tok=400),
                      act("engineer", "gpt-5.6-luna", calls=2)])
        win = window(at.attribute(record), "session")
        self.assertEqual(win["kind"], "observed_single")
        self.assertEqual(win["allocations"][0]["model"], "gpt-5.6-luna")
        self.assertEqual(win["allocations"][0]["allocatedPoints"], 6.0)

        # Only zero-call rows: nothing weightable -> unattributed.
        record = interval(
            ("ok", 6.0), ("ok", 0.0),
            activity=[act("engineer", "gpt-6-sol", calls=0, in_tok=400)])
        win = window(at.attribute(record), "session")
        self.assertEqual(win["kind"], "unattributed")
        self.assertEqual(win.get("reason"), "no_callable_activity")
        self.assertNotIn("allocations", win)

    # 14. allocations reconcile exactly to the observed delta
    def test_allocations_reconcile_exactly(self):
        calls = (("engineer", "gpt-6-sol", 1),
                 ("oracle", "gpt-5.5", 2),
                 ("scribe", "gpt-6-astra", 4))  # total 7, delta 10.0
        record = interval(
            ("ok", 10.0), ("ok", 0.0),
            activity=[act(a, m, calls=c, in_tok=i * 999)
                      for i, (a, m, c) in enumerate(calls)])
        win = window(at.attribute(record), "session")
        self.assertEqual(win["kind"], "estimated_shared")
        total = sum(a["allocatedPoints"] for a in win["allocations"])
        self.assertTrue(math.isclose(total, 10.0, rel_tol=1e-12,
                                     abs_tol=1e-12),
                        f"allocations do not reconcile: {win}")
        # No display rounding happened: 10*(1/7), 10*(2/7), 10*(4/7).
        by = {(a["agent"]): a["allocatedPoints"] for a in win["allocations"]}
        self.assertEqual(by["engineer"], 10.0 / 7.0)
        self.assertEqual(by["oracle"], 20.0 / 7.0)
        self.assertEqual(by["scribe"], 40.0 / 7.0)

        # observed_single reconciles too.
        record = interval(("ok", 3.5), ("ok", 0.0),
                          activity=[act("engineer", "gpt-6-sol", calls=7)])
        win = window(at.attribute(record), "session")
        self.assertEqual(
            sum(a["allocatedPoints"] for a in win["allocations"]), 3.5)

    def test_no_confidence_scores_or_weights_exist(self):
        record = interval(("ok", 10.0), ("ok", 10.0),
                          activity=[act("engineer", "gpt-6-sol",
                                        calls=1, in_tok=10, out_tok=2),
                                   act("oracle", "gpt-5.5", calls=3)])
        out = at.attribute(record)
        text = json.dumps(out)
        for token in ("confidence", "weight", "multiplier", "probability",
                      "score"):
            self.assertNotIn(token, text)
        # Token counts must not influence the split (1:3 by calls only).
        by = {a["agent"]: a["allocatedPoints"]
              for a in window(out, "session")["allocations"]}
        self.assertEqual(by["engineer"], 2.5)
        self.assertEqual(by["oracle"], 7.5)

    def test_invalid_window(self):
        broken = interval(("ok", 5.0), ("ok", 0.0))
        broken["codex"]["weekly"] = {"status": "weird", "deltaPoints": 1}
        self.assertEqual(window(at.attribute(broken), "weekly"),
                         {"kind": "invalid"})
        self.assertEqual(window(at.attribute(None), "weekly"),
                         {"kind": "invalid"})


class CliOfflineTest(unittest.TestCase):
    def test_cli_outputs_single_json_document(self):
        def obs(at, codex, act_entries):
            return {"schemaVersion": 1, "observedAt": at,
                    "codex": codex,
                    "hermes": {"available": True, "profiles": {}}}

        def codex(used):
            return {"available": True, "tier": "plus",
                    "session": {"usedPercent": used,
                                "resetsAt": "2026-09-26T19:06:35+00:00"},
                    "weekly": None, "error": None}

        def profile(name, models):
            return {"available": True, "models": models}

        def counters(calls, in_tok):
            return {"calls": calls, "inputTokens": in_tok, "outputTokens": 1,
                    "cacheReadTokens": 0, "cacheWriteTokens": 0}

        def hermes(name_models):
            return {"available": True,
                    "profiles": {name: profile(name, models)
                                 for name, models in name_models}}

        a = obs("2026-09-26T10:00:00-05:00", codex(10.0), None)
        a["hermes"] = hermes([("engineer",
                               {"gpt-6-sol": counters(1, 100)})])
        b = obs("2026-09-26T10:30:00-05:00", codex(14.0), None)
        b["hermes"] = hermes([("engineer",
                               {"gpt-6-sol": counters(3, 400)})])

        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "o.jsonl"
            state.write_text(json.dumps(a) + "\n" + json.dumps(b) + "\n",
                             encoding="utf-8")
            proc = subprocess.run(
                [sys.executable, str(SCRIPT), "--state", str(state),
                 "--pretty"],
                capture_output=True, text=True, timeout=30)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout)
            attributions = payload["attributions"]
            self.assertEqual(len(attributions), 1)
            session = attributions[0]["codex"]["session"]
            # Weekly window was None at both endpoints -> gap -> no share.
            self.assertEqual(session,
                             {"kind": "observed_single",
                              "allocations": [
                                  {"agent": "engineer",
                                   "model": "gpt-6-sol",
                                   "allocatedPoints": 4.0}]})
            self.assertEqual(attributions[0]["codex"]["weekly"]["kind"],
                             "gap")


if __name__ == "__main__":
    unittest.main()

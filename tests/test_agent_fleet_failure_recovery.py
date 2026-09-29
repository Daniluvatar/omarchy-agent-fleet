#!/usr/bin/env python3
"""End-to-end Phase 3 chain: Codex failure then recovery (offline).

Drives the real pipeline the way the panel's settled-refresh path does:
a snapshot capture per refresh wave — the snapshot CLI re-collects fresh,
so a failed Codex refresh lands as codex.available=false and must produce
a gap, never a bridged delta — then the interval builder, then the
aggregation layer.

Sequence (weekly points):
    A  40   (usable)
    B  45   (usable)                     A->B counts +5
    C  unavailable                       B->C and C->D must be gaps
    D  60   (usable)        never inferred: B->D (would be +15)
    E  66   (usable)                     D->E counts +6
Expected weekly: observed 11.0 — and NOT 26.0 (5 + 15 + 6), the value a
bridge across the failed observation would produce.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
TZ = "America/Guayaquil"
SNAPSHOT = ROOT / "scripts" / "agent-fleet-snapshot"
INTERVALS = ROOT / "scripts" / "agent-fleet-intervals"
AGGREGATE = ROOT / "scripts" / "agent-fleet-aggregate"
CODEX_UNAVAILABLE = ROOT / "tests" / "fixtures" / "codex-unavailable.json"
HERMES = ROOT / "tests" / "fixtures" / "hermes-profiles"
BASE_TIME = datetime(2026, 9, 27, 9, 0, tzinfo=ZoneInfo(TZ))

from importlib.machinery import SourceFileLoader  # noqa: E402
import importlib.util  # noqa: E402
loader = SourceFileLoader(
    "af_agg_chain", str(ROOT / "scripts" / "agent-fleet-aggregate"))
spec = importlib.util.spec_from_loader("af_agg_chain", loader)
agg = importlib.util.module_from_spec(spec)
loader.exec_module(agg)


def codex_payload(weekly_percent):
    # The upstream payload shape agent-fleet-codex reads from --input.
    return {
        "schemaVersion": 1, "id": "codex", "name": "Codex",
        "updatedAt": "2026-09-27T14:00:00+00:00",
        "ready": True, "hasLocalStats": True,
        "limits": [
            {"label": "5h window", "percent": 0.03,
             "resetsAt": "2026-09-27T19:26:51+00:00"},
            {"label": "Weekly (7-day)", "percent": weekly_percent,
             "resetsAt": "2026-10-03T18:40:25+00:00"},
        ],
        "tierLabel": "plus", "usageStatusText": "", "authHelpText": "",
    }


class FailureRecoveryChainTest(unittest.TestCase):

    def run_cli(self, *args):
        env = dict(os.environ, TZ=TZ)
        proc = subprocess.run(list(args), capture_output=True, text=True,
                              timeout=60, env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc

    def run_snapshot(self, state, codex_file, index):
        now = BASE_TIME + timedelta(hours=2 * index)
        self.run_cli(
            sys.executable, SNAPSHOT,
            "--state", str(state),
            "--codex-input", str(codex_file),
            "--hermes-root", str(HERMES),
            "--now", str(now.timestamp()),
        )

    def run_intervals(self, state):
        out = self.run_cli(sys.executable, INTERVALS, "--state",
                           str(state)).stdout
        return json.loads(out)["intervals"]

    def run_aggregate(self, state, window):
        out = self.run_cli(sys.executable, AGGREGATE, "--state", str(state),
                           "--window", window).stdout
        return json.loads(out)

    def test_failure_then_recovery_yields_gaps_not_bridges(self):
        with tempfile.TemporaryDirectory(
                prefix="agent-fleet-fail-recover-") as tmp:
            d = Path(tmp)
            state = d / "observations.jsonl"

            # Five consecutive refresh waves; wave 3's Codex refresh failed.
            # The stale UI value (45) is deliberately never passed to the
            # pipeline — the failed wave snapshots its own fresh (failed)
            # collection, exactly like the panel's settled path does.
            waves = [
                codex_payload(0.40),            # A
                codex_payload(0.45),            # B
                None,                           # C: failed refresh
                codex_payload(0.60),            # D
                codex_payload(0.66),            # E
            ]
            for i, payload in enumerate(waves):
                if payload is None:
                    codex_file = CODEX_UNAVAILABLE
                else:
                    codex_file = d / ("wave%d.json" % i)
                    codex_file.write_text(json.dumps(payload),
                                          encoding="utf-8")
                self.run_snapshot(state, codex_file, i)

            obs = [json.loads(l) for l in
                   state.read_text(encoding="utf-8").splitlines() if l.strip()]

            # 1. Every wave wrote exactly one observation, including the
            #    failed one (recorded as unavailable, not dropped and not
            #    faked).
            self.assertEqual(len(obs), 5)
            self.assertTrue(obs[0]["codex"]["available"])
            self.assertFalse(obs[2]["codex"]["available"])
            self.assertIsNotNone(obs[2]["codex"]["error"])
            self.assertTrue(obs[2]["hermes"]["available"])
            self.assertTrue(obs[3]["codex"]["available"])

            # 2. The interval layer sees gaps exactly across the failed
            #    observation, and nowhere else.
            ivs = self.run_intervals(state)
            self.assertEqual(len(ivs), 4)
            kinds = [agg.window_view(iv, "weekly")["kind"] for iv in ivs]
            self.assertNotIn("gap", kinds[0])   # A->B: usable 40 -> 45
            self.assertEqual(kinds[1], "gap")   # B->C: C unusable
            self.assertEqual(kinds[2], "gap")   # C->D: C unusable
            self.assertNotIn("gap", kinds[3])   # D->E: usable 60 -> 66
            self.assertEqual(agg.window_view(ivs[0], "weekly")["delta"], 5.0)
            self.assertEqual(agg.window_view(ivs[3], "weekly")["delta"], 6.0)

            # 3. The aggregation layer counts exactly the usable deltas:
            #    5 + 6 = 11, and never 26 (a B->D bridge would be +15).
            weekly = self.run_aggregate(state, "weekly")
            self.assertEqual(weekly["observedPoints"], 11.0)
            self.assertEqual(weekly["attributedPoints"], 0.0)
            self.assertEqual(weekly["unattributedPoints"], 11.0)
            # The Herumes counters in the fixture DB do not move (the codex
            # side is what varies), so the deltas land in the "no Hermes
            # activity" bucket, never attributed and never a confidence.
            self.assertEqual(
                weekly["unattributed"]["noHermesActivityPoints"], 11.0)
            self.assertLess(weekly["observedPoints"], 26.0)

            # 4. Session window follows the same rule: the failed wave cuts
            #    it into segments too (percent constant 3.0 -> zero deltas).
            session = self.run_aggregate(state, "session")
            self.assertEqual(session["observedPoints"], 0.0)
            self.assertIsNone(session["coveragePercent"])


if __name__ == "__main__":
    unittest.main()

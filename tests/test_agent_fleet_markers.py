#!/usr/bin/env python3
"""Agent Fleet gap and reset marker tests (Phase 5 — Task 5).

Markers are presentation metadata derived from the EXISTING Phase 3
interval/attribution chain: `agent-fleet-aggregate` now also emits
`markers` for the selected window (its newest reset boundary plus every
gap inside the current segment, each carrying the real interval `endAt`
or null). This suite proves:

- markers exist only when the underlying interval records say so:
  real gap, real reset_boundary, in chronological order, windows
  independent, gaps before the newest reset never leak into the
  current-segment markers;
- no marker ever invents a timestamp (missing endAt -> null);
- the full Phase 3/4 arithmetic and state invariants are untouched
  (attributed + unattributed == observed; current-segment-only
  attribution; both windows independent); and
- the markers survive the CLI contract (one JSON document on stdout,
  read-only over the store) and NOT the Phase 4 history schema
  (segments.jsonl records never gain a `markers` key).

    TZ=America/Guayaquil python3 -m unittest discover -s tests -p 'test_*.py' -v
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
AGGREGATE = SCRIPTS / "agent-fleet-aggregate"
HISTORY = SCRIPTS / "agent-fleet-history"

ENV = dict(os.environ)
ENV["TZ"] = "America/Guayaquil"


def load_module(path, alias):
    loader = SourceFileLoader(alias, str(path))
    module = module_from_spec(spec_from_loader(loader.name, loader))
    loader.exec_module(module)
    return module


agg = load_module(AGGREGATE, "af_aggregate_markers_under_test")


def t(minute):
    """Fixture timeline: 2026-09-26T12:00:00-05:00 + minute."""
    hour, rem = divmod(12 * 60 + minute, 60)
    return f"2026-09-26T{hour:02d}:{rem:02d}:00-05:00"


def interval(n=0, end_at="present", session=("gap", None),
             weekly=("gap", None), activity=None, hermes_known=True):
    """One Phase 3 interval record. status/delta per window drive the
    attribution kinds directly (gap -> gap, reset_boundary ->
    reset_boundary, ok+delta -> attribution)."""
    record = {
        "schemaVersion": 1,
        "startAt": t(30 * n),
        "codex": {
            "session": {"status": session[0], "deltaPoints": session[1]},
            "weekly": {"status": weekly[0], "deltaPoints": weekly[1]},
        },
        "hermesKnown": bool(hermes_known),
        "activity": list(activity or []),
        "unknownProfiles": [],
        "unknownIdentities": [],
        "status": "partial",
    }
    if end_at == "present":
        record["endAt"] = t(30 * n + 30)
    return record


def activity(agent, model, calls=1):
    return {"agent": agent, "model": model, "deltaCalls": calls,
            "deltaInputTokens": 0, "deltaOutputTokens": 0,
            "deltaCacheReadTokens": 0, "deltaCacheWriteTokens": 0}


class MarkerDerivationTest(unittest.TestCase):
    # 1. Current segment without gaps -> no markers at all.
    def test_no_gap_no_reset_no_markers(self):
        intervals = [
            interval(0, weekly=("ok", 12.0), activity=[activity("e", "m", 5)]),
            interval(1, weekly=("ok", 10.0), activity=[activity("e", "m", 2)]),
        ]
        s = agg.summarize("weekly", intervals)
        self.assertEqual(s["markers"], [])
        # Phase 3 invariants untouched.
        self.assertEqual(s["observedPoints"], 22.0)
        self.assertEqual(s["attributedPoints"], 22.0)
        self.assertEqual(s["unattributedPoints"], 0.0)
        self.assertEqual(s["coveragePercent"], 100.0)

    # 2. A real gap inside the current segment -> one gap marker, real at.
    def test_gap_marker_carries_real_interval_end_at(self):
        gap = interval(1, weekly=("gap", None))
        intervals = [
            interval(0, weekly=("ok", 12.0), activity=[activity("e", "m", 5)]),
            gap,
            interval(2, weekly=("ok", 10.0), activity=[activity("e", "m", 2)]),
        ]
        s = agg.summarize("weekly", intervals)
        self.assertEqual(
            s["markers"],
            [{"type": "gap", "at": t(60)}])
        self.assertEqual(s["markers"][0]["at"], gap["endAt"])
        # Numbers still exclude the gap record but keep the rest.
        self.assertEqual(s["observedPoints"], 22.0)

    # 3. A real reset boundary -> one reset_boundary marker.
    def test_reset_boundary_marker(self):
        before = interval(
            0, weekly=("ok", 12.0), activity=[activity("e", "m", 5)])
        boundary = interval(1, weekly=("reset_boundary", None))
        after = interval(
            2, weekly=("ok", 10.0), activity=[activity("e", "m", 2)])
        s = agg.summarize("weekly", [before, boundary, after])
        self.assertEqual(
            s["markers"],
            [{"type": "reset_boundary", "at": boundary["endAt"]}])
        # Phase 3 reset rule intact: current segment only.
        self.assertEqual(s["observedPoints"], 10.0)
        self.assertEqual(s["segmentStartAt"], after["startAt"])

    # 4. Gap before the newest reset belongs to a completed segment.
    def test_gap_before_reset_never_leaks_into_markers(self):
        old_gap = interval(0, weekly=("gap", None))
        boundary = interval(1, weekly=("reset_boundary", None))
        clean = interval(
            2, weekly=("ok", 10.0), activity=[activity("e", "m", 2)])
        s = agg.summarize("weekly", [old_gap, boundary, clean])
        self.assertEqual(
            s["markers"],
            [{"type": "reset_boundary", "at": boundary["endAt"]}])

    # 5. Reset + post-reset gap -> both, in chronological order.
    def test_reset_then_gap_markers(self):
        boundary = interval(0, weekly=("reset_boundary", None))
        gap = interval(1, weekly=("gap", None))
        ok = interval(
            2, weekly=("ok", 10.0), activity=[activity("e", "m", 2)])
        s = agg.summarize("weekly", [boundary, gap, ok])
        self.assertEqual(
            s["markers"],
            [
                {"type": "reset_boundary", "at": t(30)},
                {"type": "gap", "at": t(60)},
            ])
        self.assertEqual(s["observedPoints"], 10.0)
        self.assertEqual(s["attributedPoints"], 10.0)

    # 6. Multiple gaps in the current segment -> one marker each, ordered.
    def test_multiple_gap_markers_in_order(self):
        g1 = interval(1, weekly=("gap", None))
        g2 = interval(3, weekly=("gap", None))
        intervals = [
            interval(0, weekly=("ok", 4.0), activity=[activity("e", "m", 1)]),
            g1,
            interval(2, weekly=("ok", 4.0), activity=[activity("e", "m", 1)]),
            g2,
            interval(4, weekly=("ok", 4.0), activity=[activity("e", "m", 1)]),
        ]
        s = agg.summarize("weekly", intervals)
        self.assertEqual(
            s["markers"],
            [
                {"type": "gap", "at": t(60)},
                {"type": "gap", "at": t(120)},
            ])

    # 7. Weekly and session are fully independent in markers too.
    def test_windows_independent_markers(self):
        weekly_gap = interval(
            0, session=("ok", 8.0), weekly=("gap", None),
            activity=[activity("e", "m", 2)])
        s_weekly = agg.summarize("weekly", [weekly_gap])
        s_session = agg.summarize("session", [weekly_gap])
        self.assertEqual(
            s_session["markers"], [])
        self.assertEqual(
            s_weekly["markers"], [{"type": "gap", "at": t(30)}])

        weekly_reset = interval(
            0, session=("ok", 8.0), weekly=("reset_boundary", None),
            activity=[activity("e", "m", 2)])
        self.assertEqual(
            agg.summarize("weekly", [weekly_reset])["markers"],
            [{"type": "reset_boundary", "at": t(30)}])
        self.assertEqual(
            agg.summarize("session", [weekly_reset])["markers"], [])

    # 8. A gap record without endAt -> marker exists, `at` is null.
    #    The marker never invents a timestamp.
    def test_gap_marker_without_end_at_is_null(self):
        intervals = [
            interval(0, end_at="present", weekly=("ok", 4.0),
                     activity=[activity("e", "m", 1)]),
            interval(1, end_at="absent", weekly=("gap", None)),
        ]
        s = agg.summarize("weekly", intervals)
        self.assertEqual(s["markers"], [{"type": "gap", "at": None}])

    # 9. Markers do not enter the arithmetic at all: invariants hold
    #    even in the messiest ready state.
    def test_arithmetic_invariants_with_markers(self):
        intervals = [
            interval(0, weekly=("reset_boundary", None)),
            interval(1, weekly=("gap", None)),
            interval(
                2, weekly=("ok", 22.0),
                activity=[activity("e", "m", 5)]),
        ]
        s = agg.summarize("weekly", intervals)
        self.assertEqual(
            s["attributedPoints"] + s["unattributedPoints"],
            s["observedPoints"])
        self.assertEqual(s["observedPoints"], 22.0)
        self.assertEqual(len(s["markers"]), 2)

    # 10. segment_markers rejects bad inputs like summarize does.
    def test_segment_markers_input_validation(self):
        with self.assertRaises(ValueError):
            agg.segment_markers([], "monthly")
        with self.assertRaises(TypeError):
            agg.segment_markers(None, "weekly")


# --- Real-store integration (CLI contract) ------------------------------

def obs(minute, weekly=None, session=None):
    row = {
        "schemaVersion": 1,
        "observedAt": t(minute),
        "codex": {
            "available": weekly is not None or session is not None,
            "tier": "plus",
            "session": session,
            "weekly": weekly,
            "error": None,
        },
        "hermes": {"available": True, "profiles": {}},
    }
    return row


def win(used_percent, resets_at):
    return {"usedPercent": float(used_percent), "resetsAt": resets_at}


def _run_cli(cmd, extra_env=None):
    env = dict(ENV)
    env.update(extra_env or {})
    return subprocess.run(cmd, cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=60)


class MarkerCliTest(unittest.TestCase):
    """Markers survive the real read-only CLI chain (observations ->
    intervals -> attribution -> aggregate -> one JSON document)."""

    def test_cli_real_gap(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "observations.jsonl"
            rows = [
                obs(0, weekly=win(50, "W1")),
                obs(30, weekly=None),  # codex unavailable -> gap
                obs(60, weekly=win(62, "W1")),
            ]
            state.write_text(
                "\n".join(json.dumps(r) for r in rows) + "\n",
                encoding="utf-8")
            proc = _run_cli([
                sys.executable, str(AGGREGATE),
                "--state", str(state), "--window", "weekly"])
            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout)
            # One unavailable observation degrades BOTH adjacent
            # intervals (Phase 3 rule) -> two real gap markers, in order.
            self.assertEqual(
                payload["markers"],
                [
                    {"type": "gap", "at": t(30)},
                    {"type": "gap", "at": t(60)},
                ])
            # The rest of the Phase 3 contract is untouched.
            self.assertEqual(payload["window"], "weekly")

    def test_cli_reset_and_post_reset_gap(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "observations.jsonl"
            rows = [
                obs(0, weekly=win(50, "W1")),
                obs(30, weekly=win(62, "W1")),
                obs(60, weekly=win(5, "W2")),   # reset boundary
                obs(90, weekly=None),           # post-reset gap
            ]
            state.write_text(
                "\n".join(json.dumps(r) for r in rows) + "\n",
                encoding="utf-8")
            proc = _run_cli([
                sys.executable, str(AGGREGATE),
                "--state", str(state), "--window", "weekly"])
            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertEqual(
                payload["markers"],
                [
                    {"type": "reset_boundary", "at": t(60)},
                    {"type": "gap", "at": t(90)},
                ])
            # Read-only: the store is byte-identical after the run.
            self.assertEqual(
                state.read_text(encoding="utf-8"),
                "\n".join(json.dumps(r) for r in rows) + "\n")

    def test_cli_independent_windows(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "observations.jsonl"
            rows = [
                obs(0, session=win(50, "S1"), weekly=None),  # weekly gap
                obs(30, session=win(62, "S1"), weekly=win(40, "W1")),
            ]
            state.write_text(
                "\n".join(json.dumps(r) for r in rows) + "\n",
                encoding="utf-8")
            weekly = json.loads(_run_cli([
                sys.executable, str(AGGREGATE),
                "--state", str(state), "--window", "weekly"]).stdout)
            session = json.loads(_run_cli([
                sys.executable, str(AGGREGATE),
                "--state", str(state), "--window", "session"]).stdout)
            self.assertEqual(weekly["markers"], [{"type": "gap", "at": t(30)}])
            self.assertEqual(session["markers"], [])


class MarkerNotInHistoryTest(unittest.TestCase):
    """Phase 4 history stays untouched: the fixed record shape for
    segments.jsonl never gains a markers key (history picks fields
    explicitly from the summary)."""

    def test_history_records_never_carry_markers(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "observations.jsonl"
            segments = Path(tmp) / "segments.jsonl"
            rows = [
                obs(0, weekly=win(50, "W1"),
                    session=win(50, "S1")),
                obs(30, weekly=win(62, "W1"),
                    session=win(62, "S1")),   # +12/+12, valid movement
                obs(60, weekly=None),          # gap inside the run
                obs(90, weekly=win(70, "W1"),
                    session=win(70, "S1")),   # +8/+8 around the gap
                obs(120, weekly=win(5, "W2"),        # closes W1
                    session=win(80, "S2")),        # closes S1
            ]
            state.write_text(
                "\n".join(json.dumps(r) for r in rows) + "\n",
                encoding="utf-8")
            proc = _run_cli([
                sys.executable, str(HISTORY),
                "--state", str(state), "--segments", str(segments),
                "--now", "1800000000"])
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue(segments.is_file(),
                            "expected completed W1/S1 runs to be written")
            records = [
                json.loads(line)
                for line in segments.read_text(encoding="utf-8")
                .splitlines() if line.strip()]
            self.assertEqual(len(records), 2, records)  # one per window
            for record in records:
                self.assertNotIn("markers", record, record)


if __name__ == "__main__":
    unittest.main()

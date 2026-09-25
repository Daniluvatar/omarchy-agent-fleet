#!/usr/bin/env python3
"""Collector transformation tests.

Runs offline against fixtures; never calls Codex, Omarchy or the network.

    python3 -m unittest discover -s tests -p 'test_*.py' -v
"""

import io
import json
import subprocess
import sys
import unittest
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "agent-fleet-codex"
FIXTURES = ROOT / "tests" / "fixtures"

# The collector has no .py extension, so it is loaded through an explicit loader.
_LOADER = SourceFileLoader("agent_fleet_codex", str(SCRIPT))
collector = module_from_spec(spec_from_loader(_LOADER.name, _LOADER))
_LOADER.exec_module(collector)

CONTRACT_KEYS = {"schemaVersion", "provider", "available", "tier", "limits", "error"}
WINDOW_KEYS = {"label", "usedPercent", "resetsAt"}


def run_script(*args):
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return proc


def collect_fixture(name):
    return run_script("--input", str(FIXTURES / name))


class ContractShapeTest(unittest.TestCase):
    def assert_contract(self, record):
        self.assertEqual(set(record), CONTRACT_KEYS, "contract keys drifted")
        self.assertEqual(record["schemaVersion"], 1)
        self.assertEqual(record["provider"], "codex")
        self.assertIsInstance(record["available"], bool)
        self.assertEqual(set(record["limits"]), {"session", "weekly"})

    def test_normal_record_matches_contract(self):
        proc = collect_fixture("codex-normal.json")
        self.assertEqual(proc.returncode, 0)
        self.assert_contract(json.loads(proc.stdout))

    def test_stdout_is_exactly_one_json_document(self):
        proc = collect_fixture("codex-normal.json")
        self.assertEqual(proc.stdout.count("\n"), 1, "stdout must be a single JSON document")
        json.loads(proc.stdout)

    def test_unavailable_and_malformed_also_exit_zero(self):
        for name in ("codex-unavailable.json", "codex-malformed.json"):
            with self.subTest(fixture=name):
                proc = collect_fixture(name)
                self.assertEqual(proc.returncode, 0)
                self.assert_contract(json.loads(proc.stdout))


class MappingTest(unittest.TestCase):
    def setUp(self):
        self.record = json.loads(collect_fixture("codex-normal.json").stdout)

    def test_session_percent_maps_three_percent(self):
        self.assertEqual(self.record["limits"]["session"]["usedPercent"], 3.0)

    def test_weekly_percent_maps_one_hundred_percent(self):
        self.assertEqual(self.record["limits"]["weekly"]["usedPercent"], 100.0)

    def test_tier_mapping(self):
        self.assertEqual(self.record["tier"], "plus")

    def test_reset_timestamps_are_preserved_verbatim(self):
        self.assertEqual(self.record["limits"]["session"]["resetsAt"], "2026-09-25T19:26:51+00:00")
        self.assertEqual(self.record["limits"]["weekly"]["resetsAt"], "2026-09-26T18:40:25+00:00")

    def test_labels_and_availability(self):
        self.assertTrue(self.record["available"])
        self.assertIsNone(self.record["error"])
        self.assertEqual(self.record["limits"]["session"]["label"], "5h window")
        self.assertEqual(self.record["limits"]["weekly"]["label"], "Weekly (7-day)")
        self.assertEqual(set(self.record["limits"]["session"]), WINDOW_KEYS)

    def test_windows_are_identified_by_label_not_position(self):
        reversed_upstream = {
            "tierLabel": "pro",
            "limits": [
                {"label": "Weekly (7-day)", "percent": 0.25, "resetsAt": "2026-10-01T00:00:00+00:00"},
                {"label": "5h window", "percent": 0.5, "resetsAt": "2026-09-25T23:00:00+00:00"},
            ],
        }
        mapped = collector.map_limits(reversed_upstream["limits"])
        self.assertEqual(mapped["weekly"]["usedPercent"], 25.0)
        self.assertEqual(mapped["session"]["usedPercent"], 50.0)

    def test_zero_percent_is_a_value_not_a_missing_one(self):
        mapped = collector.map_limits([
            {"label": "5h window", "percent": 0.0, "resetsAt": ""},
            {"label": "Weekly (7-day)", "percent": 0.0, "resetsAt": ""},
        ])
        self.assertEqual(mapped["session"]["usedPercent"], 0.0)
        self.assertEqual(mapped["weekly"]["usedPercent"], 0.0)
        self.assertIsNone(mapped["session"]["resetsAt"], "empty upstream resetsAt becomes null")

    def test_minute_window_is_session(self):
        mapped = collector.map_limits([
            {"label": "45m window", "percent": 0.1, "resetsAt": "2026-09-25T20:00:00+00:00"},
            {"label": "Weekly (7-day)", "percent": 0.9, "resetsAt": "2026-09-26T18:00:00+00:00"},
        ])
        self.assertEqual(mapped["session"]["label"], "45m window")
        self.assertEqual(mapped["session"]["usedPercent"], 10.0)

    def test_positional_fallback_when_labels_are_meaningless(self):
        mapped = collector.map_limits([
            {"label": "Primary", "percent": 0.2, "resetsAt": "2026-09-25T20:00:00+00:00"},
            {"label": "Secondary", "percent": 0.8, "resetsAt": "2026-09-26T18:00:00+00:00"},
        ])
        self.assertEqual(mapped["session"]["usedPercent"], 20.0)
        self.assertEqual(mapped["weekly"]["usedPercent"], 80.0)

    def test_duplicate_slot_keeps_first_entry(self):
        mapped = collector.map_limits([
            {"label": "5h window", "percent": 0.1, "resetsAt": ""},
            {"label": "5h window", "percent": 0.9, "resetsAt": ""},
        ])
        self.assertEqual(mapped["session"]["usedPercent"], 10.0)
        self.assertIsNone(mapped["weekly"])

    def test_junk_entries_are_skipped(self):
        mapped = collector.map_limits([
            "nope",
            {"label": "Weekly (7-day)", "resetsAt": ""},
            {"label": "Weekly (7-day)", "percent": "lots", "resetsAt": ""},
            {"label": "Weekly (7-day)", "percent": -0.5, "resetsAt": ""},
            {"label": "Weekly (7-day)", "percent": 0.42, "resetsAt": "not-a-date"},
        ])
        self.assertEqual(mapped["weekly"]["usedPercent"], 42.0)
        self.assertIsNone(mapped["weekly"]["resetsAt"])
        self.assertIsNone(mapped["session"])


class TierTest(unittest.TestCase):
    def test_tier_normalization(self):
        self.assertEqual(collector.normalize_tier("  Plus  "), "plus")
        self.assertEqual(collector.normalize_tier("Team"), "team")
        self.assertIsNone(collector.normalize_tier(""))
        self.assertIsNone(collector.normalize_tier(None))

    def test_tier_only_record_is_available(self):
        record = collect_payload({"tierLabel": "pro", "limits": []})
        self.assertTrue(record["available"])
        self.assertEqual(record["tier"], "pro")
        self.assertIsNone(record["limits"]["session"])


class FailureTest(unittest.TestCase):
    def test_unavailable_upstream_record(self):
        record = json.loads(collect_fixture("codex-unavailable.json").stdout)
        self.assertFalse(record["available"])
        self.assertIsNone(record["tier"])
        self.assertIsNone(record["limits"]["session"])
        self.assertIsNone(record["limits"]["weekly"])
        self.assertEqual(record["error"]["code"], "CODEX_UNAVAILABLE")
        self.assertTrue(record["error"]["message"])

    def test_malformed_upstream_record(self):
        record = json.loads(collect_fixture("codex-malformed.json").stdout)
        self.assertFalse(record["available"])
        self.assertEqual(record["error"]["code"], "UPSTREAM_MALFORMED")
        self.assertIsNone(record["limits"]["weekly"])

    def test_empty_upstream_output(self):
        with mock.patch.object(sys, "stdin", io.StringIO("")):
            record = collector.collect(_args(stdin_text=""))
        self.assertFalse(record["available"])
        self.assertEqual(record["error"]["code"], "UPSTREAM_MALFORMED")

    def test_json_array_is_not_a_record(self):
        with mock.patch.object(sys, "stdin", io.StringIO("[]")):
            record = collector.collect(_args(stdin_text=""))
        self.assertEqual(record["error"]["code"], "UPSTREAM_MALFORMED")

    def test_missing_upstream_command(self):
        record = collector.collect(_args(command=str(FIXTURES / "definitely-not-a-command")))
        self.assertEqual(record["error"]["code"], "UPSTREAM_FAILED")

    def test_failing_upstream_command(self):
        self.assertEqual(collector.collect(_args(command="false"))["error"]["code"], "UPSTREAM_FAILED")

    def test_blank_upstream_command(self):
        self.assertEqual(collector.collect(_args(command="   "))["error"]["code"], "UPSTREAM_FAILED")

    def test_missing_input_file(self):
        record = collector.collect(_args(input_path=str(FIXTURES / "nope.json")))
        self.assertEqual(record["error"]["code"], "UPSTREAM_FAILED")

    def test_error_record_leaks_no_upstream_text(self):
        payload = json.dumps({
            "tierLabel": "",
            "limits": [],
            "authHelpText": "Traceback ... token=SECRET",
            "usageStatusText": "OAuthError: SECRET",
        })
        with mock.patch.object(sys, "stdin", io.StringIO(payload)):
            record = collector.collect(_args(stdin_text=""))
        self.assertNotIn("SECRET", json.dumps(record))
        self.assertEqual(record["error"]["code"], "CODEX_UNAVAILABLE")


def _args(command=None, input_path=None, stdin_text=None):
    """Build the argparse namespace collect() consumes."""

    class _Args:
        pass

    args = _Args()
    args.command = command
    if input_path is not None:
        args.input = input_path
    elif stdin_text is not None:
        args.input = "-"
    else:
        args.input = None
    args.timeout = 5.0
    return args


def collect_payload(payload):
    """Run collect() against an upstream payload without touching the network."""
    with mock.patch.object(sys, "stdin", io.StringIO(json.dumps(payload))):
        return collector.collect(_args(stdin_text=""))


class StdinTest(unittest.TestCase):
    def test_payload_is_read_from_stdin(self):
        record = collect_payload({"tierLabel": "plus", "limits": []})
        self.assertTrue(record["available"])

    def test_payload_is_read_from_stdin_as_text(self):
        with mock.patch.object(sys, "stdin", io.StringIO("not json")):
            record = collector.collect(_args(stdin_text=""))
        self.assertEqual(record["error"]["code"], "UPSTREAM_MALFORMED")


if __name__ == "__main__":
    unittest.main()

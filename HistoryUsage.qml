import QtQuick
import Quickshell
import Quickshell.Io

// HistoryUsage — the "Recent Segments" section data source for the panel.
//
// A separate, strictly read-only data source (the same family as
// CodexUsage / HermesUsage / AttributionUsage) so that parsing and
// layout math never live in Panel.qml. It runs ONLY the read-only list
// mode of the repo's own history CLI:
//
//   scripts/agent-fleet-history --list --segments <segments.jsonl>
//
// That mode (Phase 5, Task 6) renders the already-persisted completed
// segments, newest first, in exactly one JSON document. By CLI
// contract it never scans the observations store, never prunes, never
// re-derives, and never writes — so opening, rendering, scrolling, or
// toggling Recent Segments can never mutate segments.jsonl, never
// creates a snapshot, and never touches observations.jsonl. The panel
// pulls it once on first paint and on the same settled refresh the
// attribution section uses; switching the [ Weekly ] [ 5-hour ]
// selector does NOT filter it (both windows coexist in one list).
//
// Row contents come from the persisted records only: window, the
// persisted started/ended range, observedPoints, coveragePercent, and —
// compact, when non-zero — unattributedPoints. No raw observations,
// prompt content, session IDs, or logs (the record schema itself
// excludes them; this component never reaches into anything else).
// Markers (Phase 4.5) are live-display metadata and are NOT persisted,
// so there are no marker fields here to render.
//
// Empty / error states: a missing or empty store is a NORMAL state
// (zero rows -> the panel shows "No completed attribution segments
// yet"), not an error. Malformed lines are ignored by the CLI.

Item {
  id: history
  visible: false

  property int version: 1
  property string schema: "history-usage/v1"

  // The one place in the UI where the segments store path is resolved:
  // the same default the history writer uses.
  readonly property string segmentsPath: {
    var xdg = Quickshell.env("XDG_STATE_HOME")
    if (xdg && xdg !== "")
      return xdg + "/omarchy/agent-fleet/segments.jsonl"
    var home = Quickshell.env("HOME") || ""
    var user = Quickshell.env("USER") || "user"
    if (home === "")
      home = "/home/" + user
    return home + "/.local/state/omarchy/agent-fleet/segments.jsonl"
  }

  readonly property var listCommand: [
    Qt.resolvedUrl("scripts/agent-fleet-history").toString().replace(/^file:\/\//, ""),
    "--list", "--segments", history.segmentsPath
  ]

  // How many recent completed segments the panel shows (newest first —
  // the CLI already orders them; the panel keeps only the first N).
  readonly property int maxRows: 5

  // Phase 5 (Task 7): when false, the source is inert — the first-paint
  // refresh below and every refresh() call are no-ops, so the `--list`
  // process is never spawned for a hidden section (presentation-only).
  // The Panel sets this from the showRecentSegments manifest setting;
  // default true keeps the Task 6 behavior.
  property bool enabled: true

  // Display-ready rows, newest first, at most maxRows:
  //   { windowLabel, range, line }
  // All values derive from the persisted record; nothing is added.
  property var rows: []

  readonly property bool empty: history.rows.length === 0
  readonly property string emptyText:
      "No completed attribution segments yet"

  signal settled()

  property bool refreshing: false
  property bool finished: false

  function refresh() {
    if (!history.enabled)
      return
    if (history.refreshing)
      return
    // The guard keeps a first-paint call (Component.onCompleted ordering)
    // from wedging "refreshing" true before the Process child exists.
    if (!listProcess)
      return
    history.refreshing = true
    history.finished = false
    if (!listProcess.running) {
      listProcess.command = history.listCommand
      listProcess.running = true
    }
  }

  // Exactly one finalize per refresh: both the stream-finished and the
  // exited signals arrive per process — the flag makes the second a
  // no-op (same pattern as AttributionUsage).
  function _finish() {
    if (history.finished)
      return
    history.finished = true
    var records = []
    try {
      var body = String(listStream.text || "").trim()
      if (body !== "") {
        var parsed = JSON.parse(body)
        if (parsed && parsed.records)
          records = parsed.records
      }
    } catch (err) {
      records = []
    }
    history.rows = _displayRows(records)
    history.refreshing = false
    history.settled()
  }

  // ------------------------------------------------------------ rendering
  // "11" for 11.0, "1.5" for 1.5 — no fabricated precision.
  function numberText(n) {
    var v = Number(n)
    if (!isFinite(v))
      return "0"
    v = Math.round(v * 100) / 100
    return String(v)
  }

  // Persisted ISO-8601 (e.g. "2026-09-29T13:30:00-05:00") -> the clock
  // part. Slicing only — the canonical format is fixed by the schema.
  function clock(iso) {
    var s = String(iso)
    if (s.length < 16 || s.charAt(10) !== "T")
      return ""
    return s.substring(11, 16)
  }

  function dayOf(iso) {
    var s = String(iso)
    if (s.length < 10)
      return null
    var d = parseInt(s.substring(8, 10), 10)
    var m = parseInt(s.substring(5, 7), 10)
    if (isNaN(d) || isNaN(m) || m < 1 || m > 12)
      return null
    return { d: d, m: m }
  }

  // "Sep 22–29" (same month), "Sep 29 08:30–13:30" (same day),
  // "Sep 28–Oct 2" (month crossing) — from persisted timestamps only.
  function rangeText(startIso, endIso) {
    var a = dayOf(startIso)
    var b = dayOf(endIso)
    if (!a || !b)
      return String(startIso) + " – " + String(endIso)
    var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    var ma = MONTHS[a.m - 1]
    if (a.d === b.d)
      return ma + " " + a.d + " " + clock(startIso) + "–" + clock(endIso)
    if (a.m === b.m)
      return ma + " " + a.d + "–" + b.d
    return ma + " " + a.d + "–" + MONTHS[b.m - 1] + " " + b.d
  }

  function _displayRows(records) {
    var out = []
    var n = Math.min(history.maxRows, records.length)
    for (var i = 0; i < n; i++) {
      var r = records[i]
      if (!r)
        continue
      var line = numberText(r.observedPoints) + " pp observed"
      if (r.coveragePercent !== null && r.coveragePercent !== undefined)
        line += " · " + Math.round(Number(r.coveragePercent)) + "% coverage"
      if (Number(r.unattributedPoints) > 0)
        line += " · " + numberText(r.unattributedPoints) + " pp unattributed"
      out.push({
        windowLabel: String(r.window) === "session" ? "5-hour" : "Weekly",
        range: rangeText(String(r.startedAt || ""), String(r.endedAt || "")),
        line: line
      })
    }
    return out
  }

  Process {
    id: listProcess
    running: false
    command: []
    stdout: StdioCollector {
      id: listStream
      waitForEnd: true
      onStreamFinished: function() { history._finish() }
    }
    stderr: StdioCollector { waitForEnd: true }
    onExited: function(code, signal) {
      // Safety net: a crash or missing binary still settles the section.
      history._finish()
    }
  }

  // First paint: list whatever is persisted (read-only; no write path,
  // no snapshot). Deferred to the next event-loop pass so the Process
  // child exists.
  Component.onCompleted: Qt.callLater(function() { history.refresh() })
}

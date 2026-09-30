import QtQuick
import Quickshell
import Quickshell.Io

// AttributionUsage — the "Attribution" section data source for the panel.
//
// It is a separate, read-only data source (the same shape as CodexUsage and
// HermesUsage) so that parsing and layout math never live in Panel.qml. It
// runs the repo's own aggregation chain exactly as the CLI does — bare local
// commands, no shell, no network:
//
//   scripts/agent-fleet-intervals --state <observations.jsonl>
//   scripts/agent-fleet-aggregate --window weekly  --state <observations.jsonl>
//   scripts/agent-fleet-aggregate --window session --state <observations.jsonl>
//
// Neither aggregate command writes anything: the snapshot store appends, and
// this component only reads it back. Refreshing this section therefore can
// never create a snapshot, never arms a refresh wave, and never touches the
// collectors — the panel pulls it once, after a wave has settled (see
// Panel.qml).
//
// Phase 4 (session / 5-hour attribution view): BOTH provider windows are
// fetched and cached on every refresh, independently (never mixed — each
// window's state is derived from its own intervals and its own summary). The
// panel's [ Weekly ] [ 5-hour ] selector only picks which cached summary to
// render: switching windows is display-only and issues no new commands, so
// it can never refresh a collector, create a snapshot, write
// observations.jsonl, or touch segments.jsonl.
//
// Per-window states:
//   "collecting"  no observations yet (no store, or the builder produced no
//                 intervals)
//   "new_window"  a reset happened in this window but no usable post-reset
//                 interval exists yet
//   "ready"       this window's current segment produced a summary
//
// Copy rules (required terminology): Observed, Estimated, Unattributed,
// Coverage, pp. Never provider-truth words ("exact", "cost", "charged",
// "billing share", "official usage") — the upstream does not publish
// per-agent billing, and neither does this panel.

Item {
  id: attribution
  visible: false

  property int version: 2
  property string schema: "attribution-usage/v2"

  // The selected window: "weekly" (default) or "session". Driven by the
  // panel selector; changing it re-renders cached data only — it never
  // starts a process, arms a wave, or writes a store.
  property string window: "weekly"

  // The one place in the UI where the store path is resolved: the same
  // default the snapshot writer and the aggregation CLIs use
  // (grok-usage-style env read).
  readonly property string statePath: {
    var xdg = Quickshell.env("XDG_STATE_HOME")
    if (xdg && xdg !== "")
      return xdg + "/omarchy/agent-fleet/observations.jsonl"
    var home = Quickshell.env("HOME") || ""
    var user = Quickshell.env("USER") || "user"
    if (home === "")
      home = "/home/" + user
    return home + "/.local/state/omarchy/agent-fleet/observations.jsonl"
  }

  readonly property var intervalsCommand: [
    Qt.resolvedUrl("scripts/agent-fleet-intervals").toString().replace(/^file:\/\//, ""),
    "--state", attribution.statePath
  ]
  readonly property var weeklyCommand: [
    Qt.resolvedUrl("scripts/agent-fleet-aggregate").toString().replace(/^file:\/\//, ""),
    "--window", "weekly", "--state", attribution.statePath
  ]
  readonly property var sessionCommand: [
    Qt.resolvedUrl("scripts/agent-fleet-aggregate").toString().replace(/^file:\/\//, ""),
    "--window", "session", "--state", attribution.statePath
  ]

  // Per-refresh per-window cache:
  //   { weekly: { state, hasGap, summary }, session: { state, hasGap, summary } }
  // state ∈ "collecting" | "new_window" | "ready"; summary is the
  // agent-fleet-aggregate payload for that window, or null.
  property var windowData: null

  readonly property var entry: {
    var data = attribution.windowData
    if (data && attribution.window === "session" && data.session)
      return data.session
    if (data && attribution.window === "weekly" && data.weekly)
      return data.weekly
    return { state: "collecting", hasGap: false, summary: null }
  }

  readonly property string dataState: entry.state
  readonly property bool ready: attribution.dataState === "ready"
  readonly property var summary: entry.summary
  readonly property bool hasSummary: attribution.summary !== null

  // Phase 4.5 (gap and reset markers): display metadata for the window
  // being rendered, computed by the aggregate CLI — e.g.
  //   [ { "type": "reset_boundary", "at": "2026-09-26T12:00:00-05:00" },
  //     { "type": "gap",            "at": "2026-09-26T13:05:00-05:00" } ]
  // Strict pass-through: marker types and timestamps come straight from
  // the CLI output; nothing here is parsed, reinterpreted, or invented
  // (no durations, no confidence, no fabricated timestamps). The panel
  // only renders; when the window has no summary (collecting / new_window)
  // there are no markers.
  readonly property var markers: {
    var s = attribution.summary
    if (s && s.markers && s.markers.length)
      return s.markers
    return []
  }

  // ------------------------------------------------------ display helpers
  // "11" for 11.0, "1.5" for 1.5 — at most two decimals, no fabricated
  // precision.
  function formatPoints(n) {
    var v = Number(n)
    if (!isFinite(v))
      return "—"
    v = Math.round(v * 100) / 100
    if (v === Math.floor(v))
      return String(v)
    return String(v)
  }

  function formatCoverage(p) {
    if (p === null || p === undefined)
      return "—"
    var n = Number(p)
    if (!isFinite(n))
      return "—"
    return Math.round(n) + "%"
  }

  readonly property string observedText:
      attribution.hasSummary ? "Observed movement: " + formatPoints(summary.observedPoints) + " pp" : ""
  readonly property string coverageText:
      attribution.hasSummary ? "Coverage: " + formatCoverage(summary.coveragePercent) : ""

  // Agents in display order (the aggregate is already deterministic by
  // name); zero-attribution agents are dropped so nothing is presented as
  // evidence it is not. Phase 4 (expand/collapse) adds two render-only
  // fields: `id`, the stable agent identity from the aggregate (used as the
  // in-memory expansion-state key — never the display name), and `total`,
  // the agent's own totalAttributedPoints so the panel can keep the agent
  // total visible while its model rows are collapsed.
  readonly property var agentRows: {
    var out = []
    if (!attribution.summary || !attribution.summary.agents)
      return out
    for (var i = 0; i < attribution.summary.agents.length; i++) {
      var a = attribution.summary.agents[i]
      if (!a || Number(a.totalAttributedPoints) <= 0)
        continue
      var models = []
      for (var k = 0; k < (a.models || []).length; k++) {
        var m = a.models[k]
        models.push({
          name: String(m.model || ""),
          observed: Number(m.observedSinglePoints) || 0,
          estimated: Number(m.estimatedSharedPoints) || 0,
          total: (Number(m.observedSinglePoints) || 0) + (Number(m.estimatedSharedPoints) || 0)
        })
      }
      out.push({
        id: String(a.agent || ""),
        name: String(a.agent || ""),
        total: (Number(a.totalAttributedPoints) || 0),
        models: models
      })
    }
    return out
  }

  // "Unattributed: N pp" plus a one-line, non-zero-reasons breakdown.
  readonly property string unattributedLine: {
    var u = attribution.summary ? attribution.summary.unattributed : null
    if (!u)
      return ""
    var total = Number(u.noHermesActivityPoints) + Number(u.incompleteHermesObservabilityPoints)
                + Number(u.noCallableActivityPoints)
    if (total <= 0)
      return ""
    var parts = []
    if (Number(u.noHermesActivityPoints) > 0)
      parts.push("no Hermes activity " + formatPoints(Number(u.noHermesActivityPoints)) + " pp")
    if (Number(u.incompleteHermesObservabilityPoints) > 0)
      parts.push("partial observability " + formatPoints(Number(u.incompleteHermesObservabilityPoints)) + " pp")
    if (Number(u.noCallableActivityPoints) > 0)
      parts.push("no qualifying activity " + formatPoints(Number(u.noCallableActivityPoints)) + " pp")
    return (parts.length > 0 ? "Unattributed: " + formatPoints(total) + " pp (" + parts.join(" · ") + ")"
           : "Unattributed: " + formatPoints(total) + " pp")
  }

  readonly property bool hasAgentRows: {
    for (var i = 0; i < agentRows.length; i++)
      if (agentRows[i].models.length > 0)
        return true
    return false
  }

  readonly property string statusText: {
    if (attribution.dataState === "collecting")
      return "Collecting attribution data…"
    if (attribution.dataState === "new_window") {
      if (attribution.window === "session")
        return "New 5-hour window — collecting data…"
      return "New weekly window — collecting data…"
    }
    if (attribution.dataState === "ready" && entry.hasGap)
      return "Attribution incomplete — Codex observations contain gaps."
    return ""
  }

  readonly property string explanationLine:
      "Inferred from Codex allowance changes and local Hermes activity."

  readonly property string coverageFootnote:
      "Coverage is the share of observed movement Agent Fleet could attribute to an agent and model — not a share of the subscription."

  // ------------------------------------------------------------- refresh
  // Read-only recompute for BOTH windows. It never arms a snapshot, never
  // calls the collectors, and is never called from the window selector, so
  // none of it can recurse, refresh a collector, or write observations.
  signal settled()

  property bool refreshing: false
  property bool intervalsDone: false
  property bool weeklyDone: false
  property bool sessionDone: false

  function refresh() {
    if (attribution.refreshing)
      return
    // Child ids are in this item's scope (bare names), not properties of the
    // item — the same pattern the working Codex/Hermes collectors use. The
    // guard keeps a first-paint call (Component.onCompleted ordering) from
    // wedging "refreshing" true before the Process children exist.
    if (!intervalsProcess || !aggregateWeeklyProcess || !aggregateSessionProcess)
      return
    attribution.refreshing = true
    attribution.intervalsDone = false
    attribution.weeklyDone = false
    attribution.sessionDone = false
    if (!intervalsProcess.running) {
      intervalsProcess.command = attribution.intervalsCommand
      intervalsProcess.running = true
    }
    if (!aggregateWeeklyProcess.running) {
      aggregateWeeklyProcess.command = attribution.weeklyCommand
      aggregateWeeklyProcess.running = true
    }
    if (!aggregateSessionProcess.running) {
      aggregateSessionProcess.command = attribution.sessionCommand
      aggregateSessionProcess.running = true
    }
  }

  // The three commands are fast and independent; the last to finish
  // finalizes exactly once. Per-process flags (not a counter) because both
  // the stream-finished and the exited signals arrive per process — the
  // flags make the double arrival a no-op, and `refreshing` gates a second
  // finalize (same pattern as the v1 two-process version).
  function _markDone(which) {
    if (which === "intervals")
      attribution.intervalsDone = true
    else if (which === "weekly")
      attribution.weeklyDone = true
    else
      attribution.sessionDone = true
    if (attribution.intervalsDone && attribution.weeklyDone && attribution.sessionDone
            && attribution.refreshing) // exactly one finalize per refresh
      attribution._finish()
  }

  function _parseSummary(stream) {
    try {
      var body = String(stream.text || "").trim()
      if (body !== "")
        return JSON.parse(body)
    } catch (err) {
      return null
    }
    return null
  }

  // Per-window state — deliberately computed from that window's own
  // segment and its own interval rows so weekly and session never mix.
  function _windowState(win, summary, rows) {
    var segStart = (summary && summary.segmentStartAt !== null && summary.segmentStartAt !== undefined)
        ? String(summary.segmentStartAt) : ""
    if (segStart !== "") {
      // Current segment for this window exists: render it, flagging
      // Codex gaps in that same window.
      var lastReset = -1
      for (var i = 0; i < rows.length; i++) {
        var row = rows[i].codex ? rows[i].codex[win] : null
        if (row && row.status === "reset_boundary")
          lastReset = i
      }
      var hasGap = false
      for (var j = lastReset + 1; j < rows.length; j++) {
        var w = rows[j].codex ? rows[j].codex[win] : null
        if (w && w.status === "gap") {
          hasGap = true
          break
        }
      }
      return { state: "ready", hasGap: hasGap, summary: summary }
    }
    if (rows.length > 0)
      // Observations exist but nothing after the latest reset in this window.
      return { state: "new_window", hasGap: false, summary: null }
    return { state: "collecting", hasGap: false, summary: null }
  }

  function _finish() {
    var rows = []
    try {
      var rowsText = String(intervalsStream.text || "").trim()
      if (rowsText !== "") {
        var parsed = JSON.parse(rowsText)
        if (parsed && parsed.intervals)
          rows = parsed.intervals
      }
    } catch (err) {
      rows = []
    }
    attribution.windowData = {
      weekly: _windowState("weekly", _parseSummary(weeklyStream), rows),
      session: _windowState("session", _parseSummary(sessionStream), rows)
    }
    attribution.refreshing = false
    attribution.settled()
  }

  Process {
    id: intervalsProcess
    running: false
    command: []
    stdout: StdioCollector {
      id: intervalsStream
      waitForEnd: true
      onStreamFinished: function() { attribution._markDone("intervals") }
    }
    stderr: StdioCollector { waitForEnd: true }
    onExited: function(code, signal) {
      // Safety net: a crash or missing binary still settles the refresh.
      attribution._markDone("intervals")
    }
  }

  Process {
    id: aggregateWeeklyProcess
    running: false
    command: []
    stdout: StdioCollector {
      id: weeklyStream
      waitForEnd: true
      onStreamFinished: function() { attribution._markDone("weekly") }
    }
    stderr: StdioCollector { waitForEnd: true }
    onExited: function(code, signal) {
      attribution._markDone("weekly")
    }
  }

  Process {
    id: aggregateSessionProcess
    running: false
    command: []
    stdout: StdioCollector {
      id: sessionStream
      waitForEnd: true
      onStreamFinished: function() { attribution._markDone("session") }
    }
    stderr: StdioCollector { waitForEnd: true }
    onExited: function(code, signal) {
      attribution._markDone("session")
    }
  }

  // First paint: compute whatever is on disk (read-only; no snapshot).
  // Deferred to the next event-loop pass so the Process children exist.
  Component.onCompleted: Qt.callLater(function() { attribution.refresh() })
}

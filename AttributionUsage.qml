import QtQuick
import Quickshell
import Quickshell.Io

// AttributionUsage — the "Weekly Attribution" data source for the panel.
//
// It is a separate, read-only data source (the same shape as CodexUsage and
// HermesUsage) so that parsing and layout math never live in Panel.qml. It
// runs the repo's own aggregation chain exactly as the CLI does — two bare
// local commands, no shell, no network:
//
//   scripts/agent-fleet-intervals --state <observations.jsonl>
//   scripts/agent-fleet-aggregate --window weekly --state <observations.jsonl>
//
// Neither command writes anything: the snapshot store appends, and this
// component only reads it back. Refreshing this section therefore can never
// create a snapshot, never arms a wave, and never touches the collectors —
// the panel pulls it once, after a wave has settled (see Panel.qml).
//
// States:
//   "collecting"  no observations yet (no store, or the builder produced no
//                 intervals)
//   "new_window"  a weekly reset happened but no usable post-reset interval
//                 exists yet
//   "ready"       the current weekly segment produced a summary
//
// Copy rules (required terminology): Observed, Estimated, Unattributed,
// Coverage, pp. Never provider-truth words ("exact", "cost", "charged",
// "billing share", "official usage") — the upstream does not publish
// per-agent billing, and neither does this panel.

Item {
  id: attribution
  visible: false

  property int version: 1
  property string schema: "attribution-usage/v1"

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
  readonly property var aggregateCommand: [
    Qt.resolvedUrl("scripts/agent-fleet-aggregate").toString().replace(/^file:\/\//, ""),
    "--window", "weekly", "--state", attribution.statePath
  ]

  // "collecting" | "new_window" | "ready"
  property string dataState: "collecting"
  property bool refreshing: false
  property bool hasGap: false

  // The weekly aggregation summary (agent-fleet-aggregate payload) or null.
  property var summary: null

  // The interval rows (agent-fleet-intervals payload) or null — used only
  // to place the current segment's weekly-reset boundary.
  property var intervalRows: []

  readonly property bool ready: attribution.dataState === "ready"
  readonly property bool hasSummary: attribution.hasSummary_()

  function hasSummary_() { return attribution.summary !== null }

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
  // evidence it is not.
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
      out.push({ name: String(a.agent || ""), models: models })
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

  // "Unattributed: N pp" alone (breakdown stays in the faint meta line so
  // the rows stay scannable).
  readonly property bool hasAgentRows: {
    for (var i = 0; i < agentRows.length; i++)
      if (agentRows[i].models.length > 0)
        return true
    return false
  }

  readonly property string statusText: {
    if (attribution.dataState === "collecting")
      return "Collecting attribution data…"
    if (attribution.dataState === "new_window")
      return "New weekly window — collecting data…"
    if (attribution.dataState === "ready" && attribution.hasGap)
      return "Attribution incomplete — Codex observations contain gaps."
    return ""
  }

  readonly property string explanationLine:
      "Inferred from Codex allowance changes and local Hermes activity."

  readonly property string coverageFootnote:
      "Coverage is the share of observed movement Agent Fleet could attribute to an agent and model — not a share of the subscription."

  // ------------------------------------------------------------- refresh
  // Read-only recompute. It never arms a snapshot, never calls the
  // collectors, and is never called from its own handlers, so it cannot
  // recurse or write observations.
  signal settled()

  property bool intervalsDone: false
  property bool aggregateDone: false

  function refresh() {
    if (attribution.refreshing)
      return
    // Child ids are in this item's scope (bare names), not properties of the
    // item — the same pattern the working Codex/Hermes collectors use. The
    // guard keeps a first-paint call (Component.onCompleted ordering) from
    // wedging "refreshing" true before the Process children exist.
    if (!intervalsProcess || !aggregateProcess)
      return
    attribution.refreshing = true
    attribution.intervalsDone = false
    attribution.aggregateDone = false
    if (!intervalsProcess.running) {
      intervalsProcess.command = attribution.intervalsCommand
      intervalsProcess.running = true
    }
    if (!aggregateProcess.running) {
      aggregateProcess.command = attribution.aggregateCommand
      aggregateProcess.running = true
    }
  }

  // Both commands are fast and independent; the second to finish finalizes.
  function _markDone(which) {
    if (which === "intervals")
      attribution.intervalsDone = true
    else
      attribution.aggregateDone = true
    if (attribution.intervalsDone && attribution.aggregateDone
            && attribution.refreshing) // exactly one finalize per refresh
      attribution._finish()
  }

  function _finish() {
    // Parse the aggregate summary. Absent/unparseable ⇒ not ready.
    var summary = null
    try {
      var body = String(aggregateStream.text || "").trim()
      if (body !== "")
        summary = JSON.parse(body)
    } catch (err) {
      summary = null
    }
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
    attribution.summary = summary
    attribution.intervalRows = rows
    attribution.hasGap = false

    var segStart = (summary && summary.segmentStartAt !== null && summary.segmentStartAt !== undefined)
        ? String(summary.segmentStartAt) : ""
    if (segStart !== "") {
      // Current weekly segment exists: render it, flagging weekly Codex gaps.
      var lastReset = -1
      for (var i = 0; i < rows.length; i++) {
        var row = rows[i].codex ? rows[i].codex.weekly : null
        if (row && row.status === "reset_boundary")
          lastReset = i
      }
      for (var j = lastReset + 1; j < rows.length; j++) {
        var w = rows[j].codex ? rows[j].codex.weekly : null
        if (w && w.status === "gap") {
          attribution.hasGap = true
          break
        }
      }
      attribution.dataState = "ready"
    } else if (rows.length > 0) {
      // Observations exist but nothing after the latest weekly reset.
      attribution.dataState = "new_window"
    } else {
      attribution.dataState = "collecting"
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
      // Safety net: a crash or missing binary settles to "collecting".
      attribution._markDone("intervals")
    }
  }

  Process {
    id: aggregateProcess
    running: false
    command: []
    stdout: StdioCollector {
      id: aggregateStream
      waitForEnd: true
      onStreamFinished: function() { attribution._markDone("aggregate") }
    }
    stderr: StdioCollector { waitForEnd: true }
    onExited: function(code, signal) {
      attribution._markDone("aggregate")
    }
  }

  // First paint: compute whatever is on disk (read-only; no snapshot).
  // Deferred to the next event-loop pass so the Process children exist.
  Component.onCompleted: Qt.callLater(function() { attribution.refresh() })
}

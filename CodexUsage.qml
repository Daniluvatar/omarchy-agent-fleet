import QtQuick
import Quickshell
import Quickshell.Io

// Shared data source for the Agent Fleet bar slot and panel.
//
// CodexUsage runs the repo's collector (scripts/agent-fleet-codex) exactly the
// way the CLI does — a bare local command, no shell — and exposes one record.
// The bar and the panel both read that one record, so the two faces can never
// disagree.
//
// Everything here is derived from the collector's structured JSON. No raw
// upstream output (usageStatusText, authHelpText, exceptions) ever leaks into
// the state, and no credentials, tokens, or prompt/message content are read
// or stored.
Item {
  id: codex
  visible: false

  property int version: 1
  property string schema: "codex-usage/v1"
  // The repo's collector (a bare local command, no shell). It wraps the
  // Omarchy-owned `omarchy-agent-usage-codex --limits-only` and publishes the
  // one record this component renders. Resolved relative to this file, so
  // the plugin works from any install directory.
  readonly property var command: [Qt.resolvedUrl("scripts/agent-fleet-codex").toString().replace(/^file:\/\//, "")]

  // "loading" | "ready" | "unavailable"
  property string dataState: "loading"
  property var record: null
  property var fetchedAtMs: 0
  property bool refreshing: false
  property bool available: false
  property string tier: ""

  // The two meter windows, in the order the panel shows them. A null percent
  // is the panel's "—" — the collector emitted an available record but left
  // a window unmeasured.
  readonly property var slots: {
    var out = []
    if (!codex.record || !codex.record.available || !codex.record.limits)
      return out
    var lim = codex.record.limits
    var order = ["session", "weekly"]
    for (var i = 0; i < order.length; i++) {
      var s = order[i]
      var w = lim[s]
      if (!w)
        continue
      var pct = (w.usedPercent === 0 || w.usedPercent) ? Number(w.usedPercent) : null
      out.push({
        slot: s,
        label: (w.label !== undefined && w.label !== null) ? String(w.label) : (s === "session" ? "5h window" : "Weekly"),
        percent: isFinite(pct) ? pct : null,
        resetsAt: (w.resetsAt !== undefined && w.resetsAt !== null) ? String(w.resetsAt) : null
      })
    }
    return out
  }

  // The bar's headline: the fullest window currently reported.
  readonly property var barPercent: {
    var best = null
    var slots = codex.slots
    for (var i = 0; i < slots.length; i++) {
      if (slots[i].percent === null)
        continue
      if (best === null || slots[i].percent > best.percent)
        best = slots[i]
    }
    return best ? best.percent : null
  }

  readonly property string state: codex.dataState

  function refresh() {
    codex.refreshing = true
    watchdog.running = true
    // A failed refetch must not blank a known-good record; "loading" is only
    // the never-had-data case.
    if (!codex.record)
      codex.dataState = "loading"
    if (!collectProcess.running) {
      collectProcess.command = codex.command
      collectProcess.running = true
    }
  }

  function settleUnavailable() {
    if (codex.state === "loading")
      codex.dataState = "unavailable"
    codex.refreshing = false
  }

  function noteResult(stdoutText) {
    var body = String(stdoutText || "").trim()
    try {
      var parsed = JSON.parse(body)
      if (!parsed || parsed.schemaVersion !== 1 || parsed.provider !== "codex") {
        codex.settleUnavailable()
        return
      }
      codex.record = parsed
      codex.available = parsed.available === true
      codex.tier = (parsed.available && parsed.tier) ? String(parsed.tier) : ""
      codex.fetchedAtMs = Date.now()
      codex.dataState = codex.available ? "ready" : "unavailable"
    } catch (err) {
      // Malformed output: the last good record (or nothing) stays the truth.
      codex.settleUnavailable()
    }
    watchdog.stop()
    codex.refreshing = false
  }

  Process {
    id: collectProcess
    running: false
    command: []
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: function() { codex.noteResult(text) }
    }
    stderr: StdioCollector {
      waitForEnd: true
    }
    onExited: function(code, signal) {
      // A crash or missing binary ends with an empty stream, which already
      // settles the state; this is the safety net for the rest.
      codex.settleUnavailable()
      watchdog.stop()
    }
  }

  Timer {
    id: watchdog
    // More headroom than the collector's own socket timeout (20 s), so a slow
    // but healthy command still finishes.
    interval: 30000
    repeat: false
    running: false
    onRunningChanged: {
      if (watchdog.running)
        return
      // Budget expired. The collector carries its own 20 s internal timeout
      // and settles on exit; if it is still wedged, this closes the UI side
      // of it so the panel never sits on "loading".
      codex.settleUnavailable()
    }
  }

  Component.onCompleted: codex.refresh()
}

import QtQuick
import Quickshell
import Quickshell.Io

// Shared data source for the Hermes Activity section of the Agent Fleet panel.
//
// HermesUsage runs the repo's Hermes collector (scripts/agent-fleet-hermes)
// exactly the way the CLI does — a bare local command, no shell — and exposes
// the Phase 2 summary record in display-ready rows. All Hermes parsing and
// aggregation stays in the collector; this file only reshapes its stable JSON
// for the panel and never re-reads any Hermes state itself.
//
// The data is *activity*, not allowance: this component computes no shares,
// percentages, or attribution of any kind. No prompts, responses, session
// ids, credentials, or task buckets are read or exposed.
Item {
  id: hermes
  visible: false

  property int version: 1
  property string schema: "hermes-usage/v1"
  // The repo's Hermes collector (a bare local command, no shell). Resolved
  // relative to this file, so the plugin works from any install directory.
  readonly property var command: [Qt.resolvedUrl("scripts/agent-fleet-hermes").toString().replace(/^file:\/\//, "")]

  // "loading" | "ready" | "unavailable"
  property string dataState: "loading"
  property var record: null
  property var fetchedAtMs: 0
  property bool refreshing: false
  property bool available: false

  // The collector's default lookback, stated verbatim in the panel.
  readonly property int lookbackDays: 7

  readonly property int totalCalls: hermes.record && hermes.record.summary ? Number(hermes.record.summary.totalCalls) || 0 : 0
  readonly property int activeAgents: hermes.record && hermes.record.summary ? Number(hermes.record.summary.totalAgents) || 0 : 0
  readonly property int profilesDiscovered: hermes.record && hermes.record.source ? Number(hermes.record.source.profilesDiscovered) || 0 : 0

  // Agents whose profile could not be read (the collector isolates them;
  // the panel just says so, without details).
  readonly property int unreadableAgents: {
    var n = 0
    if (!hermes.record || !hermes.record.available || !hermes.record.agents)
      return 0
    var list = hermes.record.agents
    for (var i = 0; i < list.length; i++)
      if (list[i] && list[i].error)
        n++
    return n
  }

  // Display rows: agents with activity in the window, busiest first. Quiet
  // profiles (zero calls in the lookback) and unreadable ones are omitted —
  // the section header and meta line say what the window covers.
  readonly property var agents: {
    var out = []
    if (!hermes.record || !hermes.record.available || !hermes.record.agents)
      return out
    var list = hermes.record.agents
    for (var i = 0; i < list.length; i++) {
      var a = list[i]
      if (!a || a.error || Number(a.totalCalls) <= 0)
        continue
      var models = []
      var ms = a.models || []
      for (var j = 0; j < ms.length; j++) {
        var m = ms[j]
        if (!m || Number(m.calls) <= 0)
          continue
        models.push({
          model: String(m.model || ""),
          label: hermes.modelLabel(m.model),
          calls: Number(m.calls) || 0,
          // "" when the source has no token totals to show.
          tokenText: hermes.tokenText(m.inputTokens, m.outputTokens)
        })
      }
      out.push({
        id: String(a.id || ""),
        displayName: String(a.displayName || a.id || ""),
        totalCalls: Number(a.totalCalls) || 0,
        models: models
      })
    }
    out.sort(function (x, y) {
      if (y.totalCalls !== x.totalCalls)
        return y.totalCalls - x.totalCalls
      return x.displayName < y.displayName ? -1 : (x.displayName > y.displayName ? 1 : 0)
    })
    return out
  }

  // "gpt-6-sol" -> "GPT-6 Sol", "gpt-5.6-terra" -> "GPT-5.6 Terra".
  // Presentation only; the collector's raw model string stays on `model`
  // for anything that needs the exact value.
  //
  // A hyphen keeps a model family attached to its version ("GPT-6"); the
  // hyphen after a part carrying a digit is the version handing over to the
  // name, so that one becomes a space ("6 Sol"). Same reading the
  // first-party Agents widget applies to model ids.
  function modelLabel(raw) {
    var text = String(raw || "").trim()
    if (text === "")
      return ""
    var label = ""
    var previous = ""
    var parts = text.split("-")
    for (var i = 0; i < parts.length; i++) {
      var p = parts[i]
      if (p === "")
        continue
      var word = (previous === "" && p.length <= 3 && /^[a-z]+$/.test(p))
          ? p.toUpperCase()
          : p.charAt(0).toUpperCase() + p.slice(1)
      if (label === "")
        label = word
      else if (/\d/.test(previous))
        label += " " + word
      else
        label += "-" + word
      previous = p
    }
    return label
  }

  // Compact "1.1M in · 95K out"; "" when there is nothing to show. Cache
  // counters stay in the collector contract and are not rendered.
  function tokenText(inputTokens, outputTokens) {
    var inTok = Number(inputTokens) || 0
    var outTok = Number(outputTokens) || 0
    if (inTok === 0 && outTok === 0)
      return ""
    return hermes.formatTokens(inTok) + " in · " + hermes.formatTokens(outTok) + " out"
  }

  function formatTokens(n) {
    if (n < 1000)
      return String(n)
    var units = [["B", 1000000000], ["M", 1000000], ["K", 1000]]
    for (var i = 0; i < units.length; i++) {
      if (n >= units[i][1]) {
        var v = n / units[i][1]
        // Two significant digits at most: 123K, 4.5K, 1.1M.
        return (v >= 100 ? String(Math.round(v)) : String(Math.round(v * 10) / 10)) + units[i][0]
      }
    }
    return String(n)
  }

  // Emitted once per settle path so the panel can observe "this collector
  // finished one refresh" without polling.
  signal settled()

  function refresh() {
    hermes.refreshing = true
    watchdog.running = true
    // A failed refetch must not blank a known-good record; "loading" is only
    // the never-had-data case.
    if (!hermes.record)
      hermes.dataState = "loading"
    if (!collectProcess.running) {
      collectProcess.command = hermes.command
      collectProcess.running = true
      startCheck.restart()
    }
  }

  // A failed start (missing or non-executable collector) never emits exited,
  // so a start that is not even running shortly after launch settles
  // immediately instead of waiting for the watchdog. Start failures land
  // asynchronously, hence the delay rather than an inline check.
  Timer {
    id: startCheck
    interval: 400
    repeat: false
    running: false
    onTriggered: {
      if (hermes.refreshing && !collectProcess.running && collectProcess.exitCode !== 0)
        hermes.settleUnavailable()
    }
  }

  function settleUnavailable() {
    if (hermes.dataState === "loading")
      hermes.dataState = "unavailable"
    hermes.refreshing = false
    hermes.settled()
  }

  function noteResult(stdoutText) {
    var body = String(stdoutText || "").trim()
    try {
      var parsed = JSON.parse(body)
      if (!parsed || parsed.schemaVersion !== 1 || parsed.harness !== "hermes") {
        hermes.settleUnavailable()
        return
      }
      hermes.record = parsed
      hermes.available = parsed.available === true
      hermes.fetchedAtMs = Date.now()
      hermes.dataState = hermes.available ? "ready" : "unavailable"
    } catch (err) {
      // Malformed output: the last good record (or nothing) stays the truth.
      hermes.settleUnavailable()
    }
    watchdog.stop()
    hermes.refreshing = false
    hermes.settled()
  }

  Process {
    id: collectProcess
    running: false
    command: []
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: function() { hermes.noteResult(text) }
    }
    stderr: StdioCollector {
      waitForEnd: true
    }
    onExited: function(code, signal) {
      // A crash or missing binary ends with an empty stream, which already
      // settles the state; this is the safety net for the rest.
      hermes.settleUnavailable()
      watchdog.stop()
    }
  }

  Timer {
    id: watchdog
    // The local scan is ~50 ms; this only exists so a wedged process can
    // never leave the section sitting on "loading".
    interval: 30000
    repeat: false
    running: false
    onRunningChanged: {
      if (watchdog.running)
        return
      hermes.settleUnavailable()
    }
  }

  Component.onCompleted: hermes.refresh()
}

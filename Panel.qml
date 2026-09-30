import QtQuick
import QtQuick.Controls
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

// Agent Fleet bar widget + panel.
//
// One widget, two faces: a bar slot that shows the hot Codex number, and a
// panel that shows both meter windows with reset countdowns. Both read the
// one CodexUsage record below (the repo collector, scripts/agent-fleet-codex),
// so the bar and the panel can never disagree.
//
// Only one user-facing usage-unavailable state exists: the window rows
// render whatever the record says, and when the record is missing, stale, or
// unavailable they render "—".
//
// The panel also carries a Hermes Activity section fed by HermesUsage
// (scripts/agent-fleet-hermes). Hermes rows are activity counts only; they
// never feed the bar percentage, the window bars, or any attribution.
//
// Phase 3 adds a third, clearly separate section — Attribution —
// fed by AttributionUsage, a read-only source over the snapshot store that
// renders the repo's own aggregation chain (agent-fleet-intervals +
// agent-fleet-aggregate). It is inferred only: estimated, unattributed,
// and coverage never read as provider-billed truth, and the section
// refreshes once per settled refresh wave without arming or creating a
// snapshot of its own. Phase 4 adds the native [ Weekly ] [ 5-hour ]
// ButtonGroup selector (AttributionUsage fetches and caches BOTH windows
// every refresh; the selector only picks the cached summary to render —
// switching is display-only and never refreshes a collector, takes a
// snapshot, or writes observations.jsonl or segments.jsonl) and
// agent / model expand-collapse: each agent row is a clickable ▸/▾
// header that keeps the agent total visible while its model rows are
// collapsed, with the expansion state held purely in memory (keyed by
// stable agent ID, collapsed by default) — toggling changes only the
// presentation.
Panel {
  id: root
  moduleName: "io.github.daniluvatar.agent-fleet"
  ipcTarget: "io.github.daniluvatar.agent-fleet"

  // The base Panel's built-in handler stays off so this file owns the target,
  // as the first-party agents widget and the grok-usage plugin do.
  manageIpc: false

  IpcHandler {
    target: root.ipcTarget
    function open(): void { root.open() }
    function close(): void { root.close() }
    function show(): void { root.open() }
    function hide(): void { root.close() }
    function toggle(): void { root.toggle() }
    function refresh(): string { root.refresh(); return "ok" }
  }

  // The bar sizes each slot from the item's implicit size.
  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  onOpenedChanged: if (opened) {
    Qt.callLater(function() { keyCatcher.forceActiveFocus() })
    root.refresh()
  }

  // Auto-refresh on the configured cadence; the bar and panel both pick up
  // the new record when it lands.
  Timer {
    interval: root.refreshInterval * 1000
    repeat: true
    running: true
    onTriggered: root.refresh()
  }

  readonly property color foreground: bar ? bar.foreground : Color.foreground
  readonly property color urgent: bar ? bar.urgent : Color.urgent
  readonly property color dim: Qt.darker(foreground, 1.6)
  readonly property color faint: Qt.darker(foreground, 2.4)
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family

  // ------------------------------------------------------------- settings
  readonly property int refreshInterval: Number(setting("refreshIntervalSec", 900))
  // Declared in manifest.json (barWidget.schema): when off, the bar shows
  // the fleet label without a number. The bar's urgent tint (session window
  // at or over 80 %) is the at-a-glance signal and works either way.
  readonly property bool showPercentInBar: setting("showPercentInBar", true) === true
  // Phase 5 (Task 7): which window's live attribution the panel OPENS on —
  // "weekly" (existing default) or "session" (5-hour). Presentation-only:
  // it only seeds the [ Weekly ] [ 5-hour ] selector's initial selection;
  // AttributionUsage still fetches and caches BOTH windows every settle,
  // switching is display-only, and the value changes no data or math.
  readonly property string defaultAttributionWindow:
    setting("defaultAttributionWindow", "weekly") === "session" ? "session" : "weekly"
  // Phase 5 (Task 7): whether the Recent Segments section (Task 6) shows.
  // Presentation-only: hiding it renders nothing and stops further
  // HistoryUsage refreshes (enabled=false); the section is strictly
  // read-only either way — the segments store is never written by it.
  readonly property bool showRecentSegments: setting("showRecentSegments", true) === true

  // ------------------------------------------------------------- data
  readonly property var codexUsage: CodexUsage {}

  readonly property string state: codexUsage.dataState
  readonly property bool ready: state === "ready"
  readonly property bool loading: state === "loading"
  readonly property string tier: codexUsage.tier
  readonly property string tierWord: tier !== "" ? tier.charAt(0).toUpperCase() + tier.slice(1) : ""

  readonly property var windows: codexUsage.slots
  readonly property var barPercent: codexUsage.barPercent // number | null

  // Hermes activity (separate collector, separate record). Display rows and
  // formatting live in HermesUsage; nothing here feeds the bar or the
  // allowance windows.
  readonly property var hermesUsage: HermesUsage {}
  readonly property bool hermesReady: hermesUsage.dataState === "ready"
  readonly property bool hermesLoading: hermesUsage.dataState === "loading"

  // Phase 3/4: "Attribution" — its own data source (AttributionUsage),
  // read-only over the snapshot store, now serving BOTH provider windows
  // (weekly default, session / 5-hour selectable below). The panel never
  // aggregates inline; the section below only renders what the source
  // exposes.
  readonly property var attributionUsage: AttributionUsage { window: root.attributionWindow }

  // Phase 5 (Task 6): "Recent Segments" — its own strictly read-only
  // data source (HistoryUsage) over segments.jsonl: the CLI's --list
  // mode renders the already-persisted completed segments (both windows
  // coexist, newest first), so this source can never append, prune,
  // rewrite the store, or even read observations.jsonl. It is NOT
  // filtered by the window selector — the selector only chooses the
  // live attribution summary above.
  readonly property var historyUsage: HistoryUsage {}
  // [ Weekly ] [ 5-hour ] selector state (Phase 4 session / 5-hour
  // attribution view). Pure display state: changing it re-renders the
  // corresponding already-computed cached summary. It never refreshes a
  // collector, never takes a snapshot, and never writes observations.jsonl
  // or segments.jsonl. The initial value comes from the Task 7 manifest
  // setting defaultAttributionWindow (weekly by default, so existing
  // behavior is unchanged); the first selector click breaks the binding
  // and the choice remains per-shell session state, exactly as before.
  property string attributionWindow: root.defaultAttributionWindow

  // Phase 5 (Task 7): apply the showRecentSegments manifest setting to the
  // HistoryUsage data source (default: true = active). Done at completion:
  // when off, the source stays inert for all later refresh waves.
  Component.onCompleted: root.historyUsage.enabled = root.showRecentSegments

  // Phase 4 (agent / model expand-collapse). In-memory ONLY: the list of
  // stable agent IDs currently expanded, collapsed by default (empty). The
  // key is the agent ID from the aggregate — never the display name — so
  // rows stay addressable deterministically, and the choice is naturally
  // shared across the weekly / 5-hour selection (expansion is presentation
  // of whichever window is shown, keyed by the same identity). Toggling is
  // pure presentation: it issues no commands, refreshes no collector, arms
  // no snapshot, writes neither observations.jsonl nor segments.jsonl, and
  // creates no persistent setting. It is reset to collapsed on every shell
  // (re)load, which is correct — nothing about it needs to survive.
  property var expandedAgentIds: []

  function isAgentExpanded(agentId) {
    for (var i = 0; i < root.expandedAgentIds.length; i++)
      if (root.expandedAgentIds[i] === agentId)
        return true
    return false
  }

  function toggleAgentExpanded(agentId) {
    var next = []
    var present = false
    for (var i = 0; i < root.expandedAgentIds.length; i++) {
      if (root.expandedAgentIds[i] === agentId) {
        present = true
        continue
      }
      next.push(root.expandedAgentIds[i])
    }
    if (!present)
      next.push(agentId)
    root.expandedAgentIds = next
  }

  function formatPercent(p) {
    if (p === null || p === undefined)
      return ""
    var n = Number(p)
    if (!isFinite(n))
      return ""
    return Math.round(n) + "%"
  }

  function formatClock(ms) {
    if (!ms)
      return ""
    var d = new Date(ms)
    var h = d.getHours()
    var m = d.getMinutes()
    return ((h < 10) ? "0" : "") + h + ":" + ((m < 10) ? "0" : "") + m
  }

  function formatCountdown(resetIso) {
    if (!resetIso)
      return ""
    var t = new Date(resetIso).getTime()
    if (isFinite(t)) {
      var ms = Math.max(0, t - Date.now())
      if (ms === 0)
        return "now"
      var totalMinutes = Math.round(ms / 60000)
      var days = Math.floor(totalMinutes / 1440)
      var hours = Math.floor((totalMinutes % 1440) / 60)
      var minutes = totalMinutes % 60
      if (days > 0)
        return days + (days === 1 ? " day" : " days") + " " + hours + "h"
      if (hours > 0)
        return hours + "h " + minutes + "m"
      return Math.max(1, minutes) + "m"
    }
    return formatClock(t)
  }

  // Hermes section copy. The meta line states the window and what it counts;
  // the disclaimer keeps activity clearly separate from allowance usage.
  readonly property string hermesMetaLine: {
    if (!root.hermesReady)
      return ""
    var agents = root.hermesUsage.activeAgents
    var parts = ["Last " + root.hermesUsage.lookbackDays + " days",
                 agents + (agents === 1 ? " active agent" : " active agents"),
                 root.formatCount(root.hermesUsage.totalCalls) + " calls"]
    if (root.hermesUsage.unreadableAgents > 0)
      parts.push(root.hermesUsage.unreadableAgents + " unreadable")
    return parts.join(" · ")
  }

  readonly property string hermesStatusLine: {
    if (root.hermesLoading)
      return "Checking Hermes activity…"
    if (!root.hermesReady)
      return "Hermes activity unavailable"
    if (root.hermesUsage.agents.length === 0)
      return "No Codex activity in the last " + root.hermesUsage.lookbackDays + " days"
    return ""
  }

  function formatCount(n) {
    return String(Math.round(n)).replace(/\B(?=(\d{3})+(?!\d))/g, ",")
  }

  function refresh() {
    // Only a refresh wave arms a snapshot attempt. Redraws, re-activation
    // without refresh, and any property invalidation never arm one, so UI
    // redraws can never create observations.
    root.snapshotArmed = true
    if (codexUsage && codexUsage.refresh)
      codexUsage.refresh()
    if (hermesUsage && hermesUsage.refresh)
      hermesUsage.refresh()
  }

  // -------------------------------------------------- Phase 3 snapshot capture
  // One conservative attempt per refresh wave, and only after BOTH collectors
  // have settled for that wave. The snapshot store does its own fresh
  // collection (a failed Codex refresh therefore lands as codex.available
  // = false — a gap — never as a copy of the stale UI record), enforces the
  // ~60 s minimum spacing against the newest observation, and fails
  // diagnostically without touching the panel.
  readonly property var snapshotCommand:
      [Qt.resolvedUrl("scripts/agent-fleet-snapshot").toString().replace(/^file:\/\//, "")]

  property bool snapshotArmed: false

  Connections {
    target: codexUsage
    // Modern function syntax (property-form onFoo in Connections is
    // deprecated and logs a warning on every scene load).
    function onSettled() { root.maybeSnapshot() }
  }

  Connections {
    target: hermesUsage
    function onSettled() { root.maybeSnapshot() }
  }

  function maybeSnapshot() {
    if (!root.snapshotArmed)
      return
    if (codexUsage && codexUsage.refreshing)
      return
    if (hermesUsage && hermesUsage.refreshing)
      return
    root.snapshotArmed = false
    if (!snapshotProcess.running) {
      snapshotProcess.command = root.snapshotCommand
      snapshotProcess.running = true
    }
    // After the wave has settled (this is the only call site), recompute
    // the attribution view from the store. Read-only: it can never arm a
    // snapshot or refresh a collector, so no recursion, no extra capture.
    if (root.attributionUsage && root.attributionUsage.refresh)
      root.attributionUsage.refresh()
    // Recent Segments re-renders whatever the store holds now (a segment
    // may have been just persisted for a completed window). Read-only:
    // the list path never writes, prunes, or touches observations.jsonl.
    if (root.historyUsage && root.historyUsage.refresh)
      root.historyUsage.refresh()
  }

  Process {
    id: snapshotProcess
    running: false
    command: []
    stdout: StdioCollector {
      waitForEnd: true
    }
    stderr: StdioCollector {
      waitForEnd: true
    }
    onExited: function(code, signal) {
      // Conservative by contract: a failed or spacing-skipped capture is
      // diagnostic only. It never throws, never changes the panel state,
      // and never disturbs the collector records.
    }
  }

  // Bar slot: Codex percent when one is reported and the setting allows it,
  // otherwise the fleet name.
  readonly property string barLabel: {
    if (!root.showPercentInBar)
      return "Agent Fleet"
    var p = root.barPercent
    if (p !== null)
      return "Codex " + formatPercent(p)
    return "Agent Fleet"
  }

  readonly property string panelStatusLine: {
    if (loading)
      return "Checking Codex…"
    if (!ready)
      return "Usage unavailable — authenticate with Codex and try again"
    var parts = []
    for (var i = 0; i < windows.length; i++) {
      parts.push(windows[i].label + (windows[i].percent === null ? " —" : " " + formatPercent(windows[i].percent)))
    }
    if (windows.length === 0)
      return codexUsage.fetchedAtMs !== 0 ? "Updated " + formatClock(codexUsage.fetchedAtMs) + "  ·  no window data" : "No window data"
    var partsLine = parts.join("   ")
    if (codexUsage.stale)
      // Stale continuity: last-good value still visible, flagged, with when
      // it was last confirmed.
      return "Last successful update " + (formatClock(codexUsage.lastGoodMs !== 0 ? codexUsage.lastGoodMs : codexUsage.fetchedAtMs)) + "  ·  " + partsLine
    return codexUsage.fetchedAtMs !== 0 ? "Updated " + formatClock(codexUsage.fetchedAtMs) + "  ·  " + partsLine : partsLine
  }

  // ------------------------------------------------------- bar button
  WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: root.barLabel
    tooltipText: "Agent Fleet" + (root.tierWord !== "" ? " — Codex " + root.tierWord : "")
    active: root.sessionUrgent
    activeColor: root.urgent
    fontSize: Style.font.body
    onPressed: function (buttonCode) {
      if (buttonCode === Qt.RightButton)
        root.refresh()
      else if (buttonCode !== Qt.MiddleButton)
        root.toggle()
    }
  }

  readonly property bool sessionUrgent: {
    for (var i = 0; i < windows.length; i++)
      if (windows[i].slot === "session" && windows[i].percent !== null && windows[i].percent >= 80)
        return true
    return false
  }

  // ------------------------------------------------------------ panel
  KeyboardPanel {
    id: panel
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(420))
    contentHeight: panel.fittedContentHeight(content.implicitHeight, Style.space(640))

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent

      onCloseRequested: root.close()
      onMoveRequested: function (dx, dy) {
        // First-party pattern (see the agents panel): arrows are the panel's
        // scroll mechanism; same step size and clamping expression.
        if (dy !== 0)
          flick.contentY = Math.min(
              Math.max(0, flick.contentY + dy * Style.space(56)),
              Math.max(0, flick.contentHeight - flick.height))
      }
      onActivateRequested: root.refresh()
      onTabRequested: function (direction) { root.switchPanel(direction) }
      onTextKey: function (t) {
        if (t === "r" || t === "R")
          root.refresh()
      }

      Flickable {
        id: flick
        anchors.fill: parent
        contentWidth: width
        contentHeight: content.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        flickableDirection: Flickable.VerticalFlick
        interactive: contentHeight > height
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

        Column {
          id: content
          width: flick.width
          spacing: Style.space(12)

          PanelSectionHeader {
            width: parent.width
            text: "Agent Fleet"
            foreground: root.foreground
            fontFamily: root.fontFamily
          }

          PanelHero {
            width: parent.width
            iconComponent: heroIcon
            title: "Codex"
            meta: root.tierWord
            foreground: root.foreground
            fontFamily: root.fontFamily

            Component {
              id: heroIcon
              Text {
                text: "◆"
                color: root.foreground
                opacity: root.ready ? 1 : 0.4
                font.family: root.fontFamily
                font.pixelSize: Style.font.display
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
              }
            }

            trailingControl: Component {
              PanelActionButton {
                id: refreshAction
                iconText: "\uf021"
                tooltipText: "Refresh"
                foreground: root.foreground
                fontFamily: root.fontFamily
                opacity: root.loading ? 0.45 : 1.0
                onHovered: function (hovered) { keyCatcher.blocked = hovered }
                onClicked: root.refresh()
              }
            }
          }

          PanelSeparator { width: parent.width }

          // Window rows: session then weekly — whatever the record says.
          Repeater {
            model: root.windows
            delegate: Item {
              width: parent.width
              height: windowColumn.implicitHeight

              Column {
                id: windowColumn
                width: parent.width
                spacing: Style.space(4)

                Text {
                  text: {
                    if (modelData.slot === "session")
                      return "5-HOUR WINDOW"
                    return "WEEKLY"
                  }
                  color: root.dim
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                  font.bold: true
                }

                Row {
                  spacing: Style.space(6)
                  Text {
                    text: modelData.percent === null ? "—" : formatPercent(modelData.percent) + " used"
                    color: root.foreground
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.body
                    font.bold: true
                  }
                  Text {
                    visible: modelData.percent === null && modelData.resetsAt !== null
                    anchors.verticalCenter: parent.verticalCenter
                    text: "resets " + formatCountdown(modelData.resetsAt)
                    color: root.dim
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.caption
                  }
                }

                Rectangle {
                  visible: modelData.percent !== null
                  width: parent.width
                  height: 4
                  radius: 2
                  color: Style.selectedFillFor(root.foreground, Color.accent, 0.18)
                  Rectangle {
                    width: parent ? (parent.width * Math.min(100, Math.max(0, modelData.percent))) / 100 : 0
                    height: parent.height
                    radius: parent.radius
                    color: root.sessionUrgent && modelData.slot === "session"
                        ? root.urgent
                        : Qt.darker(root.foreground, 1.1)
                  }
                }

                Text {
                  visible: modelData.resetsAt !== null && modelData.percent !== null
                  text: "Resets in " + formatCountdown(modelData.resetsAt)
                  color: root.dim
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                }
              }
            }
          }

          PanelSeparator { width: parent.width }

          // Hermes Activity: agent/model call counts observed locally in the
          // lookback window. Activity counts only — no allowance share is
          // shown or implied here; rows and states come from HermesUsage.
          Column {
            width: parent.width
            spacing: Style.space(6)

            PanelSectionHeader {
              width: parent.width
              text: "Hermes Activity"
              foreground: root.foreground
              fontFamily: root.fontFamily
            }

            Text {
              visible: text !== ""
              width: parent.width
              text: root.hermesMetaLine
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
            }

            Text {
              visible: text !== ""
              width: parent.width
              text: root.hermesStatusLine
              // Urgent only for the unavailable state; loading and the quiet
              // "no activity" case read as notes, as the Codex row above does.
              color: root.hermesReady || root.hermesLoading ? root.dim : root.urgent
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
            }

            Repeater {
              model: root.hermesUsage.agents
              delegate: Column {
                width: parent.width
                spacing: Style.space(1)

                Item {
                  width: parent.width
                  height: Math.max(agentName.implicitHeight, agentCalls.implicitHeight)
                  Text {
                    id: agentName
                    anchors.left: parent.left
                    anchors.verticalCenter: parent.verticalCenter
                    text: modelData.displayName
                    color: root.foreground
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.body
                    font.bold: true
                  }
                  // Redundant with a lone model row, so only shown when an
                  // agent splits across several models.
                  Text {
                    id: agentCalls
                    visible: modelData.models.length > 1
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    text: root.formatCount(modelData.totalCalls) + (modelData.totalCalls === 1 ? " call" : " calls")
                    color: root.dim
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.caption
                  }
                }

                Repeater {
                  model: modelData.models
                  delegate: Column {
                    width: parent.width
                    spacing: 0

                    Item {
                      width: parent.width
                      height: Math.max(modelName.implicitHeight, modelCalls.implicitHeight)
                      Text {
                        id: modelName
                        anchors.left: parent.left
                        anchors.leftMargin: Style.space(8)
                        anchors.verticalCenter: parent.verticalCenter
                        text: modelData.label
                        color: root.foreground
                        opacity: 0.85
                        font.family: root.fontFamily
                        font.pixelSize: Style.font.caption
                      }
                      Text {
                        id: modelCalls
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        text: root.formatCount(modelData.calls) + (modelData.calls === 1 ? " call" : " calls")
                        color: root.dim
                        font.family: root.fontFamily
                        font.pixelSize: Style.font.caption
                      }
                    }

                    Text {
                      visible: text !== ""
                      width: parent.width
                      leftPadding: Style.space(8)
                      text: modelData.tokenText
                      color: root.faint
                      font.family: root.fontFamily
                      font.pixelSize: Style.font.caption
                    }
                  }
                }
              }
            }

            Text {
              visible: root.hermesReady
              width: parent.width
              text: "Activity counts only — not a share of your Codex allowance."
              color: root.faint
              opacity: 0.8
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
            }
          }

          PanelSeparator { width: parent.width }

          // Attribution (Phase 3, extended in Phase 4): inferred
          // attribution only. All parsing/values live in AttributionUsage;
          // this block only renders. Separate from the allowance above and
          // must never read back as provider-billed truth. The native
          // [ Weekly ] [ 5-hour ] selector picks the cached window to
          // render — display-only, no commands, no data mutation.
          Column {
            width: parent.width
            spacing: Style.space(4)

            PanelSectionHeader {
              width: parent.width
              text: "Attribution"
              foreground: root.foreground
              fontFamily: root.fontFamily
            }

            // Native shell-kit selector (qs.Ui ButtonGroup): the same
            // mutually-exclusive chip row the kit itself uses
            // (options/value/changed). Selection only drives
            // root.attributionWindow; AttributionUsage already holds both
            // windows' computed summaries, so switching issues no commands
            // and mutates no data.
            ButtonGroup {
              width: parent.width
              options: [
                { value: "weekly", label: "Weekly" },
                { value: "session", label: "5-hour" }
              ]
              value: root.attributionWindow
              foreground: root.foreground
              background: Color.background
              accent: Color.accent
              fontFamily: root.fontFamily
              onChanged: function(v) { root.attributionWindow = v }
            }

            Text {
              width: parent.width
              text: root.attributionUsage.explanationLine
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
            }

            // Phase 5 (Task 7): expand/collapse discoverability — one
            // faint hint line, shown only while there is an agent to
            // expand. No behavior or state change beyond rendering.
            Text {
              visible: root.attributionUsage.hasAgentRows
              width: parent.width
              text: "Click an agent to expand or collapse its models"
              color: root.faint
              opacity: 0.8
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
            }

            // Empty / waiting states. Deliberately unadorned: no zeros are
            // rendered as if they were evidence before data exists.
            Text {
              visible: root.attributionUsage.statusText !== ""
              width: parent.width
              text: root.attributionUsage.statusText
              color: (root.attributionUsage.dataState === "ready" ? root.urgent : root.dim)
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
            }

            Column {
              // Shown whenever usable attribution data exists — including
              // when a mid-segment gap requires the "Attribution incomplete"
              // note above it: valid attribution within the same reset
              // segment is retained, never dropped.
              visible: root.attributionUsage.ready
              width: parent.width
              spacing: Style.space(4)

              // Phase 4.5 (gap and reset markers): compact rows for the
              // evidence discontinuities of THIS window. Marker type and
              // time come verbatim from the aggregate CLI via
              // AttributionUsage.markers (pure pass-through) — the
              // delegate only renders glyphs and the real clock time;
              // no parsing, no invented timestamps, durations, or
              // confidence. Markers never alter the numbers below.
              Repeater {
                model: root.attributionUsage.markers
                delegate: Text {
                  width: parent.width
                  text: (modelData.type === "reset_boundary"
                         ? "↻ Reset boundary"
                         : "○ Evidence gap")
                       + (modelData.at ? " · " + String(modelData.at).slice(11, 16) : "")
                  color: root.dim
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                }
              }

              Text {
                text: root.attributionUsage.observedText
                color: root.foreground
                font.family: root.fontFamily
                font.pixelSize: Style.font.body
                font.bold: true
              }

              Text {
                text: root.attributionUsage.coverageText
                color: root.foreground
                font.family: root.fontFamily
                font.pixelSize: Style.font.body
              }

              // Phase 4 (agent / model expand-collapse): each agent renders
              // as one clickable header row — "▸ name … N pp" collapsed,
              // "▾ name … N pp" expanded — with the model rows visible only
              // while expanded. Toggling is the ▸/▾ prefix + click on this
              // row; the state is root.expandedAgentIds (in-memory, keyed by
              // stable agent ID, collapsed by default). The agent total
              // stays visible in the header in both states, nothing is ever
              // hidden, and Unattributed below stays separate — it is never
              // folded into an agent.
              Repeater {
                model: root.attributionUsage.agentRows
                delegate: Column {
                  width: parent.width
                  spacing: Style.space(1)

                  // Agent header: always visible, clickable.
                  // NOTE: no anchors inside this Row — anchored children are
                  // excluded from Row layout and would collapse the row to
                  // zero height (the Task 4 first pass did this and the
                  // rows were invisible in the live panel). Children share
                  // one caption font size, so top-edge stacking reads as
                  // vertical centering; the explicit height pins the row so
                  // the MouseArea below has a stable target.
                  Row {
                    id: agentHeaderRow
                    width: parent.width
                    height: agentNameText.implicitHeight
                    spacing: 0
                    Text {
                      id: agentNameText
                      text: (root.isAgentExpanded(modelData.id) ? "\u25be " : "\u25b8 ") + modelData.name
                      color: root.foreground
                      opacity: 0.9
                      font.family: root.fontFamily
                      font.pixelSize: Style.font.caption
                      font.bold: true
                    }
                    Item {
                      width: 10
                      height: 1
                    }
                    Text {
                      width: Math.max(0, agentHeaderRow.width - agentNameText.width - 10)
                      horizontalAlignment: Text.AlignRight
                      text: root.attributionUsage.formatPoints(modelData.total) + " pp"
                      color: root.foreground
                      opacity: 0.75
                      font.family: root.fontFamily
                      font.pixelSize: Style.font.caption
                    }
                    MouseArea {
                      width: parent.width
                      height: parent.height
                      hoverEnabled: true
                      cursorShape: Qt.PointingHandCursor
                      onClicked: root.toggleAgentExpanded(modelData.id)
                    }
                  }

                  // Model rows: shown only while this agent is expanded.
                  // observed / estimated / total per model stay distinct.
                  Column {
                    visible: root.isAgentExpanded(modelData.id)
                    width: parent.width
                    spacing: Style.space(1)
                    Repeater {
                      model: modelData.models
                      delegate: Row {
                        spacing: Style.space(4)
                        Text {
                          text: "    " + modelData.name
                          color: root.foreground
                          opacity: 0.75
                          font.family: root.fontFamily
                          font.pixelSize: Style.font.caption
                        }
                        Text {
                          text: root.attributionUsage.formatPoints(modelData.observed) + " pp observed · "
                               + root.attributionUsage.formatPoints(modelData.estimated) + " pp estimated · "
                               + root.attributionUsage.formatPoints(modelData.total) + " pp total"
                          color: root.dim
                          font.family: root.fontFamily
                          font.pixelSize: Style.font.caption
                        }
                      }
                    }
                  }
                }
              }

              Text {
                visible: root.attributionUsage.unattributedLine !== ""
                width: parent.width
                text: root.attributionUsage.unattributedLine
                color: root.dim
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
              }

              Text {
                visible: root.attributionUsage.hasAgentRows
                width: parent.width
                wrapMode: Text.WordWrap
                text: root.attributionUsage.coverageFootnote
                color: root.faint
                opacity: 0.8
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
              }
            }
          }

          PanelSeparator { width: parent.width; visible: root.showRecentSegments }

          // Recent Segments (Phase 5, Task 6; Task 7 adds the
          // showRecentSegments manifest setting to hide it): the completed
          // attribution segments already in segments.jsonl — both windows
          // coexisting, newest first, max 5 compact rows. Render-only: every
          // value (window label, persisted range, observed, coverage,
          // unattributed) comes from HistoryUsage, which reads the store
          // through the CLI's strict read-only --list mode. Opening,
          // closing, or scrolling this section issues no other commands,
          // never creates a snapshot, and never touches observations.jsonl
          // or the store's bytes. The [ Weekly ] [ 5-hour ] selector above
          // does NOT filter this list. Empty store is a normal state, not
          // an error. Hidden when showRecentSegments is false (with the
          // separator above).
          Column {
            visible: root.showRecentSegments
            width: parent.width
            spacing: Style.space(4)

            PanelSectionHeader {
              width: parent.width
              text: "Recent Segments"
              foreground: root.foreground
              fontFamily: root.fontFamily
            }

            Text {
              visible: root.historyUsage.empty
              width: parent.width
              text: root.historyUsage.emptyText
              color: root.dim
              opacity: 0.8
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
            }

            Column {
              visible: !root.historyUsage.empty
              width: parent.width
              spacing: Style.space(6)
              Repeater {
                model: root.historyUsage.rows
                delegate: Column {
                  width: parent.width
                  spacing: Style.space(1)
                  Row {
                    spacing: Style.space(6)
                    Text {
                      text: modelData.windowLabel
                      color: root.foreground
                      opacity: 0.9
                      font.family: root.fontFamily
                      font.pixelSize: Style.font.caption
                      font.bold: true
                    }
                    Text {
                      text: modelData.range
                      color: root.foreground
                      font.family: root.fontFamily
                      font.pixelSize: Style.font.caption
                    }
                  }
                  Text {
                    width: parent.width
                    text: "    " + modelData.line
                    color: root.dim
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.caption
                  }
                }
              }
            }
          }

          PanelSeparator { width: parent.width }

          // Status: loading / one usage-unavailable state / ready summary.
          Row {
            width: parent.width
            spacing: Style.space(6)
            Text {
              text: root.panelStatusLine
              color: root.ready ? root.dim : (root.loading ? root.dim : root.urgent)
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
            }
            Text {
              visible: !root.loading
              anchors.verticalCenter: parent.verticalCenter
              text: root.ready
                  ? "· auto-refresh " + Math.max(1, Math.round(root.refreshInterval / 60)) + " min"
                  : "· right-click the bar slot, or press R, to retry"
              color: root.dim
              opacity: 0.7
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
            }
          }
        }
      }
    }
  }
}

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

  // ------------------------------------------------------------- data
  readonly property var codexUsage: CodexUsage {}

  readonly property string state: codexUsage.dataState
  readonly property bool ready: state === "ready"
  readonly property bool loading: state === "loading"
  readonly property string tier: codexUsage.tier
  readonly property string tierWord: tier !== "" ? tier.charAt(0).toUpperCase() + tier.slice(1) : ""

  readonly property var windows: codexUsage.slots
  readonly property var barPercent: codexUsage.barPercent // number | null

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

  function refresh() {
    if (codexUsage && codexUsage.refresh)
      codexUsage.refresh()
  }

  // Bar slot: Codex percent when one is reported, otherwise the fleet name.
  readonly property string barLabel: {
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
    return codexUsage.fetchedAtMs !== 0 ? "Updated " + formatClock(codexUsage.fetchedAtMs) + "  ·  " + parts.join("   ") : parts.join("   ")
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

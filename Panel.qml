import QtQuick
import Quickshell.Io
import qs.Commons
import qs.Ui

// Agent Fleet — Phase 1, Task 2: static panel UI.
//
// One `Panel` root owns both the bar slot and the popup, the shape every
// Omarchy bar widget uses (structural reference:
// /usr/share/omarchy/shell/plugins/agents/Panel.qml, third-party references in
// docs/reference-notes.md).
//
// Everything the panel shows is static for now. Task 3 adds the Codex
// collector and Task 4 binds this UI to its snapshot; the properties under
// "Static snapshot" below are the seam.
//
// No credentials, tokens or prompts are read or stored anywhere here.
Panel {
  id: root
  moduleName: "io.github.daniluvatar.agent-fleet"
  ipcTarget: "io.github.daniluvatar.agent-fleet"

  // The base Panel's built-in handler stays off so this file owns the target,
  // as the first-party agents widget does.
  manageIpc: false

  // Theme comes from the bar whenever the widget is hosted by one, so the
  // panel follows the user's palette and font instead of a hard-coded look.
  readonly property color foreground: bar ? bar.foreground : Color.foreground
  readonly property color dim: Qt.darker(foreground, 1.55)
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family

  // ---------- Static snapshot (Task 4 replaces this block) ----------
  readonly property string providerName: "Codex"
  readonly property string providerStatus: "Status: Not loaded"
  // Unknown window values render as "—", the same as the first-party widget.
  readonly property var limitWindows: [
    { title: "5 hour", percent: -1, reset: "" },
    { title: "Weekly", percent: -1, reset: "" }
  ]

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  onOpenedChanged: if (opened) Qt.callLater(function() { keyCatcher.forceActiveFocus() })

  IpcHandler {
    target: root.ipcTarget
    function open(): void { root.open() }
    function close(): void { root.close() }
    function show(): void { root.open() }
    function hide(): void { root.close() }
    function toggle(): void { root.toggle() }
  }

  // ---------- Bar slot ----------
  WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: "󰢙 Fleet"
    labelVisible: true
    tooltipText: "Agent Fleet — Codex subscription limits"
    onPressed: function(buttonCode) { root.toggle() }
  }

  // ---------- Popup ----------
  KeyboardPanel {
    id: panel
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(340))
    contentHeight: panel.fittedContentHeight(column.implicitHeight, Style.space(420))

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      onCloseRequested: root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }

      Column {
        id: column
        width: parent.width
        spacing: Style.space(12)

        PanelHero {
          width: parent.width
          title: "Agent Fleet"
          meta: "Phase 1 · subscription limits"
          foreground: root.foreground
          fontFamily: root.fontFamily

          iconComponent: Component {
            Text {
              textFormat: Text.PlainText
              text: "󰢙"
              color: root.foreground
              font.family: root.fontFamily
              font.pixelSize: Style.font.display
            }
          }
        }

        PanelSeparator {
          foreground: root.foreground
        }

        PanelSectionHeader {
          text: "PROVIDERS"
          foreground: root.foreground
          fontFamily: root.fontFamily
        }

        // Provider row: name on the left, status on the right.
        Item {
          width: parent.width
          implicitHeight: Math.max(providerNameText.implicitHeight, providerStatusText.implicitHeight)

          Text {
            id: providerNameText
            textFormat: Text.PlainText
            text: root.providerName
            color: root.foreground
            font.family: root.fontFamily
            font.pixelSize: Style.font.body
            anchors.left: parent.left
            anchors.right: providerStatusText.left
            anchors.rightMargin: Style.spacing.sm
            anchors.verticalCenter: parent.verticalCenter
            elide: Text.ElideRight
          }

          Text {
            id: providerStatusText
            textFormat: Text.PlainText
            text: root.providerStatus
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
          }
        }

        PanelSeparator {
          foreground: root.foreground
        }

        PanelSectionHeader {
          text: "SUBSCRIPTION LIMITS"
          foreground: root.foreground
          fontFamily: root.fontFamily
        }

        Repeater {
          model: root.limitWindows

          LimitRow {
            required property var modelData
            width: parent.width
            window: modelData
          }
        }

        Text {
          textFormat: Text.PlainText
          width: parent.width
          text: "Limits appear once Codex usage is available."
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          wrapMode: Text.WordWrap
        }
      }
    }
  }

  // One usage window: title, percent used, reset line. Task 4 feeds it real
  // numbers; until then `percent` is -1 and the value reads "—".
  component LimitRow: Item {
    id: limitRow
    property var window: null

    readonly property bool known: limitRow.window && Number(limitRow.window.percent) >= 0

    implicitHeight: Math.max(titleText.implicitHeight, valueText.implicitHeight)

    Text {
      id: titleText
      textFormat: Text.PlainText
      text: limitRow.window ? String(limitRow.window.title) : ""
      color: root.foreground
      font.family: root.fontFamily
      font.pixelSize: Style.font.body
      anchors.left: parent.left
      anchors.right: valueText.left
      anchors.rightMargin: Style.spacing.sm
      anchors.verticalCenter: parent.verticalCenter
      elide: Text.ElideRight
    }

    Text {
      id: valueText
      textFormat: Text.PlainText
      text: limitRow.known ? Math.round(Number(limitRow.window.percent)) + "%" : "—"
      color: root.foreground
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
    }
  }
}

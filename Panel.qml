import QtQuick
import QtQuick.Controls
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

// Task 1 scaffold — see docs/phase-1-playbook.md.
//
// This file exists so `omarchy plugin validate .` passes from the first commit:
// the `bar-widget` kind requires an `entryPoints.barWidget` file to load, and
// the validator refuses a manifest that promises a widget it cannot find.
// Task 2 replaces the body with the static Agent Fleet panel.
//
// The structure mirrors the structural reference for this plugin,
// /usr/share/omarchy/shell/plugins/agents/Panel.qml: one `Panel` root owns both
// the bar slot and the popup, so a bar widget has exactly one QML file and no
// separate panel entry point (docs/reference-notes.md).
Panel {
  id: root
  moduleName: "io.github.daniluvatar.agent-fleet"
  ipcTarget: "io.github.daniluvatar.agent-fleet"
  manageIpc: false

  readonly property color foreground: bar ? bar.foreground : Color.foreground
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family

  implicitWidth: label.implicitWidth
  implicitHeight: label.implicitHeight

  // Task 2: BarIconButton, following the first-party widget's bar slot.
  Text {
    id: label
    anchors.centerIn: parent
    text: "Fleet"
    color: root.foreground
    font.family: root.font.family
    font.pixelSize: Style.font.normal
  }

  KeyboardPanel {
    id: panel
    anchorItem: label
    owner: root
    bar: root.bar
    open: root.opened
    contentWidth: panel.fittedContentWidth(Style.space(380))
    contentHeight: panel.fittedContentHeight(placeholder.implicitHeight, Style.space(160))

    Text {
      id: placeholder
      width: panel.width
      topPadding: Style.space(24)
      horizontalAlignment: Text.AlignHCenter
      text: "AGENT FLEET\n\nPhase 1 scaffold — panel arrives in Task 2"
      color: root.foreground
      font.family: root.fontFamily
      font.pixelSize: Style.font.normal
    }
  }
}

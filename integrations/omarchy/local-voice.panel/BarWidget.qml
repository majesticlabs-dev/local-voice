import QtQuick
import Quickshell.Io
import qs.Commons
import qs.Ui
import "Status.js" as Status

BarWidget {
  id: root
  moduleName: "local-voice.panel"

  property var playback: ({ state: "offline", error: "" })
  property string backend: "down"
  property bool opened: false
  property bool popoutSwitchClosing: false
  readonly property string statusLabel: Status.label(playback, backend)

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  function open() { opened = true }
  function close() { opened = false }
  function toggle() { opened ? close() : open() }
  function closeForPopoutSwitch() {
    popoutSwitchClosing = true
    close()
    Qt.callLater(function() { popoutSwitchClosing = false })
  }

  function refresh() {
    if (!statusProcess.running) statusProcess.running = true
    if (!healthProcess.running) healthProcess.running = true
  }

  function read() { if (!readProcess.running) readProcess.running = true }
  function select() { if (!selectionProcess.running) selectionProcess.running = true }
  function stop() { if (!stopProcess.running) stopProcess.running = true }
  function launch() { if (!appProcess.running) appProcess.running = true }
  function choose(action) {
    close()
    if (action === "stop") stop()
    else if (action === "read") read()
    else if (action === "selection") select()
    else if (action === "app") launch()
    else if (action === "quit" && !quitProcess.running) quitProcess.running = true
    else if (action === "start" && !startProcess.running) startProcess.running = true
  }

  Process {
    id: statusProcess
    command: ["local-voice-controller", "status"]
    stdout: StdioCollector { id: statusOutput; waitForEnd: true }
    onExited: function(code) { root.playback = Status.controller(statusOutput.text, code) }
  }

  Process {
    id: healthProcess
    command: ["curl", "--silent", "--show-error", "--max-time", "2", "--fail", "http://127.0.0.1:5517/health"]
    stdout: StdioCollector { id: healthOutput; waitForEnd: true }
    onExited: function(code) { root.backend = Status.service(healthOutput.text, code) }
  }

  Process {
    id: readProcess
    command: ["local-voice-controller", "read-clipboard"]
    onExited: root.refresh()
  }

  Process {
    id: selectionProcess
    command: ["local-voice-controller", "toggle-selection"]
    onExited: root.refresh()
  }

  Process {
    id: stopProcess
    command: ["local-voice-controller", "stop"]
    onExited: root.refresh()
  }

  Process {
    id: appProcess
    command: ["local-voice"]
  }

  Process {
    id: quitProcess
    command: ["local-voice-controller", "quit"]
    onExited: root.refresh()
  }

  Process {
    id: startProcess
    command: ["local-voice-controller", "start"]
    onExited: root.refresh()
  }

  Timer {
    interval: 3000
    running: true
    repeat: true
    triggeredOnStart: true
    onTriggered: root.refresh()
  }

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: Status.icon(root.playback, root.backend)
    active: Status.active(root.playback, root.backend)
    dimmed: root.backend === "down" || root.statusLabel === "Setup needed"
    tooltipText: "Local Voice: " + root.statusLabel
    onPressed: function(b) {
      if (b === Qt.RightButton) root.toggle()
      else if (b === Qt.LeftButton) root.choose(Status.primaryAction(root.playback, root.backend))
    }
  }

  KeyboardPanel {
    id: menu
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    contentWidth: menu.fittedContentWidth(Style.space(240))
    contentHeight: menu.fittedContentHeight(menuItems.implicitHeight)
    focusTarget: keyCatcher

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      onCloseRequested: root.close()

      Column {
        id: menuItems
        width: parent.width
        spacing: Style.space(2)

        Button {
          width: parent.width
          text: "Read clipboard"
          leftAlign: true
          focusable: true
          onClicked: root.choose("read")
        }
        Button {
          width: parent.width
          text: "Read selection"
          leftAlign: true
          focusable: true
          onClicked: root.choose("selection")
        }
        Button {
          width: parent.width
          text: "Stop"
          leftAlign: true
          focusable: true
          onClicked: root.choose("stop")
        }
        Button {
          width: parent.width
          text: Status.appLabel(root.playback, root.backend)
          leftAlign: true
          focusable: true
          onClicked: root.choose("app")
        }
        Button {
          width: parent.width
          text: Status.powerLabel(root.playback, root.backend)
          leftAlign: true
          focusable: true
          onClicked: root.choose(Status.powerAction(root.playback, root.backend))
        }
      }
    }
  }
}

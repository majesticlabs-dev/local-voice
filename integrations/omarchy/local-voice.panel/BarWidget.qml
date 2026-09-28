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
  readonly property string statusLabel: Status.label(playback, backend)

  implicitWidth: controls.implicitWidth
  implicitHeight: barSize

  function refresh() {
    if (!statusProcess.running) statusProcess.running = true
    if (!healthProcess.running) healthProcess.running = true
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

  Timer {
    interval: 3000
    running: true
    repeat: true
    triggeredOnStart: true
    onTriggered: root.refresh()
  }

  Row {
    id: controls
    anchors.centerIn: parent
    spacing: Style.space(2)

    WidgetButton {
      bar: root.bar
      text: root.statusLabel
      interactive: false
      dimmed: root.backend !== "ready"
    }

    WidgetButton {
      bar: root.bar
      text: "Read clipboard"
      tooltipText: "Speak clipboard text (explicit action)"
      onPressed: if (!readProcess.running) readProcess.running = true
    }

    WidgetButton {
      bar: root.bar
      text: "Read selection"
      tooltipText: "Speak primary selection, or stop current playback"
      onPressed: if (!selectionProcess.running) selectionProcess.running = true
    }

    WidgetButton {
      bar: root.bar
      text: "Stop"
      tooltipText: "Stop panel and shortcut playback only"
      onPressed: if (!stopProcess.running) stopProcess.running = true
    }

    WidgetButton {
      bar: root.bar
      text: root.statusLabel === "Setup needed" ? "Set up" : "App"
      tooltipText: root.statusLabel === "Setup needed" ? "Open Local Voice, then select Models" : "Open Local Voice"
      onPressed: if (!appProcess.running) appProcess.running = true
    }
  }
}

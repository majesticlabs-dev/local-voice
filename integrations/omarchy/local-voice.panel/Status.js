// Data from the controller and health endpoint only. Never read clipboard content here.
function commands() {
  return {
    status: ["local-voice-controller", "status"],
    read: ["local-voice-controller", "read-clipboard"],
    selection: ["local-voice-controller", "toggle-selection"],
    stop: ["local-voice-controller", "stop"],
    quit: ["local-voice-controller", "quit"],
    start: ["local-voice-controller", "start"],
    app: ["local-voice-desktop"]
  }
}
function controller(output, exitCode) {
  try {
    var value = JSON.parse(output)
    if (value && typeof value.state === "string" &&
        ["idle", "reading", "synthesizing", "playing", "setup_needed", "error", "offline", "off"].indexOf(value.state) !== -1)
      return { state: value.state, error: typeof value.error === "string" ? value.error : "" }
  } catch (e) {}
  return { state: "offline", error: "Controller unavailable" }
}

function service(output, exitCode) {
  if (exitCode !== 0) return "down"
  try {
    var value = JSON.parse(output)
    if (value.status === "setup_needed") return "setup_needed"
    if (value.status === "ok") return "ready"
    if (value.status === "degraded") return "degraded"
  } catch (e) {}
  return "down"
}

function primaryAction(controllerState, serviceState) {
  if (controllerState.state === "off" && serviceState === "down") return "start"
  return ["reading", "synthesizing", "playing"].indexOf(controllerState.state) !== -1 ? "stop" : "read"
}

function powerAction(controllerState, serviceState) {
  return controllerState.state === "off" && serviceState === "down" ? "start" : "quit"
}

function powerLabel(controllerState, serviceState) {
  return powerAction(controllerState, serviceState) === "start" ? "Start Local Voice" : "Quit Local Voice"
}

function appLabel(controllerState, serviceState) {
  return controllerState.state === "setup_needed" || serviceState === "setup_needed"
    ? "Open Local Voice (set up models)" : "Open Local Voice"
}

function active(controllerState, serviceState) {
  return serviceState !== "down" && primaryAction(controllerState, serviceState) === "stop"
}

function icon(controllerState, serviceState) {
  var state = label(controllerState, serviceState)
  if (state === "Off") return "󰐥"
  if (state === "Service down") return "󰅛"
  if (controllerState.state === "error" || state === "Service error") return "󰀦"
  if (state === "Setup needed") return "󰋼"
  if (state === "Playing") return "󰓃"
  if (state === "Reading" || state === "Synthesizing") return "󰓄"
  return "󰓃"
}

function label(controllerState, serviceState) {
  if (controllerState.state === "off" && serviceState === "down") return "Off"
  if (serviceState === "down") return "Service down"
  if (controllerState.state === "playing") return "Playing"
  if (controllerState.state === "synthesizing") return "Synthesizing"
  if (controllerState.state === "reading") return "Reading"
  if (controllerState.state === "setup_needed" || serviceState === "setup_needed") return "Setup needed"
  if (controllerState.state === "error") {
    if (["Clipboard has no text", "Selection has no text"].indexOf(controllerState.error) !== -1)
      return controllerState.error
    return "Playback error"
  }
  if (serviceState === "degraded") return "Service error"
  return "Ready"
}

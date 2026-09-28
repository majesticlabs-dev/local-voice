// Data from the controller and health endpoint only. Never read clipboard content here.
function controller(output, exitCode) {
  try {
    var value = JSON.parse(output)
    if (value && typeof value.state === "string" &&
        ["idle", "reading", "synthesizing", "playing", "setup_needed", "error", "offline"].indexOf(value.state) !== -1)
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

function label(controllerState, serviceState) {
  if (serviceState === "down") return "Service down"
  if (controllerState.state === "playing") return "Playing"
  if (controllerState.state === "synthesizing") return "Synthesizing"
  if (controllerState.state === "reading") return "Reading"
  if (controllerState.state === "setup_needed" || serviceState === "setup_needed") return "Setup needed"
  if (controllerState.state === "error") return "Playback error"
  if (serviceState === "degraded") return "Service error"
  return "Ready"
}

# Local Voice Omarchy bar widget

For Omarchy 4.0.4-1 on x86_64. This source plugin does not install a service, controller, desktop app, or model. It never reads the clipboard except when you press **Read clipboard**. It polls only the controller `status` command and loopback `/health` every three seconds. It holds no model-management token and sends no management request. Stop affects only controller playback, not Chrome or desktop playback.

After the T12 package supplies `local-voice-controller` and the `local-voice` desktop launcher on PATH, install the plugin manually (replace `$SOURCE` with this repository or the package's plugin source directory):

```sh
mkdir -p ~/.config/omarchy/plugins/local-voice.panel
cp "$SOURCE/integrations/omarchy/local-voice.panel/"{manifest.json,BarWidget.qml,Status.js} ~/.config/omarchy/plugins/local-voice.panel/
omarchy-shell shell rescanPlugins
omarchy plugin enable local-voice.panel
```

The widget starts on the right. **Set up** opens the desktop app; choose **Models** there to select and download assets with consent. If the service is down, open the app to start the shared user service, or inspect `journalctl --user -u local-voice.service`. `Ready` means the service reports ready, not that the controller has been started. The controller starts on the first Read action. An offline controller with a healthy service is normal. `Playback error` indicates a controller error; try Read again or inspect the controller independently with `local-voice-controller status`. The app launch command is a T12 packaging contract and is not yet installed by this source tree.

To remove only this integration, disable it with `omarchy plugin disable local-voice.panel`, then remove `~/.config/omarchy/plugins/local-voice.panel/` if it still contains only these three files. Do not replace `shell.json`: it is a full user override, and Omarchy manages layout when enabling the plugin. No commands in this document were run on the host during T08.

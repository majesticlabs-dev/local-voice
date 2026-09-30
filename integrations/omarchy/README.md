# Local Voice Omarchy bar widget

For Omarchy 4.0.4-1 on x86_64. This source plugin does not install a service, controller, desktop app, or model. It reads the clipboard only when you left-click its icon while idle or select **Read clipboard** from its right-click menu. Left-click while reading, synthesizing, or playing stops controller playback. The menu also has **Read selection**, **Stop**, **Settings**, **Open Local Voice** (with a model-setup hint when needed), and **Quit Local Voice**. Quit stops controller playback, requests a normal close for the matching desktop window through Hyprland, and stops the shared user service without disabling login startup. It leaves the widget installed. The off icon then offers **Start Local Voice** in the menu and on left-click; start runs `systemctl --user start local-voice.service`. Its icon and tooltip show state. It polls only the controller `status` command and loopback `/health` every three seconds. It holds no model-management token and sends no management request. Stop affects only controller playback, not Chrome or desktop playback.

All shortcuts are disabled by default. Choose **Settings**, or run `local-voice-integration settings`, to create and open `~/.config/local-voice/shortcuts.toml`. It uses `$EDITOR` through `xdg-terminal-exec`, or `xdg-open` when `$EDITOR` is unset. Enable only the actions you want and choose unused keys:

```toml
[read]
enabled = false
binding = "SUPER ALT + V"

[selection]
enabled = false
binding = "SUPER ALT + E"

[stop]
enabled = false
binding = "SUPER ALT + X"
```

Change an entry to `enabled = true` to opt in. The panel runs `local-voice-integration sync` every three seconds. This reads settings, not the clipboard. Without the panel, run that command after editing. Missing settings or all-disabled entries mean no managed shortcuts. Malformed TOML disables all of them. Invalid entries, duplicate shortcuts, and conflicts with effective `hyprctl binds -j` entries are logged and skipped, not overridden. The script writes only its owned block in `~/.config/hypr/bindings.lua` (or legacy `bindings.conf`), records it in `~/.config/local-voice/omarchy-integration.json`, then runs `hyprctl reload` and `hyprctl configerrors`. A missing target or edited owned block stops changes safely. Unrelated edits, `shell.json`, service settings, models, and packaged Omarchy files are preserved.

For an upgrade, copy the new plugin files into the user plugin directory and restart the shell, or run `local-voice-integration sync` once. With no settings file, sync removes old owned fixed shortcuts. Package installation alone cannot remove existing user bindings or replace a copied plugin. The old `setup` command remains compatible, but sync uses the TOML file as the source of truth. To undo shortcuts, delete the settings file or disable all entries, then wait for the panel or run sync. Before uninstalling, do this while the command still exists. Verify `hyprctl configerrors` and `hyprctl binds -j | grep local-voice` in the target session. Live key and editor behavior still requires target-session verification.

Selection toggles controller speech of the Wayland primary selection. Panel buttons need no shortcut. To check an installed voice without audio playback, run `local-voice-controller verify af_bella` (or another installed voice ID). It synthesizes in a child process and discards audio, without downloading assets. Clipboard and selection cleanup remains limited to the controller; desktop and Chrome behavior is unchanged.

After the T12 package supplies `local-voice-controller` and the `local-voice-desktop` launcher on PATH, install the plugin manually (replace `$SOURCE` with this repository or the package's plugin source directory):

```sh
mkdir -p ~/.config/omarchy/plugins/local-voice.panel
cp "$SOURCE/integrations/omarchy/local-voice.panel/"{manifest.json,BarWidget.qml,Status.js} ~/.config/omarchy/plugins/local-voice.panel/
omarchy-shell shell rescanPlugins
omarchy plugin enable local-voice.panel
```

The widget starts on the right. **Set up** opens the desktop app; choose **Models** there to select and download assets with consent. If the service is down, open the app to start the shared user service, or inspect `journalctl --user -u local-voice.service`. `Ready` means the service reports ready, not that the controller has been started. The controller starts on the first Read action. An offline controller with a healthy service is normal. `Playback error` indicates a controller error; an image-only clipboard or selection shows `Clipboard has no text` or `Selection has no text` in the icon tooltip. Inspect the controller with `local-voice-controller status`. A client replaces a version-mismatched controller after an upgrade only when the socket peer is verified as its own per-user controller process. The app launch command is a T12 packaging contract and is not yet installed by this source tree.

To remove only this integration, disable it with `omarchy plugin disable local-voice.panel`, then remove `~/.config/omarchy/plugins/local-voice.panel/` if it still contains only these three files. Do not replace `shell.json`: it is a full user override, and Omarchy manages layout when enabling the plugin. No commands in this document were run on the host during T08.

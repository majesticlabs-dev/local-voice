# Install Local Voice on Omarchy

This guide covers the local Arch package for Local Voice 1.2.0 on Omarchy x86_64. The package is built from this repository. It is not an AUR or published binary install. The macOS install instructions remain in the [README](../README.md).

## Requirements and build

Use Omarchy with Hyprland. The shortcut instructions below cover its Lua config provider (`~/.config/hypr/hyprland.lua` and `bindings.lua`). The package targets Arch x86_64. Its dependencies include `ffmpeg` (which supplies both `ffmpeg` and `ffplay`), `wl-clipboard` (which supplies `wl-paste`), WebKitGTK, GTK, GStreamer plugins, and systemd. The panel uses `curl` for its health check, so make sure `curl` is installed. Build from a source checkout with `uv`, Node.js, Cargo/Rust, and `makepkg` available. The build can fetch toolchains and dependencies, but does not download optional speech models.

```sh
cd /path/to/local-voice
scripts/check-and-package
```

The script runs Python, Node, and Rust checks, validates the widget when `omarchy` is available, builds the desktop and runtime, then runs `makepkg --nodeps --force`. It prints the package path under `packaging/arch/`. Inspect that package before installing:

```sh
bsdtar -tf packaging/arch/local-voice-1.2.0-1-x86_64.pkg.tar.zst
sudo pacman -U packaging/arch/local-voice-1.2.0-1-x86_64.pkg.tar.zst
```

Use the actual printed filename if it differs. `sudo` is required for `pacman` to write system package files under `/usr`. Do not run the build as root. Package installation does not enable the service, install a model, change Hyprland bindings, or enable a panel plugin.

## Start and set up a voice

To start the shared service now and at later logins:

```sh
systemctl --user enable --now local-voice.service
curl http://127.0.0.1:5517/health
```

This is a user service, not a system service. Enabling login startup is optional: opening the Linux desktop app can start the service for the current session. The service stops at logout unless your user manager is configured otherwise. A live service with no models can report `setup_needed`; this is not a failed start. The API listens on loopback only.

Run `local-voice-desktop` (or open Local Voice Desktop from the application menu). Open **Models**, choose English, Spanish, Russian, or more than one language, review the required assets, and confirm the download. Nothing is downloaded merely by installing, starting the service, checking health, or selecting a voice. English and Spanish share Kokoro engine files. English also needs its own spaCy language asset. Russian uses the Piper Dmitri voice. After installation the chosen assets work without a network connection. To test an installed voice without playing sound:

```sh
local-voice-controller verify af_bella
```

Replace `af_bella` with an installed voice ID, such as `ef_dora` or `ru_RU-dmitri-medium`. This check synthesizes a short sample and discards its audio; it does not download assets. Models are stored in `${XDG_DATA_HOME:-$HOME/.local/share}/dev.majesticlabs.localvoice/service-models/`. Output and the management token are in the same application data directory. Do not delete that directory during an upgrade if you want to keep your models.

## Add the Omarchy bar widget

The package places the plugin in `/usr/share/local-voice/local-voice.panel/`. Copy it into your own plugin directory, then register and enable it:

```sh
mkdir -p ~/.config/omarchy/plugins
cp -a /usr/share/local-voice/local-voice.panel ~/.config/omarchy/plugins/
omarchy-shell shell rescanPlugins
omarchy plugin enable local-voice.panel
```

This adds one status icon. Left-click to read the clipboard when idle, stop the controller while it reads or plays, or start Local Voice after Quit. Right-click for **Read clipboard**, **Read selection**, **Stop**, **Open Local Voice**, **Shortcut settings**, and **Quit Local Voice** (or **Start Local Voice** when off). Quit stops the controller, closes the matching desktop window, and stops the user service. It does not disable login startup. Stop affects panel and shortcut playback, not Chrome or desktop playback. Clipboard or selection text is read only after an explicit action. The panel polls service and controller status, not clipboard contents.

After an upgrade, copy the new plugin files to the same user directory and restart the shell, since the running shell can keep old QML in memory:

```sh
cp -a /usr/share/local-voice/local-voice.panel ~/.config/omarchy/plugins/
omarchy-restart-shell
```

## Enable shortcuts (optional)

All Omarchy shortcuts are disabled by default. **SUPER ALT + V/E/X** are examples, not active bindings. Select **Shortcut settings** in the panel menu, or run `local-voice-integration settings`. This creates `~/.config/local-voice/shortcuts.toml` with all entries disabled, then opens it with `$EDITOR` through `xdg-terminal-exec`, or `xdg-open` when no editor is set.

Enable each action separately and choose an unused binding. For example, enable clipboard speech only:

```toml
[read]
enabled = true
binding = "SUPER ALT + V"

[selection]
enabled = false
binding = "SUPER ALT + E"

[stop]
enabled = false
binding = "SUPER ALT + X"
```

Modifiers are `SUPER`, `ALT`, `CTRL`, and `SHIFT`. Use spaces between modifiers and one `+` before an XKB key name (such as `V`, `F8`, or `XF86AudioPlay`). Unknown keys are skipped. Key validation uses the desktop's `libxkbcommon` library. Selection toggles speech of the Wayland primary selection; stop affects only controller playback. Panel buttons remain available without shortcuts.

The updated panel checks settings every three seconds and applies saved changes. Without the panel, run `local-voice-integration sync` after each edit. It checks effective Hyprland bindings, skips collisions, updates only its managed block in `~/.config/hypr/bindings.lua` (or legacy `bindings.conf`), and reloads Hyprland. Ownership is recorded in `~/.config/local-voice/omarchy-integration.json`. Invalid entries are skipped with a warning; duplicate bindings disable both conflicting entries. A malformed TOML file disables all managed shortcuts. Warnings appear in shell logs or command stderr. No clipboard text is read by this settings check.

Delete the TOML file or set every `enabled` value to `false` to remove managed shortcuts on the next panel check or `sync`. Unrelated configuration is preserved. Do not edit the managed bindings block: if it was changed, automatic changes are refused. The older `setup --read/--stop/--selection` command remains for compatibility, but its bindings are removed by `sync` unless enabled in the settings file. No packaged Omarchy files or `shell.json` are changed.

After upgrading from fixed shortcuts, update the user plugin as described above, or run `local-voice-integration sync` once. With no settings file, this removes the old owned V/E/X bindings. Package installation cannot update a copied user plugin or remove existing user bindings by itself. Check the result in the target session:

```sh
local-voice-integration sync
hyprctl configerrors
hyprctl binds -j | grep local-voice
```

## Chrome extension

The Arch package does not include or install the extension. Load it unpacked from the source checkout's `extension/` directory: open `chrome://extensions/` in Chrome, turn on **Developer mode**, select **Load unpacked**, and choose that directory. The extension connects to `http://127.0.0.1:5517` and plays audio in Chrome. Keep the user service running to use it when the desktop app is closed. Set up a voice in the desktop app first.

## Upgrade, removal, and problems

For an upgrade, build the new package, then install it with `sudo pacman -U <new-package-path>`. Restart the user service to use the new packaged runtime:

```sh
systemctl --user restart local-voice.service
```

The controller checks the protocol version and replaces a controller from a previous package automatically. If replacement fails, see the fallback below. Use the widget upgrade steps above for new QML.

Before uninstalling, disable all entries in `~/.config/local-voice/shortcuts.toml` (or delete the file), then remove managed shortcuts while their command still exists. Stop and disable the user service, disable the plugin, and remove the package:

```sh
rm -f ~/.config/local-voice/shortcuts.toml
local-voice-integration sync
systemctl --user disable --now local-voice.service
omarchy plugin disable local-voice.panel
sudo pacman -R local-voice
```

Remove `~/.config/omarchy/plugins/local-voice.panel/` yourself if it contains only the copied plugin files. Package removal does not remove your downloaded models or user data. It does not remove the Chrome extension from your browser.

| Problem | Check |
| --- | --- |
| Image-only clipboard shows **Clipboard has no text** | Copy text and try again. The controller requests `text/plain`, not images. |
| Old controller remains after upgrade | Replacement is automatic via a protocol version check. If it fails, stop playback, run `pkill -f 'clipboard_controller serve'` as a fallback, then try again. |
| Service down or port 5517 in use | Run `systemctl --user status local-voice.service` and inspect `journalctl --user -u local-voice.service`. Check for another process using the port; the service does not take it over. |
| **Setup needed** | Open `local-voice-desktop`, choose **Models**, and confirm a language download. Health alone never downloads a model. |

## Maintainers

Run `scripts/check-and-package` locally on Linux x86_64. It executes Python unittest discovery (`tests/`), Node tests for desktop, extension, and Omarchy integration, Rust library tests, a runtime build, and the Arch package build. The script does not prove native GUI playback or real-model inference. Check those separately with an approved installed artifact and models. `omarchy plugin validate` is skipped if Omarchy is unavailable. The resulting package is under `packaging/arch/`; use `bsdtar -tf` to audit its paths. The PKGBUILD is `packaging/arch/PKGBUILD` and the installed launcher, service, controller, plugin, and notice files come from that recipe. The package includes no optional model weights. Review `packaging/arch/THIRD-PARTY-NOTICES` and bundled dependency licenses before redistribution.

For a 1.2.0 release, keep `packaging/arch/PKGBUILD` (`pkgver`, `pkgrel`), `pyproject.toml`, `src-tauri/Cargo.toml`, `src-tauri/tauri.conf.json`, and `extension/manifest.json` in sync. The panel has its own plugin version in `integrations/omarchy/local-voice.panel/manifest.json`. No push, tag, or publication follows from building the package.

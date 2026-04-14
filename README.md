# Local Voice

**Local text-to-speech for macOS.** Read web pages and documents aloud using a high-quality TTS engine that runs entirely on your machine. Your text never leaves your computer.

## What You Get

- **Chrome Extension** — select text on any web page and hear it read aloud
- **Desktop App** — paste text or drop a file, listen, and export MP3s

Both use the same local TTS engine powered by [Kokoro](https://github.com/hexgrad/kokoro) with six natural-sounding voices.

## Install

### Mac Desktop App

1. Download the latest `.dmg` from [GitHub Releases](https://github.com/majesticlabs/local-voice/releases)
2. Open the `.dmg` and drag **Local Voice Desktop** to Applications
3. On first launch, macOS may warn about an unidentified developer because the app is not notarized yet. Right-click the app, choose **Open**, then click **Open** in the dialog.

If Finder still refuses to launch the app after you approve it, clear the quarantine flag and try again:

```bash
xattr -dr com.apple.quarantine "/Applications/Local Voice Desktop.app"
```

The desktop app bundles the TTS service and starts it automatically. You still need these on your system:

- [uv](https://docs.astral.sh/uv/) — `brew install uv`
- [ffmpeg](https://formulae.brew.sh/formula/ffmpeg) — `brew install ffmpeg`

On launch, the desktop app checks the local engine runtime and `ffmpeg` availability up front. Homebrew installs in `/opt/homebrew/bin` and `/usr/local/bin` are detected automatically and written into the app settings. If your `ffmpeg` binary lives somewhere unusual, you can override it in the desktop app with the optional `ffmpeg path` setting.

### Chrome Extension

Install from the [Chrome Web Store](https://chromewebstore.google.com/) (search "Local Voice Reader"), or load manually:

1. Open `chrome://extensions/`
2. Enable **Developer mode** (top right)
3. Click **Load unpacked** and select the `extension/` directory

The extension requires the TTS service running locally — either through the desktop app or started manually (see [Development](#development) below).

## Usage

### Desktop App

1. Launch **Local Voice Desktop**
2. Wait for the health indicator to turn green
3. Paste text or drop a `.md` / `.txt` file
4. Choose a voice and speed, then click **Speak**
5. Use **Download MP3** to export

Enable **Server mode** to expose the API to other devices on your local network (with a clear warning).

### Chrome Extension

| Action | How |
|--------|-----|
| Read selected text | Select text, right-click, choose **Read aloud with Local Voice** |
| Keyboard shortcut | Select text, press `Ctrl+Shift+S` (Mac: `^+Shift+S`) |
| Stop playback | `Ctrl+Shift+X` or click Stop in the popup |
| Change voice/speed | Click the extension icon |

**Reading modes:**

| Mode | Behavior |
|------|----------|
| **Selection** | Reads highlighted text. Falls back to nearest paragraph, then article. |
| **Block** | Reads the paragraph or container around your cursor. |
| **Article** | Extracts and reads the main content of the page. |

## Voices

| Voice | Language | Gender |
|-------|----------|--------|
| Bella | English | Female |
| Sarah | English | Female |
| Adam | English | Male |
| Michael | English | Male |
| Emma | English (British) | Female |
| George | English (British) | Male |

## Configuration

Settings persist automatically — voice and speed in the desktop app (local storage) and extension (Chrome storage).

Override service defaults in `config.yml` or with environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `LV_HOST` | `127.0.0.1` | Bind address |
| `LV_PORT` | `5517` | Port |
| `LV_ENGINE` | `kokoro` | TTS engine |
| `LV_VOICE` | `af_bella` | Default voice |
| `LV_MAX_INPUT` | `50000` | Max text length per request |
| `LV_FFMPEG_PATH` | unset | Advanced override for standalone service runs when `ffmpeg` is installed outside standard PATH / Homebrew locations |

## Architecture

```
Chrome Extension / Desktop App        Python Service (localhost:5517)
┌────────────────────────────────┐    ┌──────────────────────────┐
│ Extension                      │    │  FastAPI                 │
│  - content script              │    │  ┌────────────────────┐  │
│  - background worker           │───▶│  │ /synthesize        │  │
│  - offscreen audio player      │    │  │ /stream            │  │
├────────────────────────────────┤    │  │ /export            │  │
│ Desktop app (Tauri)            │───▶│  │ /preprocess        │  │
│  - file upload / paste         │    │  │ /voices            │  │
│  - playback / download         │    │  │ /health            │  │
│  - server mode toggle          │    │  └────────┬───────────┘  │
└────────────────────────────────┘    │           │              │
                                      │  ┌────────▼───────────┐  │
                                      │  │ Kokoro TTS Engine  │  │
                                      │  └────────────────────┘  │
                                      └──────────────────────────┘
```

Short text (under 800 chars) goes through a single `/synthesize` call. Longer text is split into sentence-safe chunks via `/stream` and played as a queue.

## Development

### Prerequisites

- macOS (Apple Silicon recommended)
- Python 3.11+
- [uv](https://docs.astral.sh/uv/)
- [ffmpeg](https://formulae.brew.sh/formula/ffmpeg)
- Chrome or Chromium-based browser
- Rust toolchain + Node.js (for desktop app builds)

### Setup

```bash
git clone https://github.com/majesticlabs/local-voice.git
cd local-voice
uv sync
```

### Run the service standalone

```bash
./run.sh
# Verify: curl http://127.0.0.1:5517/health
```

### Run the desktop app in dev mode

```bash
npx @tauri-apps/cli dev
```

This launches the Tauri window and starts the Python service as a sidecar. Don't run `./run.sh` separately.

### Build the desktop app

```bash
./build.sh
# Or build the signed app plus a DMG:
./build.sh --bundles dmg
```

`build.sh` prepares the bundled Python runtime, builds the Tauri app, clears extended attributes, seals the `.app`, and optionally creates a DMG from the signed app.

Output: `src-tauri/target/release/bundle/macos/Local Voice Desktop.app`

### Adding a TTS engine

1. Create `service/providers/your_engine.py` implementing the `TTSProvider` ABC
2. Add a branch in `service/app.py:get_provider()`
3. Set `LV_ENGINE=your_engine`

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Red dot in extension popup | TTS service isn't running — launch the desktop app or run `./run.sh` |
| No audio output | Launch the desktop app and check the startup warning. Homebrew installs under `/opt/homebrew/bin` and `/usr/local/bin` are detected automatically; for custom installs, set the optional `ffmpeg path` in app settings. |
| "No readable text found" | Select text first, or switch to Article mode |
| Extension not loading | Ensure you selected the `extension/` directory, not the project root |
| Kokoro import error | Run `uv sync` to reinstall dependencies |
| macOS says the app is from an unidentified developer | Right-click → Open → Open |
| macOS still refuses to launch after approval | `xattr -dr com.apple.quarantine "/Applications/Local Voice Desktop.app"` |
| macOS says the app is damaged | Delete that copy and download the latest release. Current release builds are sealed before packaging, so the expected warning is the unidentified-developer prompt, not a damaged-app error. |

## Legal

- [MIT License](./LICENSE)
- [Privacy Policy](./PRIVACY.md) — we collect nothing
- [Terms of Service](./TERMS.md)

---

[majesticlabs.dev](https://majesticlabs.dev) · Majestic Labs LLC · Austin, TX

# Local Voice - TTS tool

## What This Is

Two-process local TTS system: a Chrome MV3 extension captures text and plays audio, a Python FastAPI service on `127.0.0.1:5517` runs the TTS engine. No cloud dependencies.

## Running the Service

```bash
uv sync
./run.sh
# or directly:
uv run uvicorn service.app:app --host 127.0.0.1 --port 5517 --reload
```

Requires `ffmpeg` on PATH for MP3 output. The service binds to loopback only.

## Loading the Extension

Chrome → `chrome://extensions` → Developer Mode → Load Unpacked → select `extension/` directory.

## Architecture

**Extension → HTTP → Service → Provider → Engine**

The extension's background service worker (`background.js`) is the orchestrator. It receives text from the content script, decides short vs long path based on `CHUNK_THRESHOLD` (800 chars), calls the localhost API, and routes audio to an offscreen document for playback.

Short text: single `POST /synthesize` → audio blob → play.
Long text: `POST /stream` → server chunks text, synthesizes each, returns chunk URLs → extension fetches and queues playback.

All intra-extension communication uses `chrome.runtime.sendMessage` with a `type` field. Message types and job statuses are defined in `constants.js` — both the popup and player consume `STATE_CHANGED` events broadcast by the background worker.

**Provider abstraction**: `providers/base.py` defines `TTSProvider` ABC. `providers/kokoro.py` implements it. The provider is selected by `config.engine` and instantiated lazily in `app.py:get_provider()`. Adding a new engine means implementing the ABC and adding a branch in `get_provider()`.

**Audio pipeline**: Kokoro outputs float32 PCM → `core/audio.py` wraps as WAV → ffmpeg converts to MP3.

**Caching**: `core/cache.py` uses SHA256 of `text|voice|rate|format` as key, stores files in `artifacts/cache/` with TTL (default 3600s). Both `/synthesize` and `/stream` check cache before calling the provider.

## Service Configuration

Environment variables: `LV_HOST`, `LV_PORT`, `LV_ENGINE`, `LV_VOICE`, `LV_MAX_INPUT`. Defaults in `service/core/config.py`.

## Extension Settings

Persisted in `chrome.storage.local` via `store.js`. Defaults in `constants.js`. Key settings: `serverUrl`, `voice`, `rate`, `mode` (selection/block/article), `format`.

## API Endpoints

- `GET /health` — engine status
- `GET /voices` — available voices
- `POST /synthesize` — single audio response (binary)
- `POST /stream` — chunked synthesis, returns job_id + chunk URLs
- `GET /audio/{job_id}/{filename}` — fetch individual chunk
- `POST /stop` — cancel streaming job

Request/response models are in `service/core/models.py`.

## Text Extraction

`content.js` supports three modes with fallback chains. Selection mode tries: user selection → nearest block element → article/main element → largest text-dense container.

## Chunking

Mirrored in both `extension/src/chunker.js` (client preview) and `service/core/chunking.py` (server canonical). Splits by paragraph breaks first, then sentence boundaries, respecting `target_chars`/`max_chars` limits.

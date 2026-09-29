# Local Voice: Omarchy implementation plan

## Purpose and authority

Create a shareable, installable Omarchy integration in this repository. The user selected both the existing desktop/Chrome experience and native Omarchy panel controls with clipboard speech shortcuts. Users must choose which models they download.

This document is a planning artifact, not a record of completed implementation. No implementation agents, builds, tests, installs, or model downloads were started during planning. T01 baseline checks are recorded below. Release publication, package-registry submission, pushes, and pull requests require separate user authorization.

Herdr project: `local-voice-omarchy`.
Repository: `/home/dpaluy/Projects/local-voice`.
Research baseline: branch `feat/omarchy`, commit `a407f59b5d6ec9bf5aaae34a1a8a57d9e79d8763`.
The worktree was clean before adding this plan. Future threads must inspect current state and use an explicit base containing this plan. Do not assume Herdr's default worktree base contains `feat/omarchy`.

## Agreed product scope

- R1: One repository for the Linux port and Omarchy integration. Do not fork or duplicate the TTS service.
- R2: Desktop app, Chrome extension, Omarchy panel status/controls, read-clipboard shortcut, and stop shortcut.
- R3: A shared local service that remains usable without the desktop window open. Users must not start a terminal server manually.
- R4: Explicit model management: available models, languages/voices, size, installed status, download, cancellation/retry, and removal.
- R5: Installation, startup, health checks, voice selection, and ordinary synthesis requests must not implicitly download models. Request confirmation for all required model assets before downloading.
- R6: Explain shared assets. Kokoro voices use shared engine assets; Piper voices have individual model/config files. Do not imply one voice always equals one independent model file.
- R7: Models work offline after the chosen assets are installed. Interrupted downloads must never appear installed. Block unsafe removal while assets are in use.
- R8: Keep the API local by default. Read the clipboard only on explicit action, never monitor it continuously. Do not store clipboard text in logs or settings.
- R9: Preserve macOS behavior except where explicit model-download control intentionally replaces automatic downloads. Keep the macOS build path functional.

## Proposed defaults, not separately confirmed requirements

- D1: Initial release targets Omarchy x86_64, not general Linux or ARM.
- D2: Native Arch package with a separate, explicit user-integration setup step. No manual source checkout for end users.
- D3: Use a systemd user service for the shared Linux backend. Choose and document startup behavior in T06, including consent for login startup and resource use while idle. No system-level daemon or lingering after logout by default.
- D4: Browser playback stays in the extension. Desktop playback stays in the desktop app. Panel/shortcut playback has a dedicated local controller. Stop in the panel controls its own session, not all browser/desktop sessions.
- D5: Chrome extension installation remains a browser-controlled step. Do not silently enable developer mode or install an extension into a user's profile.
- D6: Omarchy panel opens the desktop model manager when setup is required. Do not build a second model manager in the panel.
- D7: No new languages, cloud services, GPU requirement, tray implementation, shell theme framework, or cross-client playback synchronization in the initial release.

Ask the user if evidence requires a material change to these defaults. Select routine internal implementation details from repository code and installed APIs.

## Architecture and ownership

```text
Desktop app ----------------------+
Chrome extension -----------------+--> shared local Python TTS service
Omarchy panel / shortcuts ---------+        |
         |                                 +--> model catalog and lifecycle
         +--> local playback controller    +--> offline Kokoro/Piper providers
```

The current service synthesizes audio; it does not play audio through the desktop sound device. A panel button that only calls `/synthesize` is not a complete implementation.

On Linux, the service manager owns the Python process. Closing or reopening the Tauri app must not kill or duplicate that process. Preserve the app-owned process path on macOS where still needed. Reconcile the existing server-mode toggle and runtime settings with shared service ownership before changing them. New download/removal controls must not become available to arbitrary websites or unauthenticated LAN clients.

Keep public API changes compatible with the existing extension where practical. Do not introduce a generic plugin framework. Put optional platform files in a clearly named directory, such as `integrations/omarchy/`, and packaging files in `packaging/arch/` if those names fit the implementation. These are proposed paths, not existing files.

## Verified repository findings

- F1: `README.md` markets a macOS application and gives Homebrew installation instructions. It describes the Python service, Tauri desktop app, and Chrome extension. Some headline voice counts do not match its voice table; use provider catalogs, not prose counts, when building the model UI.
- F2: `build.sh` unconditionally requires `codesign`, `ditto`, and `xattr`, copies `libpython*.dylib`, constructs a `.app`, and can create/sign a DMG. Linux needs its own build path without removing macOS support.
- F3: `src-tauri/src/lib.rs` resolves release resources through Tauri, also checking `_up_`. Releases require `.bundle-venv`; development uses `.venv` or `uv`. `bundled_python_runtime_complete()` requires a `.dylib` even on Linux. Merely teaching the shell script about `.so` is insufficient: relocation, loader paths, Python native modules, and executable permissions must also work.
- F4: The same Rust file starts uvicorn, sets model/cache/output paths through Tauri app directories, starts a Unix process group, and kills that process group on service stop. Desktop settings include an FFmpeg path; changing it restarts the child service. These ownership assumptions need an explicit Linux design.
- F5: `src-tauri/tauri.conf.json` bundles `.bundle-venv`, `service`, `config.yml`, `pyproject.toml`, and `uv.lock`. It fixes the window at 1120 by 920 pixels, disables resize/maximize, and sets CSP to null. Test Linux resource paths and usability under tiling/scaling. Scope security work to the new management surface and required behavior, not unrelated cleanup.
- F6: `src-tauri/Cargo.toml` declares Tauri 2.10.3, tauri-build 2.5.6, and dialog/log plugins. `pyproject.toml` permits Python >=3.11 and depends on Kokoro, Piper >=1.7.0, FastAPI, uvicorn, numpy, PyYAML, and a direct spaCy English model wheel. A Python lower bound does not prove the newest system Python is supported by all native dependencies.
- F7: `service/providers/kokoro.py` lazily creates `KPipeline(lang_code=...)`. `is_ready()` calls the loader, so readiness checks can cause model acquisition through dependencies. It configures espeak through `espeakng_loader` and `phonemizer`. Cataloged voices cover English and Spanish; the code accepts some additional language prefixes, which is not approval to add languages to this release.
- F8: `service/providers/piper.py` downloads `.onnx` and `.onnx.json` from Hugging Face during voice loading. It uses `.part` then rename, per-voice locks, and a short espeak data path workaround. Reuse applicable safeguards, but the two-file set is not yet a complete explicit download lifecycle. Its readiness check only imports Piper; it does not prove a selected model is installed.
- F9: `service/core/dependencies.py` already searches PATH and standard Linux binary locations, but its missing-FFmpeg message tells every user to run `brew install ffmpeg`. `tests/test_dependencies.py` asserts this text. `desktop/index.html` also contains a Homebrew FFmpeg placeholder.
- F10: `desktop/app.js` uses HTML audio/blob URLs, native save dialogs, export requests, and drag/drop listeners. Linux MP3 generation through FFmpeg and Linux WebKit audio decoding are separate concerns.
- F11: `extension/manifest.json` has macOS-specific marketing text, general shortcuts, and macOS overrides. The extension already talks to localhost and plays audio in an offscreen document. No extension rewrite was justified by the inspection.
- F12: `.github/workflows/release.yml` currently builds and releases only the extension ZIP. It does not build desktop release artifacts.
- F13: `service/app.py` currently configures permissive CORS (`allow_origins=["*"]`). Verify the full request path before adding model download/delete APIs. Loopback binding alone does not authorize callers.
- F14: Existing tests include `test_config.py`, `test_dependencies.py`, `test_health.py`, `test_router.py`, `test_kokoro_provider.py`, `test_piper_espeak_path.py`, `test_document_chunks.py`, and `test_markdown.py`. The Rust library also contains runtime/path/error tests. No test suite was run in this planning session.

## Local environment observed during planning

- E1: `uname -m` returned `x86_64`; `omarchy version` returned `4.0.4-1`.
- E2: Installed package queries returned WebKitGTK 4.1 version 2.52.6-1, GTK3 3.24.52-1, GStreamer good/libav plugins 1.28.6-3, FFmpeg 9.0.1-4, and Python 3.14.7-1. Re-query before implementation; these are one-machine observations, not release requirements.
- E3: The package query did not return entries for `uv`, `espeak-ng`, or `gst-plugins-bad`. This does not prove corresponding tools/libraries are unavailable through another installation method.
- E4: `omarchy-shell`, `quickshell`, `wl-paste`, and `systemctl` were found. `OMARCHY_PATH` is `/usr/share/omarchy`. The combined discovery command exited nonzero because not all queried commands were present; its trailing `omarchy --help` did not run. No exact plugin installation API was verified.
- E5: Installed Omarchy guidance describes user shell plugins under `~/.config/omarchy/plugins/<plugin-id>/` and overrides in `~/.config/omarchy/shell.json`. Packaged files under `/usr/share/omarchy/` are read-only for this work. Confirm the actual shell/plugin API and Hyprland configuration format rather than guessing from older releases.

## External sources already consulted

- S1: https://v2.tauri.app/start/prerequisites/ : Tauri Linux has platform-specific system prerequisites, including WebKitGTK. Read the current Arch section before declaring package dependencies.
- S2: https://v2.tauri.app/distribute/appimage/ : AppImage builds must respect the minimum supported glibc baseline. Audio/video applications need `bundle.linux.appimage.bundleMediaFramework`; documentation says this is fully supported on Ubuntu build systems. This is relevant only if AppImage is later chosen. Do not build an AppImage merely because Tauri supports it.
- S3: https://v2.tauri.app/distribute/ : distribution overview, fetched but not used to establish an Arch packaging recipe.
- S4: Local skill references: `/home/dpaluy/.pi/agent/skills/omarchy/SKILL.md` and `plugins.md` in that directory. Read `hyprland.md` before modifying bindings. Source discovery must use the installed CLI and local read-only examples.

Open research includes frozen model asset manifests and redistribution rights, dependency-controlled downloads, runtime relocation, and package size. Do not invent model sizes, memory requirements, performance numbers, checksums, or license permissions.

## T01 baseline and contracts (Omarchy 4.0.4-1, x86_64)

This worktree starts at `08e50f7` on `hp/local-voice-omarchy/t-0002-t01-linux-baseline-and-contracts`, with this plan present. `feat/omarchy` at `a407f59` is the pre-plan research base. No packages, real weights, or host configuration were changed.

### Dependency and test baseline

- `pyproject.toml` requires Python >=3.11, FastAPI, uvicorn, Pydantic, Kokoro, numpy, PyYAML, Piper, and the direct `en_core_web_sm` 3.8.0 wheel. `uv.lock` resolves Kokoro 0.9.4, Misaki 0.9.4, Piper 1.7.0, spaCy 3.8.14, Torch 2.11.0, espeakng-loader 0.2.4, and phonemizer-fork 3.3.2. Python 3.14.7 is installed here, but native wheel compatibility and a supported release Python version are **unknown**. Neither `pyproject.toml` nor the lock proves that combination starts. The release runtime must include compatible native Python modules, espeak data/library, FFmpeg for MP3, and Linux Tauri WebKitGTK/GTK and media decoding dependencies. Tauri's [Linux prerequisites](https://v2.tauri.app/start/prerequisites/) give a build baseline, not a tested package dependency set. Installed: `omarchy` 4.0.4-1, `webkit2gtk-4.1` 2.52.6-1, GTK3 3.24.52-1, FFmpeg 9.0.1-4, GStreamer good/libav 1.28.6-3. `uv` 0.9.26 and Cargo are on PATH; `espeak-ng` executable is not on PATH. Python packages can supply espeak independently.
- Baseline command `PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s tests -v` with system Python 3.14.7: 17 tests pass, four test-module imports fail because `yaml` or `fastapi` is missing. These are pre-existing environment/dependency gaps, not newly introduced test failures. No project virtual environment is present. Full Python suite requires permission to install dependencies in a disposable environment, or a supplied prepared runtime.
- `CARGO_TARGET_DIR=/tmp/local-voice-t01-cargo cargo test --offline --lib` fails before compilation: cached crates.io index lacks `tauri`. No Rust tests ran. A network-enabled dependency fetch/build or prepared Cargo cache is needed; neither is evidence of an installed Linux app. Rust release, native GUI, macOS, and real inference remain unverified. The test commands are `python -m unittest discover -s tests -v` and `cargo test --lib` from `src-tauri/`; extension tests are not established by this baseline.

### Verified shell contract and ownership

The installed `/usr/share/omarchy/shell/README.md`, `plugins/README.md`, `plugins/bar/README.md`, and `plugins/panels/clock/manifest.json` specify a user-owned `~/.config/omarchy/plugins/<id>/manifest.json` with `schemaVersion: 1`, namespaced `id`, `kinds: ["bar-widget"]`, `entryPoints.barWidget`, and a QML entry point. `barWidget.defaultSection` is optional. Hand installation: copy source to that directory, `omarchy-shell shell rescanPlugins`, then `omarchy plugin enable <id>`; the latter places the widget in the center by default, and `omarchy bar move` changes its section. `shell.json` requires `version: 1`; it is a full user override, not a deep merge. Plugin presence in `bar.layout` enables a third-party widget. The shell hot-reloads user plugin files. The registry and widget API are version-specific; test actual loading in T08. Do not use `omarchy plugin add` for the packaged integration: it clones a separate Git repository, and package installation must not write the user's config. No user config was edited in T01.

Service/control boundary: one loopback systemd **user** service owns Linux synthesis and model jobs; desktop and Chrome keep their own playback sessions; the panel calls a dedicated local clipboard playback controller whose stop affects only its own session. The panel uses the manifest-backed bar-widget API and reads controller/service status, not clipboard contents. Setup must be an explicit, reversible user action. The browser has no management authority by default. The existing LAN server-mode toggle and model-management authorization remain design blockers for T03/T06; no new API is presumed secure just because it binds to loopback. On macOS retain the current app-owned service and browser playback path until tested replacement. The shared Linux process must not be killed on desktop close.

### User model choice and asset inputs

**Product decision (revised):** users choose languages independently: English (Kokoro), Spanish (Kokoro), and Russian (Piper Dmitri only). No model is selected or acquired at install/startup/health/selection. Shared Kokoro files are listed once and reused by English and Spanish. English alone requires the optional spaCy `en_core_web_sm` asset. Irina and Ruslan are excluded. Amounts below are upstream file sizes in bytes, **not** total installed disk use or full package/download size. Freeze upstream revisions, hashes, transitive runtime assets, and license notices before implementing downloads.

| Choice | Included voice assets and engines | Known speech-file transfer size | License evidence |
| --- | --- | ---: | --- |
| English | Kokoro shared `config.json` (2,351) and `kokoro-v1_0.pth` (327,212,226); six voice `.pt` files: `af_bella` 523,425, `af_sarah` 523,425, `am_adam` 523,420, `am_michael` 523,435, `bf_emma` 523,420, `bm_george` 523,430. English Misaki G2P needs `en_core_web_sm` 3.8.0 and espeak fallback/runtime assets. | 330,355,132 for Kokoro files; spaCy wheel adds 12,806,118 if downloaded as an optional asset. Other runtime transfer/disk use unknown. | Kokoro model card: Apache-2.0. spaCy wheel and runtime license/redistribution inventory incomplete. |
| Spanish | Kokoro shared `config.json` (2,351) and `kokoro-v1_0.pth` (327,212,226), plus `ef_dora` 523,420, `em_alex` 523,420, `em_santa` 523,430 (Spanish through espeak). Shared files are acquired once when English and Spanish are both chosen. | 328,784,847 for Kokoro files; runtime extras unknown. | Kokoro model card: Apache-2.0; runtime inventory incomplete. |
| Russian | Piper `ru_RU-dmitri-medium` `.onnx` 63,201,294 and `.onnx.json` 4,824. Piper runtime includes its espeak phonemizer/data. | 63,206,118 for Piper files; runtime extras unknown. | Dmitri model card: CC0; Piper repository metadata: MIT. Runtime redistribution inventory incomplete. |

Kokoro source: [model tree](https://huggingface.co/hexgrad/Kokoro-82M/tree/main), [voice tree](https://huggingface.co/hexgrad/Kokoro-82M/tree/main/voices), [tree metadata API](https://huggingface.co/api/models/hexgrad/Kokoro-82M/tree/main/voices?expand=true), [model card](https://huggingface.co/hexgrad/Kokoro-82M). Piper source: [versioned tree API](https://huggingface.co/api/models/rhasspy/piper-voices/tree/v1.0.0/ru/ru_RU?recursive=true&expand=true), [repository metadata](https://huggingface.co/rhasspy/piper-voices/blob/v1.0.0/README.md), and [Irina](https://huggingface.co/rhasspy/piper-voices/blob/v1.0.0/ru/ru_RU/irina/medium/MODEL_CARD), [Dmitri](https://huggingface.co/rhasspy/piper-voices/blob/v1.0.0/ru/ru_RU/dmitri/medium/MODEL_CARD), [Ruslan](https://huggingface.co/rhasspy/piper-voices/blob/v1.0.0/ru/ru_RU/ruslan/medium/MODEL_CARD) cards. The spaCy wheel size comes from the [3.8.0 release asset API](https://api.github.com/repos/explosion/spacy-models/releases/tags/en_core_web_sm-3.8.0). Upstream [Kokoro pipeline](https://github.com/hexgrad/kokoro/blob/main/kokoro/pipeline.py) downloads voices through `hf_hub_download`; [Misaki English G2P](https://github.com/hexgrad/misaki/blob/main/misaki/en.py) calls `spacy.cli.download` if the model package is absent. These moving source-code links verify the current path, not the locked versions' complete transitive behavior. The current provider also downloads Piper files on first synthesis. Test the **locked** dependency chain under denied network in T04.

English, Spanish, and Russian can be selected separately, including multiple languages in one request. M3 conflicts now: the spaCy wheel is an unconditional package dependency, so installation acquires an English speech model before English is selected. Move it behind explicit English consent and verify its loader does not install it itself. Unlike the weights, engine/runtime libraries can be installed as required package dependencies, but espeak data and any bundled speech assets must be disclosed and classified before packaging. Never present the 12.8 MB wheel as the whole installed spaCy footprint.

**T01b approval blockers:** the user approved Dmitri only for Russian. Confirm a licensing policy for downloaded versus redistributed assets before T03b/T12. Real model download, dependency installation, persistent setup, external writes, and package publication still require separate authority. **T01c test-environment blockers:** a disposable dependency-equipped Python/Cargo environment and later an approved real-model/GUI target are needed to prove native compatibility and inference. Runtime Python version, relocation, complete transitive model inventory, hash/revision pinning, offline loader behavior, and full disk footprint remain unknown; T02/T03/T04 must resolve them rather than infer them from this inventory.

## Model management contract

- M1: Start with no selected TTS model. A missing model is a normal setup state, not a crashed service. Health separates service liveness, installed dependencies, installed assets, and usable voices without loading/downloading models.
- M2: Use a bounded catalog for the existing supported voices. Each entry needs a stable ID, label, language/voice relationships, required/shared assets, source and revision, license information, download size when verified, and integrity metadata when available. Unknown size must be labeled unknown. No arbitrary URL/path installation API.
- M3: Inventory every asset acquired by Kokoro, Hugging Face, spaCy/Misaki, Piper, and espeak-related dependencies. Distinguish installed runtime packages from optional speech assets. The existing spaCy model dependency needs an explicit decision: make it selectable with its required engine assets, or disclose any unavoidable runtime asset before installation. Do not silently ship optional models under a package label.
- M4: Download is an explicit management action. Present all shared and voice-specific assets and disk use before consent. Handle insufficient space, offline state, HTTP failures, cancellation, duplicate requests, and app closure. Download jobs belong to the service, not the window.
- M5: Publish an installed model only after every required file is validated. Use bounded paths under the application data location, staging files, atomic completion, and durable inventory or reproducible disk inspection. Partial files are never used for synthesis.
- M6: Cancellation and retry are required; byte-range resume is optional and should not add complexity without need. Define cleanup and retention of partial data. Service restart must recover a truthful status rather than report a stale active job.
- M7: Model removal is explicit. Do not remove shared files still needed by another installed model. Release cached provider objects safely; refuse removal while a synthesis/download job uses the assets. Coordinate access across actual worker threads/processes, not just UI state.
- M8: Configure providers for local-only loading outside the approved downloader. Missing assets return a structured actionable error. Voice listing and selection never fetch data. Prove this with denied-network tests, not only mocks of the top-level download function.
- M9: Define compatibility for existing downloaded assets. Discover and validate supported old locations or offer explicit migration. Do not delete/re-download user assets silently. Do not delete espeak path workarounds until supported installations are verified.
- M10: Protect download, removal, and filesystem operations from arbitrary websites, path traversal, and LAN clients. Define request authorization and allowed origins compatible with the desktop, panel, and browser extension. Do not expose management APIs through server mode without a separate approved design.

### T03a catalog and management API handoff

`GET /models` returns bounded `languages` (id, label, engine, shared/required asset IDs, voice IDs and per-voice asset IDs, installed flags) and a deduplicated `assets` array (id, relative path, upstream source/revision, license, known byte size or null, SHA-256 or null, state). English, Spanish, and Russian are independent selections. Inventory inspects only catalog paths under `LV_MODELS_DIR`; an absent file is `absent`, a size mismatch is `invalid`, and a size match without a frozen digest is `present_unverified`, **not installed**. Symlinks are not accepted. No current catalog asset has a verified digest or frozen Kokoro revision. Runtime/transitive assets and actual installed footprint remain unknown. T03b must freeze integrity and source revisions before accepting downloads or promoting assets to `verified`; T04 must not infer provider readiness from mere presence.

Management routes require a direct loopback peer and loopback Host, an explicit `LV_MANAGEMENT_TOKEN` supplied in `X-Local-Voice-Management`, and no web/extension Origin (native Tauri origins are allowed). With no configured token, management is disabled. This is a provisional local capability, not a desktop token delivery mechanism. T05/T06 must provide a secret to the desktop without exposing it to browser pages, and must verify actual Tauri origins and LAN server mode before enabling the UI. Existing permissive CORS on synthesis routes does not grant management access; do not weaken this guard to make the browser a model manager.

Reserved job API, currently responds 501 after authorization and does not mutate state: `POST /models/downloads` body `{languages: ["en", "es", "ru"]}` (one or more catalog IDs), `GET /models/downloads/{job_id}`, `POST /models/downloads/{job_id}/cancel`, and `POST /models/removals` body `{languages: [...]}`. T03b should return 202 with `{job_id, status}` on accepted download, 409 for conflicting active work, and expose `{job_id, languages, status, bytes_done, bytes_total, error}` on polling. Statuses: `queued`, `downloading`, `completed`, `failed`, `cancelled`; unknown totals are null. T03c should return 409 when an asset is in use and protect shared assets. Define exact atomic validation, migration, and removal semantics in those tasks, then update this contract. No job/removal behavior is claimed here.

### T03b lifecycle handoff

The service now owns in-process background download jobs. An identical active request returns the same job ID (202); conflicting work returns 409. Transfers use pinned source revisions, bounded catalog paths, SHA-256 and size validation in per-job staging; only a complete validated set is promoted. Cancellation discards staging; retry starts a new job. Catalog inventory rehashes files after restart, so a lost in-memory job ID returns 404 rather than a false active status. Removal is still T03c. One service worker process is assumed; cross-process locking and crash cleanup of abandoned `.downloads` staging need integration decisions before running multiple workers. Promotion is atomic per file, not across the whole language set; consumers must check the complete required set.

Kokoro is pinned to `f3ff3571791e39611d31c381e3a41a3af07b4987` and Piper to `375a0fe641dea077c2a47b4e9a056d6da521eed3`. LFS SHA-256 OIDs came from the revision-specific Hugging Face tree API; the small config SHA-256 values were computed from revision-specific upstream files, not model weights. The spaCy wheel digest in `uv.lock` has no independent upstream checksum in the GitHub release API. English download returns 409 until its digest can be verified under the no-real-model-download restriction. Runtime/transitive asset inventory remains a T04/package gate; this implementation does not prove offline synthesis.

### T03c lifecycle handoff

`POST /models/removals` accepts language IDs and removes only verified files not required by any retained language. It returns removed asset IDs, or 409 for active downloads, active synthesis, unverified files, or a missing provider-cache release hook. T04 must register `model_lifecycle.register_release(callback)` and hold `model_lifecycle.using(set(voice_assets(language, voice)))` over each full synthesis, including model loading and audio generation, across short, stream, and export paths. The callback must evict cached Kokoro/Piper objects for the affected assets before unlinking. Until T04 wires this, removal fails closed, not silently without cache eviction. Only one worker process may own the model store: the API router startup obtains a nonblocking `flock` on `.management.lock` under `LV_MODELS_DIR` and removes abandoned `.downloads` staging. A second process fails startup. T06 must launch exactly one uvicorn worker, not `--workers N`, and keep the router lifespan active. The lock applies to model management within this service, not to unrelated standalone processes or legacy providers that bypass the T04 hook.

`GET /models/migration` lists hash-verified candidates from Hugging Face Kokoro snapshots (`HF_HUB_CACHE` or `HF_HOME/hub`, otherwise `~/.cache/huggingface/hub`) and prior desktop `service-models` locations under Tauri's app-data directory on macOS or XDG Linux, plus the repository's old artifact model directory. `POST /models/migration` accepts candidate IDs from that list and copies through staging with size and SHA-256 revalidation. It does not delete sources, overwrite destinations, or download anything. Existing Piper files in the active `LV_MODELS_DIR/piper` already match the catalog layout and need no copy. The English spaCy wheel has no pinned digest, so it cannot be migrated or marked installed. Migration is per asset and does not imply a language is installed until its full set verifies. Old caches at other locations need explicit support after evidence, not an arbitrary filesystem-path API. Lost in-memory download IDs still return 404 after restart; staging is reclaimed before requests can start.

## Task packets and dependencies

Each T-code maps to one Herdr backlog item. These packets are ready for later delegation; no thread is currently assigned. A task is complete only with observable validation and a report of changed files, tests actually run, existing failures, assumptions, and remaining blockers.

### T01: Establish Linux baseline and implementation contracts

Dependencies: none.
Read the files identified above and all applicable repository instructions. Confirm the branch/base and installed Omarchy APIs. Identify existing test commands, supported Python/dependency combination, model assets and licenses, and baseline failures. Inspect shell plugin examples read-only. Record the chosen service/control boundaries and compatibility matrix. Do not install packages, download model weights, or edit host configuration without permission. Use disposable fixtures for baseline tests where possible; ask before real model acquisition.
Acceptance: evidence-backed dependency list, test baseline, verified plugin interface, model catalog inputs, and concrete unresolved blockers. Update this plan with decisions, not speculative APIs.

### T02: Port Linux runtime preparation and release resources

Dependencies: T01.
Files: `build.sh`, `src-tauri/src/lib.rs`, `src-tauri/tauri.conf.json`, dependency configuration as needed.
Choose a reproducible Linux Python runtime strategy compatible with the package and model-consent policy. Do not rely on rolling system Python ABI or copied developer environments accidentally working. Separate macOS and Linux tools; validate native libraries, interpreter relocation, resource paths, read-only install locations, and writable XDG data/cache paths. Pin build tooling where necessary using existing project conventions.
Acceptance: a Linux release starts outside the checkout without the developer `.venv` or shell PATH; runtime tests cover Linux/missing assets; macOS path remains valid. T12 later proves installed behavior.

### T03: Implement model catalog and lifecycle APIs

Dependencies: T01.
Files: new focused service modules/endpoints plus existing config/models/health where needed.
Implement M1-M10 backend behavior: inventory, explicit background download, progress/status, cancellation/retry, atomic validation, removal, shared assets, migration policy, and management authorization. Agree API shapes with T04/T05/T10 before those tasks start. Persist only required state. Do not log user text or allow arbitrary filesystem paths.
Acceptance: API tests cover zero-model startup, duplicate/concurrent requests, corrupt/incomplete files, cancel/retry/restart, disk errors, in-use deletion, shared assets, and unauthorized callers. Test downloads against a disposable local fixture server.

### T04: Make providers and health local-only

Dependencies: T03.
Files: `service/providers/kokoro.py`, `service/providers/piper.py`, `service/providers/router.py`, `service/api/health.py`, dependency checks/tests.
Replace implicit acquisition with validated local catalog paths. Prevent startup/readiness/voice-list side effects. Preserve synthesis routing, chunking, speed, format, espeak workarounds, and existing supported voices. Audit transitive loader behavior, not just these two modules.
Acceptance: missing assets produce setup-needed errors with no network attempt; installed fixture assets load through provider interfaces; approved real models synthesize offline in final integration tests. Existing provider/health tests remain meaningful.

### T05: Add desktop model manager

Dependencies: T03, T04.
Files: `desktop/index.html`, `desktop/app.js`, `desktop/styles.css`, Tauri commands/capabilities only if required.
Build catalog/status UI, required-asset consent, progress/cancel/retry, removal confirmation, and setup-needed state. Keep long downloads owned by the service; reconnect after window closure. Disable or clearly mark unavailable voices. Distinguish installed, downloading, failed, and ready without treating a live zero-model service as broken.
Acceptance: test observable user flows, including unknown size, failed download, shared assets, removal in use, and reconnection. No network/model acquisition from simply opening the UI or selecting a voice.

### T06: Add shared Linux service ownership

Dependencies: T02, T04.
Files: Linux user service definition, Rust service manager/settings, platform integration helpers.
Make desktop/panel/browser share one backend. Define login activation, readiness, restart, port conflict, logs, environment, and directory ownership. Keep model data available across upgrades. Reconcile FFmpeg setting updates and the existing server-mode toggle with external service ownership; do not silently expand network exposure. Handle an already running standalone backend explicitly rather than killing it.
Acceptance: desktop close does not stop the shared service, reopen does not duplicate it, model configuration persists, startup with no models is healthy/setup-needed, and startup failures are actionable. Use a disposable user/session for lifecycle validation where practical.

### T06 shared-service handoff (implementation candidate)

Linux uses `packaging/arch/local-voice.service`, installed but disabled by default. Opening the desktop starts the unit through `systemctl --user start`; closing the app does not stop it. To serve browser/panel before opening the desktop on later logins, the user explicitly opts in with `systemctl --user enable --now local-voice.service`. No lingering is configured. The unit is one worker, listens only on `127.0.0.1:5517`, and uses journal logs (`journalctl --user -u local-voice.service`). `systemctl --user restart local-voice.service` restarts it. No service process is owned by the desktop on Linux. macOS retains the app-owned process and settings behavior.

The prospective T12 package layout is `/usr/lib/local-voice/{start-service,service_launcher.py,service,config.yml,.bundle-venv}` with the unit in `/usr/lib/systemd/user/`. T12 must validate this layout and interpreter relocation against the installed package. Persistent model/output data is in `~/.local/share/dev.majesticlabs.localvoice/`, cache in `${XDG_CACHE_HOME:-~/.cache}/dev.majesticlabs.localvoice/service-cache`; upgrades must preserve data. The launcher creates a 0600 management token at the app data path and passes it only through the unit process environment. The Rust `manage_models` command reads this file and proxies only bounded model routes to loopback. Browser JS does not receive the token. T05 should use this command, not send management requests directly. Download jobs stay in this one service process, per T03c's single-worker constraint. Validate actual Tauri app-data path and native origin before release.

The Linux FFmpeg path field and LAN toggle are disabled. Setting `LV_FFMPEG_PATH` in a user-service override plus restarting the unit is the explicit FFmpeg route; the LAN toggle cannot bind this shared service to a public interface. A pre-existing standalone process on the port is reported as a conflict, never killed or adopted. The Linux desktop checks unit activity and `/health` before reporting ready; startup failure points to the journal. Installation alone does not start the unit or fetch models. Disposable unit tests, installed process identity, GUI, real-model inference, and macOS validation remain T12/T13 gates.

### T07: Implement clipboard playback controller

Controller protocol (T07 candidate): `local-voice-controller read-clipboard|stop|status` uses a private Unix socket under `$XDG_RUNTIME_DIR/local-voice/controller.sock`. The first read starts the controller process; stop/status do not start it. Status returns JSON `{state,error}` with `idle`, `reading`, `synthesizing`, `playing`, `setup_needed`, `error`, or `offline`. The panel should invoke this CLI rather than reading the clipboard. Repeated reads replace the prior session; stop cancels queued chunks and terminates only this controller's player. The current HTTP synthesis request can finish in the service after stop, but its result is discarded. The controller uses `wl-paste --type text/plain` on the explicit read command and `ffplay` via stdin for MP3 output. On the inspected Omarchy host `/usr/bin/ffplay` belongs to the existing `ffmpeg` package, so no new playback dependency is needed; `wl-paste` belongs to `wl-clipboard`. Text is never interpolated in a shell command. The service still synthesizes, never plays. T12 must package the CLI wrapper and verify its installed interpreter and runtime path. Native audio and real inference remain T13 gates.

Dependencies: T04, T06.
Select the smallest suitable existing playback dependency after inspecting the target. Retrieve clipboard text only on command. Use argument arrays/stdin, never shell interpolation of text. Support long-text chunk playback, bounded queue/state, stop/cancellation, service-not-ready errors, missing-model guidance, repeated invocation, and cleanup. Define panel status interface and session ownership for T08/T09. Preserve browser/desktop playback independence.
Acceptance: copied text produces audio through the desktop audio system without the Tauri window open; stop halts controller audio and its queued synthesis; repeated commands do not overlap accidentally; empty/non-text clipboard and failed requests are safe; no clipboard text in logs.

### T08: Implement Omarchy shell panel plugin

Dependencies: T05, T07.
Use the verified installed plugin interface. Provide status, read clipboard, stop, open app, and setup/model-manager entry. Handle missing backend/controller cleanly. Keep state polling bounded; do not poll the clipboard. Keep the plugin thin and reuse controller/service logic.
Acceptance: plugin loads through user-owned configuration, reflects actual playback and setup state, survives shell reload, and leaves packaged Omarchy files untouched. Verify against the declared supported Omarchy version.

### T09: Add shortcuts and reversible user integration

Dependencies: T07, T08.
Provide read-clipboard and stop bindings with collision detection or a user-chosen binding flow. Do not choose unverified global key combinations. Installer/setup must show the changes, use user-owned config, preserve unrelated edits, and record exactly what it owns. Make repeated setup idempotent and removal surgical. Validate Hyprland with its current supported tools after approved host changes.
Acceptance: install/setup twice produces one integration, conflicting bindings are reported, removal preserves all unrelated configuration, and no desktop configuration changes occur from package installation without explicit setup/consent.

### T10: Adapt Chrome integration to model availability

Dependencies: T03, T04, T06.
Files: extension API/store/background/popup/constants and manifest as needed.
Keep extraction and playback behavior. Update platform wording and model-ready voice handling. Show useful setup/download-required errors; model installation is initiated only through explicit management, not synthesis. Preserve user settings and browser permission boundaries. Document opening the desktop model manager if direct launch is unavailable.
Acceptance: installed voices work against the shared backend, absent models do not trigger downloads, stop/long text remain functional, and Chrome installation is a documented separate step. Do not promise a Store listing until its publication status is verified.

### T11: Validate and fix Linux desktop behavior

Dependencies: T05, T06.
Files: Tauri window config and desktop files, only for confirmed issues.
Check Wayland/Hyprland tiling, small/scaled displays, clipboard paste, text/Markdown drop, file dialogs, short and long playback, stop, and MP3 export. Address fixed window constraints where necessary without redesigning the app. Treat FFmpeg encoding and WebKit/GStreamer decoding separately. Use native GUI verification for claims about Tauri, not browser-only tests.
Acceptance: documented end-to-end desktop flows work on the target. Native Linux dependency errors are actionable. No macOS regression is knowingly introduced.

### T12: Build installable Arch package

Dependencies: T02, T06, T08, T09, T10, T11.
Add an auditable PKGBUILD/package recipe and release artifact assembly. Package the desktop launcher/icon, service, controller, and plugin assets with correct ownership/dependencies. End users need no Rust/Node/source checkout. Avoid root pip installation and optional model weights in the package. Declare runtime/native media dependencies, license notices, and supported architecture. Installation must not edit a running user's panel or silently fetch models.
Acceptance: clean install, normal launcher startup, explicit integration setup, upgrade, and uninstall work in a disposable Arch/Omarchy environment. Uninstall retains user data by default. Inspect the installed artifact for missing libraries and confirm the running process uses it, not repository files.

### T13: Run cross-interface and failure acceptance tests

Dependencies: T12.
Run the release checklist below with the installed artifact. Use disposable homes/model stores and local test servers; obtain consent before real model downloads, host package installation, or persistent desktop edits. Include approved real Kokoro/Piper assets to prove inference/audio behavior, plus network-denied runs. Record model identities, artifact identity, environment, and results.
Acceptance: all required checks pass or concrete blockers are reported. Fixture tests alone cannot prove real native engine/playback readiness.

### T14: Add reproducible CI and release artifact jobs

Dependencies: T12; final readiness also requires T13.
Files: `.github/workflows/release.yml` and focused build/test workflow additions.
Run deterministic service/Rust tests, build Linux package artifacts, preserve extension ZIP delivery, and retain macOS validation where supported. Make asset-fixture tests network independent. Keep model-weight downloads out of routine tests unless explicitly configured and licensed. Document which graphical checks require target-machine verification. Preparing workflow code does not authorize pushing tags or creating releases.
Acceptance: workflow syntax/build steps are checked using existing consumers where practical; actual executed local/CI results are distinguished. Final CI green status can be claimed only after an authorized run.

### T15: Write user and maintainer documentation

Dependencies: T12, T13, T14.
Update README/install/config/troubleshooting instructions for Omarchy and macOS. Cover one supported installation route, browser setup, explicit model choice and disk use, offline use, panel/shortcut controls, login startup, logs, restart, port conflicts, upgrade/removal, and data retention. Document exact supported versions and known limitations. Include third-party model/runtime license notices and verify redistribution rights rather than guessing.
Acceptance: a new user can follow the published instructions without cloning the source or starting a server manually; every command matches the artifact tested in T13.

### T16: Approve and publish the first Omarchy release

Dependencies: T13, T14, T15 and explicit user approval.
Present release evidence, artifacts/checksums, supported target, known limitations, license checks, and distribution destination. Ask for authorization before external writes, tags, releases, PRs, or registry submissions. Verify the account/repository before publishing and verify uploaded artifacts afterward. Do not submit to AUR unless asked.
Acceptance: approved artifacts match tested builds and public instructions. If approval has not been given, remain pending with a local release candidate, not a fabricated publication claim.

## Execution order and handoff rules

- A1: Start with T01. Then T02 and T03 can proceed independently after contracts are settled.
- A2: T04 follows T03. T05 and T06 can then proceed once their dependencies are satisfied. Coordinate changes to the Rust manager; avoid concurrent edits to the same ownership logic.
- A3: T07 follows shared service/provider readiness; T08/T09 follow controller contracts. T10 and T11 can proceed independently when their prerequisites are complete.
- A4: T12 integrates packaging. T13 and T14 validate it. T15 documents tested behavior; T16 is a user approval gate.
- A5: Follow the configured Herdr thread profile and parallel cap. Do not change safety settings, profiles, or start agents merely because this backlog exists. Ask the user to delegate tasks when ready.
- A6: Every code task uses meaningful regression tests and preserves unrelated user changes. No source-string assertion tests, speculative abstractions, broad cleanup, or removal of compatibility paths without consumer/migration evidence.

## Release acceptance checklist

- V1: Fresh installation contains no silently selected optional TTS model. Startup, health, voice listing, selection, and attempted synthesis do not download assets.
- V2: Explicit download lists shared/voice assets and verified sizes or unknown status. Cancel, retry, insufficient space, corruption, concurrency, and interrupted restart have truthful states.
- V3: Removal protects active jobs and shared assets. Existing supported model caches are preserved or explicitly migrated.
- V4: Independently selected English/Spanish Kokoro and Russian Piper Dmitri work offline with user-approved installed assets. Record which representative voices were actually exercised; do not infer all voices passed.
- V5: Desktop, Chrome, and panel/shortcut paths all work against one service. Closing the desktop leaves panel/browser usable. Each playback surface has correct stop behavior under the documented ownership contract.
- V6: Clipboard reads require explicit action. Quoting/metacharacters and non-text content cannot cause command execution. New management APIs reject unauthorized origin/caller, path traversal, and unintended LAN access.
- V7: Wayland launch, tiling/scaling, file drop/save, short/long playback, and MP3 export pass native tests. Missing media dependencies produce useful diagnostics.
- V8: Startup/restart, existing-service conflict, setup twice, upgrade, and uninstall are tested in disposable environments. User config and models survive where documented.
- V9: Release starts from its installed location with the development checkout unavailable. Process identity confirms the tested binary/runtime is the new artifact.
- V10: Linux tests/build pass; macOS checks are run on a suitable environment or explicitly reported unverified. Documentation and license notices match the actual artifact.

## Deferred or unknown

- U1: Exact Python version, CPU/GPU dependency selection, package size, runtime relocation approach, and real engine performance are not established.
- U2: Exact Omarchy plugin installation/schema and minimum supported shell version need installed-source verification.
- U3: Complete Kokoro/spaCy/Misaki/voice asset list, hashes, download sizes, and licenses need source verification. Piper file pairs alone do not describe the whole engine dependency chain.
- U4: Playback dependency and detailed controller protocol are not chosen. Do not turn the TTS HTTP service into an audio server without evidence that this is simpler and safe.
- U5: Migration of existing model caches and desktop settings needs supported-installation evidence.
- U6: Shared Linux service behavior for the existing LAN server-mode toggle needs a concrete design. Model management is local-only by default.
- U7: Neither Linux build success nor baseline test success has been established. No performance or time estimate is justified yet.

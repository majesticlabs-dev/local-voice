import { stripMarkdown } from './markdown.js';

const SETTINGS_KEY = 'local-voice-desktop-settings';
const DEFAULT_SETTINGS = {
  voice: 'af_bella',
  rate: 1,
  serverMode: false,
};

const tauriApi = window.__TAURI__ ?? {};
const invoke = tauriApi.core?.invoke;
const confirmDialog = tauriApi.dialog?.confirm
  ? (message, options) => tauriApi.dialog.confirm(message, options)
  : async (message) => window.confirm(message);
const messageDialog = tauriApi.dialog?.message
  ? (message, options) => tauriApi.dialog.message(message, options)
  : async (message) => window.alert(message);
const saveDialog = tauriApi.dialog?.save
  ? (options) => tauriApi.dialog.save(options)
  : async () => null;

const state = {
  loading: false,
  loadingText: 'Preparing audio…',
  ffmpegPath: '',
  healthPhase: 'starting',
  healthReady: false,
  healthText: 'Starting service…',
  settingsOpen: false,
  startupError: '',
  startupErrorTitle: 'Startup issue',
  startupIssueNotice: '',
  serviceInfo: null,
  activeChunk: 0,
  totalChunks: 0,
  playbackPercent: 0,
  playing: false,
  paused: false,
  playToken: 0,
  currentAudioUrl: null,
  cancelPlayback: null,
  lastSpeak: null,
  voicesLoaded: false,
  track: null,
  estimatedDuration: 0,
};

const els = {
  audio: document.querySelector('#audio-player'),
  backwardButton: document.querySelector('#backward-button'),
  chunkProgress: document.querySelector('#chunk-progress'),
  downloadButton: document.querySelector('#download-button'),
  fileInput: document.querySelector('#file-input'),
  fileName: document.querySelector('#file-name'),
  ffmpegPath: document.querySelector('#ffmpeg-path'),
  healthDot: document.querySelector('#health-dot'),
  healthPill: document.querySelector('#health-pill'),
  healthText: document.querySelector('#health-text'),
  lanNote: document.querySelector('#lan-note'),
  loadingRow: document.querySelector('#loading-row'),
  loadingText: document.querySelector('#loading-text'),
  pauseButton: document.querySelector('#pause-button'),
  progressFill: document.querySelector('#progress-fill'),
  rateInput: document.querySelector('#rate-input'),
  rateValue: document.querySelector('#rate-value'),
  resetText: document.querySelector('#reset-text'),
  restartButton: document.querySelector('#restart-button'),
  settingsButton: document.querySelector('#settings-button'),
  settingsClose: document.querySelector('#settings-close'),
  settingsOverlay: document.querySelector('#settings-overlay'),
  serverMode: document.querySelector('#server-mode'),
  speakButton: document.querySelector('#speak-button'),
  startupErrorCard: document.querySelector('#startup-error-card'),
  startupErrorCopy: document.querySelector('#startup-error-copy'),
  startupErrorTitle: document.querySelector('#startup-error-title'),
  statusText: document.querySelector('#status-text'),
  stopButton: document.querySelector('#stop-button'),
  textField: document.querySelector('.input-panel .field'),
  textInput: document.querySelector('#text-input'),
  timeText: document.querySelector('#time-text'),
  uploadTrigger: document.querySelector('#upload-trigger'),
  voiceSelect: document.querySelector('#voice-select'),
  forwardButton: document.querySelector('#forward-button'),
};

function loadSettings() {
  try {
    return { ...DEFAULT_SETTINGS, ...JSON.parse(localStorage.getItem(SETTINGS_KEY) ?? '{}') };
  } catch (_) {
    return { ...DEFAULT_SETTINGS };
  }
}

function saveSettings() {
  localStorage.setItem(
    SETTINGS_KEY,
    JSON.stringify({
      voice: els.voiceSelect.value,
      rate: Number(els.rateInput.value),
      serverMode: els.serverMode.checked,
    }),
  );
}

async function loadDesktopSettings() {
  if (!invoke) {
    return;
  }

  const desktopSettings = await invoke('get_desktop_settings');
  state.ffmpegPath = desktopSettings.ffmpegPath ?? '';
  els.ffmpegPath.value = state.ffmpegPath;
}

function setLoading(loading, text = state.loadingText) {
  state.loading = loading;
  state.loadingText = text;
  render();
}

function setStatus(text) {
  els.statusText.textContent = text;
}

function openSettings() {
  state.settingsOpen = true;
  render();
}

function closeSettings() {
  state.settingsOpen = false;
  render();
}

function showError(message) {
  setStatus('Error');
  return messageDialog(message, { title: 'Local Voice Desktop', kind: 'error' });
}

function extractErrorDetail(payload) {
  if (!payload) {
    return '';
  }
  if (typeof payload === 'string') {
    return payload;
  }
  if (typeof payload.detail === 'string') {
    return payload.detail;
  }
  if (Array.isArray(payload.detail)) {
    return payload.detail.map((item) => {
      if (typeof item === 'string') {
        return item;
      }
      if (typeof item?.msg === 'string') {
        return item.msg;
      }
      return JSON.stringify(item);
    }).join('; ');
  }
  return '';
}

async function responseErrorMessage(response) {
  const text = await response.text();
  if (!text) {
    return `Request failed (${response.status})`;
  }

  try {
    const detail = extractErrorDetail(JSON.parse(text));
    if (detail) {
      return detail;
    }
  } catch (_) {}

  return text;
}

function blockingDependencies(dependencies = []) {
  return dependencies.filter((dependency) => dependency?.required && !dependency?.available);
}

function dependencyErrorMessage(dependencies = []) {
  return blockingDependencies(dependencies)
    .map((dependency) => dependency.detail)
    .filter(Boolean)
    .join('\n\n');
}

function applyHealthState(health) {
  const dependencies = Array.isArray(health?.dependencies) ? health.dependencies : [];
  const blocking = blockingDependencies(dependencies);

  state.healthReady = Boolean(health?.ready) && blocking.length === 0;

  if (blocking.length) {
    const missingBinary = blocking.some((dependency) => dependency.name === 'ffmpeg');
    state.healthPhase = 'error';
    state.healthText = missingBinary ? 'Missing dependency' : 'Startup issue';
    state.startupErrorTitle = missingBinary ? 'Missing dependency' : 'Startup issue';
    state.startupError = dependencyErrorMessage(blocking);
    return;
  }

  state.startupErrorTitle = 'Startup issue';
  state.startupError = '';
  state.healthPhase = health?.ready ? 'ready' : 'starting';
  state.healthText = health?.ready
    ? `Service ready (${health.engine})`
    : `Service warming up (${health.engine})`;
}

async function maybeNotifyStartupIssue() {
  if (!state.startupError) {
    state.startupIssueNotice = '';
    return;
  }

  const noticeKey = `${state.startupErrorTitle}\n${state.startupError}`;
  if (state.startupIssueNotice === noticeKey) {
    return;
  }

  state.startupIssueNotice = noticeKey;
  await messageDialog(state.startupError, {
    title: `${state.startupErrorTitle} · Local Voice Desktop`,
    kind: 'error',
  });
}

function cleanupCurrentAudioUrl() {
  if (state.currentAudioUrl) {
    URL.revokeObjectURL(state.currentAudioUrl);
    state.currentAudioUrl = null;
  }
}

function currentPreparedText() {
  return stripMarkdown(els.textInput.value).trim();
}

function syncRateLabel() {
  els.rateValue.textContent = `${Number(els.rateInput.value).toFixed(2)}x`;
}

function formatTime(seconds) {
  const totalSeconds = Number.isFinite(seconds) ? Math.max(0, Math.floor(seconds)) : 0;
  const minutes = Math.floor(totalSeconds / 60);
  const remainder = totalSeconds % 60;
  return `${minutes}:${String(remainder).padStart(2, '0')}`;
}

function elapsedPlaybackTime() {
  const items = state.track?.items ?? [];
  const currentIndex = state.track?.currentIndex ?? 0;
  let elapsed = 0;
  for (let i = 0; i < currentIndex; i++) {
    elapsed += items[i]?.duration ?? 0;
  }
  elapsed += Number.isFinite(els.audio.currentTime) ? els.audio.currentTime : 0;
  return elapsed;
}

function estimateDuration(text, rate) {
  const words = text.split(/\s+/).filter(Boolean).length;
  const wpm = 150 * (rate || 1);
  return (words / wpm) * 60;
}

function syncTimeLabel() {
  const elapsed = elapsedPlaybackTime();
  const total = state.estimatedDuration || 0;
  els.timeText.textContent = `${formatTime(elapsed)} / ${formatTime(total)}`;
}

function render() {
  els.healthPill.classList.toggle('ready', state.healthPhase === 'ready');
  els.healthPill.classList.toggle('error', state.healthPhase === 'error');
  els.healthText.textContent = state.healthText;

  els.chunkProgress.textContent = `${state.activeChunk}/${state.totalChunks}`;
  els.progressFill.style.width = `${Math.max(0, Math.min(100, state.playbackPercent))}%`;
  els.loadingRow.hidden = !state.loading;
  els.loadingText.textContent = state.loadingText;

  const hasText = currentPreparedText().length > 0;
  els.resetText.hidden = !hasText;
  els.speakButton.disabled = !state.healthReady || !hasText || state.loading;
  els.pauseButton.disabled = !(state.playing || state.paused);
  els.pauseButton.textContent = state.paused ? 'Resume' : 'Pause';
  els.stopButton.disabled = !(state.playing || state.paused || state.loading);
  els.downloadButton.disabled = !hasText || state.loading;
  const hasTrack = Boolean(state.track?.items?.length);
  els.restartButton.disabled = !hasTrack || state.loading;
  els.backwardButton.disabled = !hasTrack || state.loading;
  els.forwardButton.disabled = !hasTrack || state.loading;

  const lanUrl = state.serviceInfo?.lanUrl;
  if (state.serviceInfo?.serverMode && lanUrl) {
    els.lanNote.innerHTML = `LAN API available on <code>${lanUrl}</code>. This API is unauthenticated.`;
  } else {
    const loopbackUrl = state.serviceInfo?.loopbackUrl ?? 'the configured local API address';
    els.lanNote.innerHTML = `Loopback only on <code>${loopbackUrl}</code>.`;
  }

  els.startupErrorCard.hidden = !state.startupError;
  els.startupErrorTitle.textContent = state.startupErrorTitle;
  els.startupErrorCopy.textContent = state.startupError;
  els.settingsButton.setAttribute('aria-expanded', String(state.settingsOpen));
  els.settingsOverlay.hidden = !state.settingsOpen;
  els.textField.hidden = Boolean(state.startupError);
}

async function ensureTrackBlob(index) {
  const item = state.track?.items?.[index];
  if (!item) {
    throw new Error('Playback track is unavailable.');
  }
  if (!item.blob) {
    item.blob = item.url ? await fetchChunkBlob(item.url) : item.blob;
  }
  if (!item.blob) {
    throw new Error('Audio chunk could not be loaded.');
  }
  return item.blob;
}

async function measureBlobDuration(blob) {
  const url = URL.createObjectURL(blob);
  return new Promise((resolve, reject) => {
    const probe = new Audio();
    const cleanup = () => {
      probe.removeAttribute('src');
      probe.load();
      URL.revokeObjectURL(url);
    };

    probe.addEventListener('loadedmetadata', () => {
      const duration = Number.isFinite(probe.duration) ? probe.duration : 0;
      cleanup();
      resolve(duration);
    }, { once: true });

    probe.addEventListener('error', () => {
      cleanup();
      reject(new Error('Audio metadata could not be read.'));
    }, { once: true });

    probe.src = url;
  });
}

async function ensureTrackDuration(index) {
  const item = state.track?.items?.[index];
  if (!item) {
    throw new Error('Playback track is unavailable.');
  }
  if (typeof item.duration !== 'number') {
    item.duration = await measureBlobDuration(await ensureTrackBlob(index));
  }
  return item.duration;
}

function apiBase() {
  const baseUrl = state.serviceInfo?.baseUrl;
  if (!baseUrl) {
    throw new Error('Desktop service configuration is not loaded yet.');
  }
  return baseUrl.replace(/\/+$/, '');
}

function chunkThreshold() {
  const threshold = state.serviceInfo?.chunkThreshold;
  if (typeof threshold !== 'number') {
    throw new Error('Desktop chunk threshold is not loaded yet.');
  }
  return threshold;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function fetchJson(path, options = {}) {
  const response = await fetch(`${apiBase()}${path}`, options);
  if (!response.ok) {
    throw new Error(await responseErrorMessage(response));
  }
  return response.json();
}

async function fetchBlob(path, options = {}) {
  const response = await fetch(`${apiBase()}${path}`, options);
  if (!response.ok) {
    throw new Error(await responseErrorMessage(response));
  }
  return response.blob();
}

async function fetchChunkBlob(path) {
  for (let attempt = 0; attempt < 240; attempt += 1) {
    const response = await fetch(`${apiBase()}${path}`);
    if (response.ok) {
      return response.blob();
    }
    if (response.status === 425) {
      await sleep(250);
      continue;
    }
    throw new Error(await responseErrorMessage(response));
  }

  throw new Error('Timed out while waiting for the next audio chunk.');
}

async function healthPoll() {
  try {
    const health = await fetchJson('/health');
    applyHealthState(health);
    if (state.healthReady && !state.voicesLoaded) {
      await loadVoices();
    }
  } catch (_) {
    try {
      if (invoke) {
        state.serviceInfo = await invoke('get_service_state');
      }
    } catch (_) {}
    state.healthReady = false;
    if (state.serviceInfo?.lastError) {
      state.healthPhase = 'error';
      state.healthText = 'Service failed';
      state.startupErrorTitle = 'Service startup failed';
      state.startupError = state.serviceInfo.lastError;
    } else if (state.serviceInfo?.serviceRunning) {
      state.healthPhase = 'starting';
      state.healthText = 'Starting service…';
      state.startupErrorTitle = 'Startup issue';
      state.startupError = '';
    } else {
      state.healthPhase = 'error';
      state.healthText = 'Service unavailable';
      state.startupErrorTitle = 'Startup issue';
      state.startupError = '';
    }
  } finally {
    render();
    await maybeNotifyStartupIssue();
  }
}

async function loadServiceState() {
  if (!invoke) {
    throw new Error('Tauri APIs are not available in this webview.');
  }
  state.serviceInfo = await invoke('get_service_state');
  if (state.serviceInfo?.lastError) {
    state.healthPhase = 'error';
    state.healthReady = false;
    state.healthText = 'Service failed';
    state.startupErrorTitle = 'Service startup failed';
    state.startupError = state.serviceInfo.lastError;
  } else if (state.serviceInfo?.serviceRunning) {
    state.healthPhase = 'starting';
    state.healthReady = false;
    state.healthText = 'Starting service…';
    state.startupErrorTitle = 'Startup issue';
    state.startupError = '';
  } else {
    state.startupErrorTitle = 'Startup issue';
    state.startupError = '';
  }
  render();
}

async function loadVoices() {
  const payload = await fetchJson('/voices');
  const selected = els.voiceSelect.value || loadSettings().voice;
  els.voiceSelect.innerHTML = '';
  for (const voice of payload.voices) {
    const option = document.createElement('option');
    option.value = voice.id;
    option.textContent = `${voice.label} (${voice.id})`;
    els.voiceSelect.append(option);
  }
  els.voiceSelect.value = payload.voices.some((voice) => voice.id === selected)
    ? selected
    : payload.voices[0]?.id ?? DEFAULT_SETTINGS.voice;
  state.voicesLoaded = true;
  saveSettings();
}

function updatePlaybackFromAudio() {
  if (!state.totalChunks || !els.audio.duration) {
    syncTimeLabel();
    return;
  }
  const currentIndex = state.track?.currentIndex ?? Math.max(state.activeChunk - 1, 0);
  if (state.track?.items?.[currentIndex] && Number.isFinite(els.audio.duration)) {
    state.track.items[currentIndex].duration = els.audio.duration;
  }
  const completedBeforeCurrent = Math.max(state.activeChunk - 1, 0);
  const fraction = els.audio.currentTime / els.audio.duration;
  state.playbackPercent = ((completedBeforeCurrent + fraction) / state.totalChunks) * 100;
  syncTimeLabel();
  render();
}

async function stopPlayback({ cancelServer = true } = {}) {
  state.playToken += 1;
  if (typeof state.cancelPlayback === 'function') {
    state.cancelPlayback('stopped');
    state.cancelPlayback = null;
  }

  els.audio.pause();
  els.audio.removeAttribute('src');
  els.audio.load();
  cleanupCurrentAudioUrl();

  if (cancelServer && state.lastSpeak?.jobId) {
    try {
      await fetchJson('/stop', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ job_id: state.lastSpeak.jobId }),
      });
    } catch (_) {}
  }

  state.playing = false;
  state.paused = false;
  state.playbackPercent = 0;
  state.activeChunk = state.totalChunks ? Math.min(state.activeChunk, state.totalChunks) : 0;
  state.estimatedDuration = 0;
  syncTimeLabel();
  setLoading(false);
  setStatus('Stopped');
  render();
}

async function playBlob(blob, token, { index = 0, startTime = 0 } = {}) {
  cleanupCurrentAudioUrl();
  state.currentAudioUrl = URL.createObjectURL(blob);
  els.audio.src = state.currentAudioUrl;
  els.audio.currentTime = 0;
  if (state.track) {
    state.track.currentIndex = index;
  }
  state.activeChunk = index + 1;
  render();

  return new Promise((resolve, reject) => {
    const onLoadedMetadata = () => {
      if (state.track?.items?.[index] && Number.isFinite(els.audio.duration)) {
        state.track.items[index].duration = els.audio.duration;
      }
      if (startTime > 0 && Number.isFinite(els.audio.duration)) {
        els.audio.currentTime = Math.min(startTime, els.audio.duration);
      }
      syncTimeLabel();
      render();
    };
    const onEnded = () => finalize('ended');
    const onError = () => finalize('error');

    const finalize = (result) => {
      els.audio.removeEventListener('loadedmetadata', onLoadedMetadata);
      els.audio.removeEventListener('ended', onEnded);
      els.audio.removeEventListener('error', onError);
      if (state.cancelPlayback === cancelPlayback) {
        state.cancelPlayback = null;
      }
      if (result !== 'stopped') {
        cleanupCurrentAudioUrl();
      }
      if (result === 'error') {
        reject(new Error('Audio playback failed.'));
      } else {
        resolve(result);
      }
    };

    const cancelPlayback = (result) => finalize(result);
    state.cancelPlayback = cancelPlayback;

    els.audio.addEventListener('loadedmetadata', onLoadedMetadata, { once: true });
    els.audio.addEventListener('ended', onEnded, { once: true });
    els.audio.addEventListener('error', onError, { once: true });

    els.audio.play().then(() => {
      if (token !== state.playToken) {
        finalize('stopped');
        return;
      }
      state.playing = true;
      state.paused = false;
      render();
    }).catch((error) => {
      finalize('error');
      reject(error);
    });
  });
}

async function playSingleClip(blob, token) {
  state.track = {
    items: [{ blob, duration: null }],
    currentIndex: 0,
  };
  await playTrackFrom(0, token, 0);
}

async function playChunkQueue(chunks, token) {
  state.track = {
    items: chunks.map((chunk) => ({ url: chunk.url, blob: null, duration: null })),
    currentIndex: 0,
  };
  await playTrackFrom(0, token, 0);
}

async function playTrackFrom(startIndex, token, startTime = 0) {
  const items = state.track?.items ?? [];
  state.totalChunks = items.length;
  state.playbackPercent = items.length ? (startIndex / items.length) * 100 : 0;
  render();

  for (let index = startIndex; index < items.length; index += 1) {
    if (token !== state.playToken) {
      return;
    }

    state.activeChunk = index + 1;
    if (!items[index].blob && items[index].url) {
      setLoading(true, `Fetching chunk ${index + 1} of ${items.length}…`);
    }
    render();

    const blob = await ensureTrackBlob(index);
    if (token !== state.playToken) {
      return;
    }

    setLoading(false);
    const seekTime = index === startIndex ? startTime : 0;
    const result = await playBlob(blob, token, { index, startTime: seekTime });
    if (result !== 'ended') {
      return;
    }
  }

  if (token === state.playToken) {
    state.playbackPercent = 100;
    state.playing = false;
    state.paused = false;
    setStatus('Playback complete');
    render();
  }
}

async function restartPlayback() {
  if (!state.track?.items?.length) {
    return;
  }
  setStatus('Restarting');
  const token = state.playToken + 1;
  state.playToken = token;
  if (typeof state.cancelPlayback === 'function') {
    state.cancelPlayback('stopped');
    state.cancelPlayback = null;
  }
  await playTrackFrom(0, token, 0);
}

async function seekBy(seconds) {
  if (!state.track?.items?.length) {
    return;
  }

  const currentIndex = state.track.currentIndex ?? 0;
  let currentDuration = Number.isFinite(els.audio.duration)
    ? els.audio.duration
    : await ensureTrackDuration(currentIndex);
  let targetIndex = currentIndex;
  let targetTime = (Number.isFinite(els.audio.currentTime) ? els.audio.currentTime : 0) + seconds;

  while (targetTime < 0 && targetIndex > 0) {
    targetIndex -= 1;
    currentDuration = await ensureTrackDuration(targetIndex);
    targetTime += currentDuration;
  }

  while (targetTime > currentDuration && targetIndex < state.track.items.length - 1) {
    targetTime -= currentDuration;
    targetIndex += 1;
    currentDuration = await ensureTrackDuration(targetIndex);
  }

  targetTime = Math.max(0, Math.min(currentDuration, targetTime));

  if (targetIndex === currentIndex && els.audio.src) {
    els.audio.currentTime = targetTime;
    updatePlaybackFromAudio();
    return;
  }

  setStatus(seconds < 0 ? 'Rewinding' : 'Seeking');
  const token = state.playToken + 1;
  state.playToken = token;
  if (typeof state.cancelPlayback === 'function') {
    state.cancelPlayback('stopped');
    state.cancelPlayback = null;
  }
  await playTrackFrom(targetIndex, token, targetTime);
}

async function handleSpeak() {
  const text = currentPreparedText();
  if (!text) {
    await showError('There is no readable text to synthesize.');
    return;
  }

  await stopPlayback({ cancelServer: false });

  const voice = els.voiceSelect.value || DEFAULT_SETTINGS.voice;
  const rate = Number(els.rateInput.value);
  const threshold = chunkThreshold();
  const token = state.playToken + 1;
  state.playToken = token;
  state.lastSpeak = { text, voice, rate, jobId: null };
  state.estimatedDuration = estimateDuration(text, rate);

  setLoading(true, text.length > threshold ? 'Batching audio chunks…' : 'Synthesizing…');
  setStatus('Preparing audio');
  state.playbackPercent = 0;
  state.activeChunk = 0;
  state.totalChunks = 0;
  state.track = null;
  syncTimeLabel();
  render();

  try {
    if (text.length <= threshold) {
      const blob = await fetchBlob('/synthesize', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, voice, rate, format: 'mp3' }),
      });
      if (token !== state.playToken) {
        return;
      }
      setLoading(false);
      setStatus('Playing');
      await playSingleClip(blob, token);
      return;
    }

    const streamResult = await fetchJson('/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        text,
        voice,
        rate,
        format: 'mp3',
        chunking: { strategy: 'sentence', target_chars: 500, max_chars: 1000 },
      }),
    });
    if (token !== state.playToken) {
      return;
    }
    state.lastSpeak.jobId = streamResult.job_id;
    setStatus('Playing');
    await playChunkQueue(streamResult.chunks, token);
  } catch (error) {
    setLoading(false);
    state.playing = false;
    state.paused = false;
    render();
    await showError(error.message);
  }
}

async function handlePauseResume() {
  if (state.paused) {
    await els.audio.play();
    state.paused = false;
    state.playing = true;
    setStatus('Playing');
  } else {
    els.audio.pause();
    state.paused = true;
    state.playing = false;
    setStatus('Paused');
  }
  render();
}

async function handleDownload() {
  const currentText = currentPreparedText();
  if (!currentText) {
    await showError('There is no readable text to export.');
    return;
  }

  const voice = els.voiceSelect.value || DEFAULT_SETTINGS.voice;
  const rate = Number(els.rateInput.value);
  const downloadJobId = state.lastSpeak
    && state.lastSpeak.text === currentText
    && state.lastSpeak.voice === voice
    && state.lastSpeak.rate === rate
      ? state.lastSpeak.jobId
      : null;

  setLoading(true, 'Exporting MP3…');
  setStatus('Exporting MP3');

  try {
    const blob = await fetchBlob('/export', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        job_id: downloadJobId,
        text: currentText,
        voice,
        rate,
        format: 'mp3',
        chunking: { strategy: 'sentence', target_chars: 500, max_chars: 1000 },
      }),
    });

    const buffer = await blob.arrayBuffer();
    const suggestedFilename = `local_voice_${Math.floor(Date.now() / 1000)}.mp3`;
    setLoading(false);
    setStatus('Choose save location');

    const selectedPath = await saveDialog({
      title: 'Save MP3',
      defaultPath: suggestedFilename,
      filters: [{ name: 'MP3 Audio', extensions: ['mp3'] }],
    });

    if (!selectedPath) {
      setStatus('Save cancelled');
      return;
    }

    setLoading(true, 'Saving MP3…');
    const savedPath = await invoke('write_audio_file', {
      path: selectedPath,
      data: Array.from(new Uint8Array(buffer)),
    });
    setStatus(savedPath ? 'MP3 saved' : 'Save cancelled');
  } catch (error) {
    await showError(error.message);
  } finally {
    setLoading(false);
  }
}

async function handleFile(file) {
  const raw = await file.text();
  const stripped = stripMarkdown(raw);
  els.textInput.value = stripped;
  els.fileName.textContent = `${file.name} loaded`;
  els.fileName.hidden = false;
  saveSettings();
  render();
}

async function handleFfmpegPathChange() {
  if (!invoke) {
    return;
  }

  const nextValue = els.ffmpegPath.value.trim();
  const previousValue = state.ffmpegPath.trim();
  if (nextValue === previousValue) {
    return;
  }

  setLoading(true, 'Updating ffmpeg path…');
  setStatus('Updating settings');

  try {
    state.serviceInfo = await invoke('set_ffmpeg_path', { path: nextValue || null });
    await loadDesktopSettings();
    await healthPoll();
  } catch (error) {
    els.ffmpegPath.value = state.ffmpegPath;
    await showError(error.message);
  } finally {
    setLoading(false);
    render();
  }
}

async function handleServerToggle() {
  const enable = els.serverMode.checked;
  if (enable) {
    const confirmed = await confirmDialog(
      'Server mode exposes an unauthenticated TTS API to your local network. Continue?',
      { title: 'Enable Server Mode', kind: 'warning' },
    );
    if (!confirmed) {
      els.serverMode.checked = false;
      render();
      return;
    }
  }

  try {
    state.serviceInfo = await invoke('toggle_server_mode', { enable });
    saveSettings();
    await healthPoll();
  } catch (error) {
    els.serverMode.checked = !enable;
    await showError(error.message);
  } finally {
    render();
  }
}

function bindFileDrop() {
  const target = els.textInput;

  target.addEventListener('dragover', (event) => {
    event.preventDefault();
    target.classList.add('dragover');
  });
  target.addEventListener('dragleave', () => target.classList.remove('dragover'));
  target.addEventListener('drop', async (event) => {
    event.preventDefault();
    target.classList.remove('dragover');
    const [file] = event.dataTransfer?.files ?? [];
    if (file) {
      await handleFile(file);
    }
  });
}

async function init() {
  if (tauriApi.app?.getVersion) {
    tauriApi.app.getVersion().then((v) => {
      document.getElementById('app-version').textContent = `v${v}`;
    });
  }

  const settings = loadSettings();
  els.rateInput.value = String(settings.rate);
  els.serverMode.checked = Boolean(settings.serverMode);
  syncRateLabel();
  render();

  els.audio.addEventListener('timeupdate', updatePlaybackFromAudio);
  els.uploadTrigger.addEventListener('click', () => els.fileInput.click());
  els.fileInput.addEventListener('change', async (event) => {
    const [file] = event.target.files ?? [];
    if (file) {
      await handleFile(file);
      event.target.value = '';
    }
  });
  bindFileDrop();

  els.rateInput.addEventListener('input', () => {
    syncRateLabel();
    saveSettings();
  });
  els.settingsButton.addEventListener('click', openSettings);
  els.settingsClose.addEventListener('click', closeSettings);
  els.settingsOverlay.addEventListener('click', (event) => {
    if (event.target === els.settingsOverlay) {
      closeSettings();
    }
  });
  els.voiceSelect.addEventListener('change', saveSettings);
  els.ffmpegPath.addEventListener('change', () => {
    handleFfmpegPathChange().catch((error) => showError(error.message));
  });
  els.serverMode.addEventListener('change', handleServerToggle);
  els.speakButton.addEventListener('click', handleSpeak);
  els.pauseButton.addEventListener('click', handlePauseResume);
  els.stopButton.addEventListener('click', () => stopPlayback());
  els.downloadButton.addEventListener('click', handleDownload);
  els.restartButton.addEventListener('click', () => restartPlayback().catch((error) => showError(error.message)));
  els.backwardButton.addEventListener('click', () => seekBy(-15).catch((error) => showError(error.message)));
  els.forwardButton.addEventListener('click', () => seekBy(15).catch((error) => showError(error.message)));
  els.resetText.addEventListener('click', () => {
    els.textInput.value = '';
    els.fileName.hidden = true;
    render();
  });
  els.textInput.addEventListener('input', render);
  window.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && state.settingsOpen) {
      closeSettings();
    }
  });

  try {
    await loadDesktopSettings();
    await loadServiceState();
    if (settings.serverMode && !state.serviceInfo?.serverMode) {
      state.serviceInfo = await invoke('toggle_server_mode', { enable: true });
    }
  } catch (error) {
    state.serviceInfo = { serverMode: false, lastError: error.message };
  }

  await healthPoll();
  syncTimeLabel();
  setInterval(() => {
    healthPoll().catch(() => {});
  }, 3000);
  render();
}

init().catch((error) => {
  showError(error.message);
});

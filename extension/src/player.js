const MSG = {
  PLAYER_PLAY: 'PLAYER_PLAY',
  PLAYER_ENQUEUE: 'PLAYER_ENQUEUE',
  PLAYER_STREAM_DONE: 'PLAYER_STREAM_DONE',
  PLAYER_STOP: 'PLAYER_STOP',
  PLAYER_PAUSE: 'PLAYER_PAUSE',
  PLAYER_RESUME: 'PLAYER_RESUME',
  PLAYER_GET_STATE: 'PLAYER_GET_STATE',
  PLAYER_STARTED: 'PLAYER_STARTED',
  PLAYER_PROGRESS: 'PLAYER_PROGRESS',
  PLAYER_ENDED: 'PLAYER_ENDED',
  PLAYER_ERROR: 'PLAYER_ERROR',
};

let audio = new Audio();
let queue = [];
let currentIndex = 0;
let stopped = false;
let playbackVersion = 0;
let streamComplete = false;
let waitingForMore = false;

function getPlaybackState() {
  const active = !stopped && (Boolean(audio.src) || waitingForMore);
  return {
    active,
    paused: active && !waitingForMore ? audio.paused : false,
    waitingForChunk: waitingForMore,
    queueLength: queue.length,
    currentIndex,
    chunksDone: active ? currentIndex + (audio.ended || waitingForMore ? 0 : 1) : 0,
  };
}

function notify(type, extra = {}) {
  chrome.runtime.sendMessage({ type, ...extra }).catch(() => {});
}

function playNext(version = playbackVersion) {
  if (version !== playbackVersion) return;
  if (stopped) return;

  if (currentIndex >= queue.length) {
    if (streamComplete) {
      waitingForMore = false;
      notify(MSG.PLAYER_ENDED);
      queue = [];
      currentIndex = 0;
      return;
    }
    waitingForMore = true;
    return;
  }

  waitingForMore = false;
  audio.src = queue[currentIndex];
  const source = audio.src;
  audio.play().then(() => {
    if (version !== playbackVersion || stopped || audio.src !== source) return;
    if (currentIndex === 0) notify(MSG.PLAYER_STARTED);
    notify(MSG.PLAYER_PROGRESS, { chunksDone: currentIndex + 1 });
  }).catch(err => {
    if (version !== playbackVersion || stopped) return;
    console.error('Playback error:', err);
    notify(MSG.PLAYER_ERROR, { error: err.message });
  });
}

audio.addEventListener('ended', () => {
  if (stopped) return;
  URL.revokeObjectURL(audio.src);
  currentIndex++;
  playNext(playbackVersion);
});

audio.addEventListener('error', () => {
  if (stopped || !audio.src || currentIndex >= queue.length) return;
  notify(MSG.PLAYER_ERROR, { error: 'Audio playback failed' });
});

function stopAll() {
  playbackVersion += 1;
  stopped = true;
  streamComplete = false;
  waitingForMore = false;
  audio.pause();
  audio.src = '';
  for (const url of queue) {
    try { URL.revokeObjectURL(url); } catch (_) {}
  }
  queue = [];
  currentIndex = 0;
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  switch (msg.type) {
    case MSG.PLAYER_PLAY:
      stopAll();
      stopped = false;
      streamComplete = !msg.streaming;
      if (msg.single) {
        queue = [msg.dataUrl];
      } else if (msg.dataUrl) {
        queue = [msg.dataUrl];
      } else {
        queue = msg.dataUrls || [];
      }
      currentIndex = 0;
      playNext(playbackVersion);
      break;

    case MSG.PLAYER_ENQUEUE:
      if (!stopped && msg.dataUrl) {
        queue.push(msg.dataUrl);
        if (waitingForMore) {
          playNext(playbackVersion);
        }
      }
      break;

    case MSG.PLAYER_STREAM_DONE:
      streamComplete = true;
      if (waitingForMore && currentIndex >= queue.length) {
        waitingForMore = false;
        notify(MSG.PLAYER_ENDED);
        queue = [];
        currentIndex = 0;
      }
      break;

    case MSG.PLAYER_STOP:
      stopAll();
      break;

    case MSG.PLAYER_PAUSE:
      audio.pause();
      break;

    case MSG.PLAYER_RESUME:
      audio.play().catch(() => {});
      break;

    case MSG.PLAYER_GET_STATE:
      sendResponse({ player: getPlaybackState() });
      return false;
  }
});

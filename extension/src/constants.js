export const DEFAULT_SETTINGS = {
  serverUrl: 'http://127.0.0.1:5517',
  engine: 'kokoro',
  voice: 'af_bella',
  rate: 1.0,
  format: 'mp3',
  mode: 'selection',
  autoplay: true,
  targetChunkChars: 500,
  maxChunkChars: 1000,
  healthcheckOnStart: true,
  fallbackToBrowserTTS: false,
  debug: false,
};

export const JOB_STATUS = {
  IDLE: 'idle',
  QUEUED: 'queued',
  SYNTHESIZING: 'synthesizing',
  PLAYING: 'playing',
  PAUSED: 'paused',
  ERROR: 'error',
};

export const MSG = {
  READ_SELECTION: 'READ_SELECTION',
  GET_SELECTION: 'GET_SELECTION',
  SPEAK: 'SPEAK',
  STOP: 'STOP',
  PAUSE: 'PAUSE',
  RESUME: 'RESUME',
  GET_STATE: 'GET_STATE',
  STATE_CHANGED: 'STATE_CHANGED',
  PLAYER_STARTED: 'PLAYER_STARTED',
  PLAYER_PROGRESS: 'PLAYER_PROGRESS',
  PLAYER_ENDED: 'PLAYER_ENDED',
  PLAYER_ERROR: 'PLAYER_ERROR',
  PLAYER_PLAY: 'PLAYER_PLAY',
  PLAYER_ENQUEUE: 'PLAYER_ENQUEUE',
  PLAYER_STREAM_DONE: 'PLAYER_STREAM_DONE',
  PLAYER_STOP: 'PLAYER_STOP',
  PLAYER_PAUSE: 'PLAYER_PAUSE',
  PLAYER_RESUME: 'PLAYER_RESUME',
  PLAYER_GET_STATE: 'PLAYER_GET_STATE',
};

export const CHUNK_THRESHOLD = 800;

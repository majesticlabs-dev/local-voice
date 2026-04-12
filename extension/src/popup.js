import { LocalTTSClient } from './api.js';
import { loadSettings, setSetting } from './store.js';
import { MSG, JOB_STATUS } from './constants.js';

const $ = (s) => document.querySelector(s);

let settings;
let api;
let serviceReady = false;
let currentJob = {
  status: JOB_STATUS.IDLE,
  chunksTotal: 0,
  chunksDone: 0,
  errorMessage: '',
};

function syncTransportButtons() {
  const btnSpeak = $('#btn-speak');
  const btnPause = $('#btn-pause');
  const btnStop = $('#btn-stop');
  const active = [JOB_STATUS.SYNTHESIZING, JOB_STATUS.PLAYING, JOB_STATUS.PAUSED].includes(currentJob.status);

  btnSpeak.style.display = active ? 'none' : 'flex';
  btnSpeak.disabled = !serviceReady;
  btnPause.disabled = !active;
  btnStop.disabled = !active;
}

async function init() {
  settings = await loadSettings();
  api = new LocalTTSClient(settings.serverUrl);

  $('#rate-slider').value = settings.rate;
  $('#rate-value').textContent = `${settings.rate}x`;
  $('#mode-select').value = settings.mode;

  $('#version').textContent = `v${chrome.runtime.getManifest().version}`;

  checkHealth()
    .then((ready) => {
      if (ready) return loadVoices();
      $('#voice-select').innerHTML = '<option value="">Open app first</option>';
      return null;
    })
    .catch(() => {
      $('#voice-select').innerHTML = '<option value="">Open app first</option>';
    });

  chrome.runtime.sendMessage({ type: MSG.GET_STATE }, (res) => {
    if (chrome.runtime.lastError) return;
    if (res && res.job) updateUI(res.job);
  });
}

async function checkHealth() {
  const dot = $('#health-dot');
  const label = $('#health-label');
  try {
    const data = await api.health();
    const engineLabel = data.engine || 'Local Voice';
    serviceReady = Boolean(data.ready);
    dot.className = serviceReady ? 'health-dot ok' : 'health-dot unknown';
    label.textContent = serviceReady ? engineLabel : `${engineLabel} warming`;
  } catch (_) {
    serviceReady = false;
    dot.className = 'health-dot error';
    label.textContent = 'Open app';
  }
  syncTransportButtons();
  return serviceReady;
}

async function loadVoices() {
  const select = $('#voice-select');
  try {
    const data = await api.voices();
    select.innerHTML = '';
    for (const v of data.voices) {
      const opt = document.createElement('option');
      opt.value = v.id;
      opt.textContent = v.label;
      select.appendChild(opt);
    }
    select.value = settings.voice;
  } catch (_) {
    select.innerHTML = '<option value="">Open app first</option>';
  }
}

function updateUI(job) {
  currentJob = {
    ...currentJob,
    ...job,
  };
  const statusText = $('#status-text');
  const progress = $('#progress');
  const btnPause = $('#btn-pause');

  const labels = {
    [JOB_STATUS.IDLE]: 'Ready',
    [JOB_STATUS.QUEUED]: 'Queued...',
    [JOB_STATUS.SYNTHESIZING]: 'Synthesizing...',
    [JOB_STATUS.PLAYING]: 'Playing',
    [JOB_STATUS.PAUSED]: 'Paused',
    [JOB_STATUS.ERROR]: job.errorMessage || 'No readable text found',
  };

  statusText.textContent = labels[job.status] || 'Ready';
  statusText.title = job.errorMessage || '';
  statusText.className = '';
  if ([JOB_STATUS.SYNTHESIZING, JOB_STATUS.PLAYING].includes(job.status)) {
    statusText.classList.add('active');
  } else if (job.status === JOB_STATUS.ERROR) {
    statusText.classList.add('error');
  }

  if (job.chunksTotal > 1) {
    progress.textContent = `${job.chunksDone}/${job.chunksTotal}`;
  } else {
    progress.textContent = '';
  }

  syncTransportButtons();

  if (job.status === JOB_STATUS.PAUSED) {
    btnPause.innerHTML = '&#9654;';
    btnPause.title = 'Resume';
    btnPause.classList.add('btn-primary', 'resuming');
    btnPause.classList.remove('btn-secondary');
  } else {
    btnPause.innerHTML = '&#10074;&#10074;';
    btnPause.title = 'Pause';
    btnPause.classList.add('btn-secondary');
    btnPause.classList.remove('btn-primary', 'resuming');
  }
}

$('#btn-speak').addEventListener('click', async () => {
  const ready = await checkHealth();
  if (!ready) {
    const healthLabel = $('#health-label').textContent || 'Open app';
    $('#status-text').textContent = /warming/i.test(healthLabel)
      ? 'Local Voice is warming up'
      : 'Open Local Voice app';
    $('#status-text').className = 'error';
    return;
  }

  $('#status-text').textContent = 'Getting text...';
  $('#status-text').className = 'active';
  chrome.runtime.sendMessage({ type: MSG.SPEAK }, () => {
    if (chrome.runtime.lastError) {
      $('#status-text').textContent = 'Extension error';
      $('#status-text').className = 'error';
    }
  });
});

$('#btn-pause').addEventListener('click', () => {
  chrome.runtime.sendMessage({ type: MSG.GET_STATE }, (res) => {
    if (chrome.runtime.lastError) return;
    if (res?.job?.status === JOB_STATUS.PAUSED) {
      chrome.runtime.sendMessage({ type: MSG.RESUME }).catch(() => {});
    } else {
      chrome.runtime.sendMessage({ type: MSG.PAUSE }).catch(() => {});
    }
  });
});

$('#btn-stop').addEventListener('click', () => {
  chrome.runtime.sendMessage({ type: MSG.STOP }).catch(() => {});
});

$('#voice-select').addEventListener('change', async (e) => {
  settings = await setSetting('voice', e.target.value);
});

$('#rate-slider').addEventListener('input', async (e) => {
  const val = parseFloat(e.target.value);
  $('#rate-value').textContent = `${val}x`;
  settings = await setSetting('rate', val);
});

$('#mode-select').addEventListener('change', async (e) => {
  settings = await setSetting('mode', e.target.value);
});

chrome.runtime.onMessage.addListener((msg) => {
  if (msg.type === MSG.STATE_CHANGED && msg.job) {
    updateUI(msg.job);
    if (msg.job.status === JOB_STATUS.ERROR) {
      checkHealth().catch(() => {});
    }
  }
});

init();

import { LocalTTSClient } from './api.js';
import { loadSettings } from './store.js';
import { JOB_STATUS, MSG, CHUNK_THRESHOLD } from './constants.js';

const JOB_STORAGE_KEY = 'activeJob';
const SERVICE_HEALTH_ALARM = 'service-health-check';
const SERVICE_HEALTH_POLL_MINUTES = 1;
const APP_UNAVAILABLE_STATUS = 'Open Local Voice app';
const APP_UNAVAILABLE_MESSAGE = 'Open the Local Voice application so its local service starts, then try again.';
const APP_UNAVAILABLE_NOTIFICATION_ID = 'local-voice-app-unavailable';
const PLAYER_READY_RETRIES = 30;
const PLAYER_READY_DELAY_MS = 100;

let api = null;
let playbackGeneration = 0;
const DEFAULT_JOB = {
  id: null,
  status: JOB_STATUS.IDLE,
  source: null,
  textLength: 0,
  chunksTotal: 0,
  chunksDone: 0,
  startedAt: null,
  voice: null,
  rate: null,
  format: null,
  errorMessage: '',
};
let job = { ...DEFAULT_JOB };

async function getApi() {
  if (!api) {
    const settings = await loadSettings();
    api = new LocalTTSClient(settings.serverUrl);
  }
  return api;
}

function getJobStore() {
  return chrome.storage.session || chrome.storage.local;
}

async function loadPersistedJob() {
  const result = await getJobStore().get(JOB_STORAGE_KEY);
  if (!result?.[JOB_STORAGE_KEY]) return { ...DEFAULT_JOB };
  return { ...DEFAULT_JOB, ...result[JOB_STORAGE_KEY] };
}

async function persistJob(snapshot) {
  await getJobStore().set({ [JOB_STORAGE_KEY]: snapshot });
}

async function queryPlayerState() {
  try {
    const response = await chrome.runtime.sendMessage({ type: MSG.PLAYER_GET_STATE });
    return response?.player || null;
  } catch (_) {
    return null;
  }
}

function reconcileJobState(baseJob, playerState) {
  const nextJob = { ...DEFAULT_JOB, ...baseJob };

  if (!playerState?.active) {
    if ([
      JOB_STATUS.QUEUED,
      JOB_STATUS.SYNTHESIZING,
      JOB_STATUS.PLAYING,
      JOB_STATUS.PAUSED,
    ].includes(nextJob.status)) {
      nextJob.status = JOB_STATUS.IDLE;
      nextJob.id = null;
      nextJob.chunksDone = 0;
      nextJob.chunksTotal = 0;
    }
    return nextJob;
  }

  if (playerState.waitingForChunk) {
    nextJob.status = JOB_STATUS.SYNTHESIZING;
  } else {
    nextJob.status = playerState.paused ? JOB_STATUS.PAUSED : JOB_STATUS.PLAYING;
  }
  nextJob.chunksTotal = Math.max(nextJob.chunksTotal || 0, playerState.queueLength || 0);
  nextJob.chunksDone = Math.max(nextJob.chunksDone || 0, playerState.chunksDone || 0);
  return nextJob;
}

function updateJob(patch) {
  const nextPatch = { ...patch };
  if (nextPatch.status && nextPatch.status !== JOB_STATUS.ERROR && !('errorMessage' in nextPatch)) {
    nextPatch.errorMessage = '';
  }
  Object.assign(job, nextPatch);
  persistJob({ ...job }).catch(() => {});
  chrome.runtime.sendMessage({ type: MSG.STATE_CHANGED, job: { ...job } }).catch(() => {});
  if ('status' in nextPatch) syncBadge(nextPatch.status);
}

function setJobError(errorMessage) {
  updateJob({ status: JOB_STATUS.ERROR, errorMessage });
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function errorMessageOf(error) {
  if (error instanceof Error) return error.message;
  return `${error ?? ''}`;
}

function isMissingReceiverError(error) {
  return /Could not establish connection|Receiving end does not exist/i.test(errorMessageOf(error));
}

function isLocalServiceUnavailableError(error) {
  return /Failed to fetch|Load failed|NetworkError|Network request failed/i.test(errorMessageOf(error));
}

async function notifyAppUnavailable() {
  try {
    await chrome.notifications.clear(APP_UNAVAILABLE_NOTIFICATION_ID);
    await chrome.notifications.create(APP_UNAVAILABLE_NOTIFICATION_ID, {
      type: 'basic',
      iconUrl: 'icons/128.png',
      title: 'Local Voice is not running',
      message: APP_UNAVAILABLE_MESSAGE,
      priority: 2,
    });
  } catch (_) {}
}

async function ensurePlayerReady() {
  await ensureOffscreen();

  for (let attempt = 0; attempt < PLAYER_READY_RETRIES; attempt += 1) {
    try {
      const response = await chrome.runtime.sendMessage({ type: MSG.PLAYER_GET_STATE });
      if (response?.player) return;
    } catch (error) {
      if (!isMissingReceiverError(error)) throw error;
    }
    await delay(PLAYER_READY_DELAY_MS);
  }

  throw new Error('Local audio player is unavailable.');
}

async function sendPlayerMessage(message) {
  await ensurePlayerReady();
  try {
    await chrome.runtime.sendMessage(message);
  } catch (error) {
    if (!isMissingReceiverError(error)) throw error;
    await delay(PLAYER_READY_DELAY_MS);
    await ensurePlayerReady();
    await chrome.runtime.sendMessage(message);
  }
}

async function ensureOffscreen() {
  const contexts = await chrome.runtime.getContexts({
    contextTypes: ['OFFSCREEN_DOCUMENT'],
  });
  if (contexts.length) return;
  await chrome.offscreen.createDocument({
    url: 'src/player.html',
    reasons: ['AUDIO_PLAYBACK'],
    justification: 'Playing TTS audio',
  });
}

async function setActionIndicator(available, engine = '') {
  const title = available
    ? `Local Voice Reader: ${engine || 'service ready'}`
    : 'Local Voice Reader: open the Local Voice app';

  try {
    await chrome.action.setTitle({ title });
  } catch (_) {}
}

async function syncBadge(status) {
  const active = [JOB_STATUS.SYNTHESIZING, JOB_STATUS.PLAYING, JOB_STATUS.PAUSED].includes(status);
  try {
    await chrome.action.setBadgeBackgroundColor({ color: '#34c759' });
    await chrome.action.setBadgeText({ text: active ? 'ON' : '' });
  } catch (_) {}
}

async function updateServiceIndicator() {
  try {
    const client = await getApi();
    const health = await client.health();
    const engineLabel = health?.ready
      ? (health?.engine || 'service ready')
      : `${health?.engine || 'service'} warming`;
    await setActionIndicator(true, engineLabel);
  } catch (_) {
    await setActionIndicator(false);
  }
}

function ensureServiceHealthAlarm() {
  chrome.alarms.create(SERVICE_HEALTH_ALARM, {
    periodInMinutes: SERVICE_HEALTH_POLL_MINUTES,
  });
}

async function requestTabExtraction(tabId, mode, timeoutMs = 2000) {
  try {
    const response = await Promise.race([
      chrome.tabs.sendMessage(tabId, { type: MSG.GET_SELECTION, mode }),
      new Promise((_, reject) => setTimeout(() => reject(new Error('timeout')), timeoutMs)),
    ]);
    if (response?.text) return response;
  } catch (_) {}

  return null;
}

async function ensureTabContentScript(tabId) {
  try {
    const results = await chrome.scripting.executeScript({
      target: { tabId },
      func: () => Boolean(globalThis.__LOCAL_VOICE_CONTENT_SCRIPT_READY__),
    });
    if (results?.[0]?.result) return true;

    await chrome.scripting.executeScript({
      target: { tabId },
      files: ['src/content.js'],
    });
    return true;
  } catch (_) {
    return false;
  }
}

async function getExtractionFromTab(tabId, mode) {
  const directExtraction = await requestTabExtraction(tabId, mode);
  if (directExtraction) return directExtraction;

  if (await ensureTabContentScript(tabId)) {
    const retriedExtraction = await requestTabExtraction(tabId, mode, 750);
    if (retriedExtraction) return retriedExtraction;
  }

  try {
    const results = await chrome.scripting.executeScript({
      target: { tabId },
      func: (m) => {
        const normalizeWhitespace = (text, preserveParagraphs = true) => {
          let normalized = `${text ?? ''}`
            .replace(/\u00A0/g, ' ')
            .replace(/\u200B/g, '')
            .replace(/\r\n/g, '\n')
            .replace(/\r/g, '\n');
          normalized = normalized.replace(/[ \t]+\n/g, '\n').replace(/\n[ \t]+/g, '\n');
          if (preserveParagraphs) {
            normalized = normalized.replace(/[ \t]{2,}/g, ' ');
            normalized = normalized.replace(/\n{3,}/g, '\n\n');
          } else {
            normalized = normalized.replace(/\s+/g, ' ');
          }
          return normalized.trim();
        };
        const stripLine = (text) => normalizeWhitespace(text, false);
        const stripSpeechArtifacts = (text, preserveParagraphs = true) => {
          let normalized = normalizeWhitespace(text, preserveParagraphs);
          normalized = normalized.replace(/^[ \t]*Show more[ \t]*$/gim, '');
          normalized = normalized.replace(/^[ \t]*Translate post[ \t]*$/gim, '');
          normalized = normalized.replace(/^[ \t]*Who can reply\?[ \t]*$/gim, '');
          normalized = normalized.replace(/^[ \t]*To view keyboard shortcuts,? press .+$/gim, '');
          normalized = normalized.replace(/https?:\/\/\S+/gi, '');
          normalized = normalized.replace(/www\.\S+/gi, '');
          normalized = normalized.replace(/\n{3,}/g, '\n\n');
          return normalized.trim();
        };
        const dedupeAdjacentLines = (lines) => {
          const deduped = [];
          for (const line of lines) {
            if (!line) continue;
            if (deduped[deduped.length - 1] === line) continue;
            deduped.push(line);
          }
          return deduped;
        };
        const pruneNode = (root, selector) => {
          root.querySelectorAll(selector).forEach((node) => node.remove());
        };
        const normalizeLines = (text) => dedupeAdjacentLines(
          normalizeWhitespace(text || '', true)
            .split('\n')
            .map(stripLine)
            .filter(Boolean),
        );
        const isLikelyParagraph = (line) => line.length >= 70 || /[.!?]["')\]]?$/.test(line);
        const isXHost = [
          'x.com',
          'www.x.com',
          'mobile.x.com',
          'twitter.com',
          'www.twitter.com',
          'mobile.twitter.com',
        ].includes(location.hostname);
        const isXArticlePath = /\/article(?:s)?\//.test(location.pathname);
        const isXStatusPath = /\/status\/\d+/.test(location.pathname);
        const getXPrimaryColumn = () => document.querySelector('[data-testid="primaryColumn"]')
          || document.querySelector('[role="main"]')
          || document.querySelector('main');

        const sel = window.getSelection();
        if (sel && sel.toString().trim()) {
          return {
            sourceType: 'selection',
            text: sel.toString().trim(),
            title: document.title || '',
            url: location.href,
          };
        }
        if (m === 'article') {
          const host = location.hostname;
          const bodyText = document.body?.innerText || '';

          if (isXHost) {
            const extractXArticle = () => {
              const body = document.querySelector('[data-testid="twitterArticleRichTextView"]');
              if (!body) return null;

              const clone = body.cloneNode(true);
              pruneNode(clone, [
                '[data-testid="sidebarColumn"]',
                '[data-testid="simpleTweet"]',
                '[data-testid="placementTracking"]',
                '[data-testid="tweetButtonInline"]',
                '[data-testid="tweetButton"]',
                '[data-testid="bookmark"]',
                '[data-testid="like"]',
                '[data-testid="retweet"]',
                '[data-testid="reply"]',
                '[data-testid="share"]',
                '[data-testid="caret"]',
                '[data-testid="HelpButton"]',
                '[data-testid="keyboardShortcutsDialog"]',
                '[data-testid="card.wrapper"]',
                '[data-testid="UserCell"]',
                'button',
                '[role="group"]',
              ].join(', '));

              const title = stripSpeechArtifacts(
                document.querySelector('[data-testid="twitter-article-title"]')?.textContent || '',
                false,
              );
              const articleText = stripSpeechArtifacts(clone.innerText || clone.textContent || '', true);
              const text = [title, articleText].filter(Boolean).join('\n\n').trim();
              if (text.length < 200) return null;

              return {
                sourceType: 'article',
                text,
                title: document.title || '',
                url: location.href,
              };
            };

            const extractXPost = () => {
              if (!isXStatusPath) return null;

              const primaryColumn = getXPrimaryColumn();
              const post = primaryColumn?.querySelector('article[data-testid="tweet"][tabindex="-1"]')
                || primaryColumn?.querySelector('article[data-testid="tweet"]');
              if (!post) return null;

              const textNodes = Array.from(post.querySelectorAll('[data-testid="tweetText"]'))
                .map((node) => stripSpeechArtifacts(node.innerText || '', true))
                .filter(Boolean);
              if (!textNodes.length) return null;

              const [mainText, ...quotedTexts] = textNodes;
              let text = mainText;
              if (quotedTexts.length) {
                text += `\n\nQuoted post:\n${quotedTexts.join('\n\n')}`;
              }

              return {
                sourceType: isXArticlePath ? 'x-article' : 'x-post',
                text: stripSpeechArtifacts(text, true),
                title: document.title || '',
                url: location.href,
              };
            };

            return extractXArticle() || extractXPost();
          }

          if (host === 'nfx.com' || host === 'www.nfx.com') {
            const skipLines = new Set([
              'Content',
              'Team',
              'Companies',
              'About',
              'Products',
              'Jobs',
              'News',
              'Signal',
              'Brieflink',
              'BriefLink',
              'NFX Masterclass',
              'Privacy Policy',
              'Terms',
              'Contact',
              'Subscribe',
              'Add your email',
              'Related Content',
              'Table of Contents',
            ]);
            const endPatterns = [
              /^Subscribe for more /i,
              /^As Founders ourselves,/i,
              /^Related Content$/i,
              /^Privacy Policy$/i,
              /^©\d{4}/,
            ];
            const looksLikeMetadata = (line) => /@[a-z0-9_]+/i.test(line)
              || /\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b/i.test(line)
              || /^AI$/i.test(line);
            const title = stripLine(
              document.querySelector('h1')?.textContent
                || document.title.replace(/\s*\|\s*NFX.*$/, ''),
            );
            const roots = [
              document.querySelector('article')?.innerText || '',
              document.querySelector('main')?.innerText || '',
              bodyText,
            ].filter(Boolean);

            let bestLines = null;
            let bestScore = Number.NEGATIVE_INFINITY;
            for (const rootText of roots) {
              const lines = normalizeLines(rootText);
              if (!lines.length) continue;

              const titleIndex = title ? lines.findIndex((line) => line === title) : -1;
              const startIndex = titleIndex >= 0 ? titleIndex : 0;
              let proseChars = 0;
              let paragraphCount = 0;

              for (let index = startIndex; index < lines.length; index += 1) {
                const line = lines[index];
                if (!line) continue;
                if (endPatterns.some((pattern) => pattern.test(line))) break;
                if (line.includes('from NFX')) continue;
                if (skipLines.has(line)) continue;
                if (looksLikeMetadata(line)) continue;
                if (!isLikelyParagraph(line)) continue;

                proseChars += line.length;
                paragraphCount += 1;
              }

              let score = proseChars + (paragraphCount * 260);
              if (titleIndex >= 0) score += 400;
              if (paragraphCount < 3) score -= 3000;

              if (score > bestScore) {
                bestScore = score;
                bestLines = lines;
              }
            }

            if (bestLines?.length) {
              const titleIndex = title ? bestLines.findIndex((line) => line === title) : -1;
              const startIndex = titleIndex >= 0 ? titleIndex : 0;
              const body = [];
              let bodyStarted = false;
              let skippingToc = false;

              for (let index = startIndex; index < bestLines.length; index += 1) {
                const line = bestLines[index];
                if (!line) continue;
                if (index > startIndex && endPatterns.some((pattern) => pattern.test(line))) break;
                if (line.includes('from NFX')) continue;

                if (skipLines.has(line)) {
                  if (line === 'Table of Contents') skippingToc = true;
                  continue;
                }

                if (index === startIndex && title) {
                  body.push(title);
                  continue;
                }

                if (!bodyStarted) {
                  if (skippingToc) {
                    if (!isLikelyParagraph(line) && !/^#+\s*/.test(line)) continue;
                    skippingToc = false;
                  }

                  if (looksLikeMetadata(line)) continue;
                  if (!isLikelyParagraph(line) && !/^#+\s*/.test(line)) continue;
                  bodyStarted = true;
                }

                body.push(line);
              }

              const text = dedupeAdjacentLines(body)
                .filter((line) => line && !line.includes('from NFX'))
                .join('\n\n')
                .trim();

              if (text.length >= 200) {
                return {
                  sourceType: 'article',
                  text,
                  title: document.title || '',
                  url: location.href,
                };
              }
            }
          }

          const candidates = [
            document.querySelector('article')?.innerText || '',
            document.querySelector('[role="main"]')?.innerText || '',
            document.querySelector('main')?.innerText || '',
            bodyText,
          ]
            .map((text) => normalizeWhitespace(text, true))
            .filter((text) => text.length >= 200)
            .sort((left, right) => right.length - left.length);

          if (candidates.length) {
            return {
              sourceType: 'article',
              text: candidates[0],
              title: document.title || '',
              url: location.href,
            };
          }
        }
        return null;
      },
      args: [mode],
    });
    if (results?.[0]?.result) return results[0].result;
  } catch (e) {
    console.warn('executeScript failed:', e);
  }

  return null;
}

async function speak(extraction, tabId) {
  await stopPlayback({ bumpGeneration: false });
  const generation = ++playbackGeneration;

  const text = typeof extraction === 'string' ? extraction : extraction?.text;
  if (!text) {
    setJobError('No readable text found');
    return;
  }

  const settings = await loadSettings();
  api = new LocalTTSClient(settings.serverUrl);

  const sessionId = crypto.randomUUID();
  updateJob({
    id: sessionId,
    status: JOB_STATUS.SYNTHESIZING,
    source: extraction?.sourceType || 'tab',
    textLength: text.length,
    startedAt: Date.now(),
    voice: settings.voice,
    rate: settings.rate,
    format: settings.format,
    chunksTotal: 0,
    chunksDone: 0,
    errorMessage: '',
  });

  try {
    if (text.length <= CHUNK_THRESHOLD) {
      const blob = await api.synthesize({
        text,
        voice: settings.voice,
        rate: settings.rate,
        format: settings.format,
        sessionId,
      });
      if (generation !== playbackGeneration) return;

      const reader = new FileReader();
      const dataUrl = await new Promise((resolve, reject) => {
        reader.onload = () => resolve(reader.result);
        reader.onerror = reject;
        reader.readAsDataURL(blob);
      });
      if (generation !== playbackGeneration) return;

      updateJob({ chunksTotal: 1 });
      await sendPlayerMessage({ type: MSG.PLAYER_PLAY, dataUrl, single: true });
    } else {
      const result = await api.stream({
        text,
        voice: settings.voice,
        rate: settings.rate,
        format: settings.format,
        chunking: {
          strategy: 'sentence',
          target_chars: settings.targetChunkChars,
          max_chars: settings.maxChunkChars,
        },
        sessionId,
      });
      if (generation !== playbackGeneration) return;

      updateJob({ id: result.job_id || sessionId, chunksTotal: result.chunks.length });

      const chunkUrls = result.chunks.map(c => c.url);
      for (let i = 0; i < chunkUrls.length; i++) {
        if (generation !== playbackGeneration) return;

        const blob = await api.fetchChunk(chunkUrls[i]);
        if (generation !== playbackGeneration) return;

        const dataUrl = await new Promise((resolve, reject) => {
          const reader = new FileReader();
          reader.onload = () => resolve(reader.result);
          reader.onerror = reject;
          reader.readAsDataURL(blob);
        });
        if (generation !== playbackGeneration) return;

        if (i === 0) {
          await sendPlayerMessage({ type: MSG.PLAYER_PLAY, dataUrl, streaming: true });
        } else {
          await sendPlayerMessage({ type: MSG.PLAYER_ENQUEUE, dataUrl });
        }
      }

      if (generation !== playbackGeneration) return;
      await sendPlayerMessage({ type: MSG.PLAYER_STREAM_DONE });
    }
  } catch (err) {
    if (generation !== playbackGeneration) return;

    console.error('Speak error:', err);
    if (isLocalServiceUnavailableError(err)) {
      setJobError(APP_UNAVAILABLE_STATUS);
      updateServiceIndicator().catch(() => {});
      notifyAppUnavailable().catch(() => {});
      return;
    }
    setJobError('Playback failed');
  }
}

async function stopPlayback({ bumpGeneration = true } = {}) {
  if (bumpGeneration) playbackGeneration += 1;

  chrome.runtime.sendMessage({ type: MSG.PLAYER_STOP }).catch(() => {});
  const currentJob = job.id ? { ...job } : await loadPersistedJob();
  if (currentJob.id && currentJob.status !== JOB_STATUS.IDLE) {
    try {
      const client = await getApi();
      await client.stop(currentJob.id);
    } catch (_) {}
  }
  updateJob({
    status: JOB_STATUS.IDLE,
    id: null,
    chunksDone: 0,
    chunksTotal: 0,
  });
}

async function getCurrentJobState() {
  const persisted = await loadPersistedJob();
  const playerState = await queryPlayerState();
  job = reconcileJobState(persisted, playerState);
  await persistJob({ ...job }).catch(() => {});
  updateServiceIndicator().catch(() => {});
  return { ...job };
}

// Context menu
chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: 'speak-selection',
    title: 'Read aloud with Local Voice',
    contexts: ['selection'],
  });
  ensureServiceHealthAlarm();
  updateServiceIndicator().catch(() => {});
});

chrome.runtime.onStartup.addListener(() => {
  ensureServiceHealthAlarm();
  updateServiceIndicator().catch(() => {});
});

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === SERVICE_HEALTH_ALARM) {
    updateServiceIndicator().catch(() => {});
  }
});

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId === 'speak-selection') {
    const text = info.selectionText;
    if (text) await speak({ sourceType: 'selection', text }, tab.id);
  }
});

// Keyboard commands
chrome.commands.onCommand.addListener(async (command) => {
  if (command === 'speak-selection') {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab) return;
    const settings = await loadSettings();
    const extraction = await getExtractionFromTab(tab.id, settings.mode);
    if (extraction?.text) await speak(extraction, tab.id);
  } else if (command === 'stop-speaking') {
    await stopPlayback();
  }
});

// Message handler
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  switch (msg.type) {
    case MSG.SPEAK:
      (async () => {
        try {
          const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
          if (msg.text) {
            await speak({ sourceType: 'selection', text: msg.text }, tab?.id);
          } else if (tab) {
            const settings = await loadSettings();
            const extraction = await getExtractionFromTab(tab.id, settings.mode);
            if (extraction?.text) {
              await speak(extraction, tab.id);
            } else {
              setJobError('No readable text found');
            }
          } else {
            setJobError('No readable text found');
          }
          sendResponse({ ok: true });
        } catch (err) {
          console.error('SPEAK handler error:', err);
          if (isLocalServiceUnavailableError(err)) {
            setJobError(APP_UNAVAILABLE_STATUS);
            notifyAppUnavailable().catch(() => {});
          } else {
            setJobError('Playback failed');
          }
          sendResponse({ ok: false, error: err.message });
        }
      })();
      return true;

    case MSG.STOP:
      stopPlayback().then(() => sendResponse({ ok: true }));
      return true;

    case MSG.PAUSE:
      chrome.runtime.sendMessage({ type: MSG.PLAYER_PAUSE }).catch(() => {});
      updateJob({ status: JOB_STATUS.PAUSED });
      sendResponse({ ok: true });
      return false;

    case MSG.RESUME:
      chrome.runtime.sendMessage({ type: MSG.PLAYER_RESUME }).catch(() => {});
      updateJob({ status: JOB_STATUS.PLAYING });
      sendResponse({ ok: true });
      return false;

    case MSG.GET_STATE:
      getCurrentJobState().then((currentJob) => sendResponse({ job: currentJob }));
      return true;

    case MSG.PLAYER_STARTED:
      updateJob({ status: JOB_STATUS.PLAYING });
      return false;

    case MSG.PLAYER_PROGRESS:
      updateJob({ chunksDone: msg.chunksDone });
      return false;

    case MSG.PLAYER_ENDED:
      updateJob({
        status: JOB_STATUS.IDLE,
        id: null,
        chunksDone: 0,
        chunksTotal: 0,
      });
      return false;

    case MSG.PLAYER_ERROR:
      if (!job.id || job.status === JOB_STATUS.IDLE) return false;
      setJobError(msg.error || 'Playback failed');
      return false;
  }
});

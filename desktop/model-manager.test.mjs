import test from 'node:test';
import assert from 'node:assert/strict';
import { createModelManager, choiceAssets } from './model-manager.js';

class Element {
  constructor() { this.children = []; this.listeners = {}; this.hidden = false; this.disabled = false; this.value = ''; }
  set textContent(value) { this.text = value; this.children = []; }
  get textContent() { return this.text ?? ''; }
  append(...items) { this.children.push(...items); }
  prepend(item) { this.children.unshift(item); }
  replaceChildren(...items) { this.children = items; }
  addEventListener(type, handler) { this.listeners[type] = handler; }
  click() { return this.listeners.click?.(); }
  change() { return this.listeners.change?.(); }
}

globalThis.document = { createElement: () => new Element() };
const selectors = ['model-message', 'model-unavailable', 'model-content', 'model-choices', 'model-assets',
  'model-size', 'model-download', 'model-remove', 'model-cancel', 'model-progress', 'model-migration'];
const makeRoot = () => {
  const elements = Object.fromEntries(selectors.map((id) => [`#${id}`, new Element()]));
  return { elements, querySelector: (id) => elements[id] };
};
const catalog = {
  languages: [
    { id: 'en', label: 'English', engine: 'kokoro', assets: ['shared', 'english'], installed: false,
      voices: [{ id: 'bella', label: 'Bella', installed: false }] },
    { id: 'es', label: 'Spanish', engine: 'kokoro', assets: ['shared', 'spanish'], installed: false,
      voices: [{ id: 'dora', label: 'Dora', installed: false }] },
    { id: 'ru', label: 'Russian', engine: 'piper', assets: ['russian'], installed: true,
      voices: [{ id: 'dmitri', label: 'Dmitri', installed: true }] },
  ],
  assets: [
    { id: 'shared', size_bytes: 1048576, state: 'absent', license: 'Apache-2.0' },
    { id: 'english', size_bytes: null, state: 'absent', license: null },
    { id: 'spanish', size_bytes: 100, state: 'absent', license: 'Apache-2.0' },
    { id: 'russian', size_bytes: 100, state: 'verified', license: 'CC0' },
  ],
};
const flush = async () => { for (let i = 0; i < 8; i++) await new Promise((resolve) => setImmediate(resolve)); };

function setup({ savedJob, responses = {} } = {}) {
  const root = makeRoot();
  const store = new Map(savedJob ? [['local-voice-model-job', savedJob]] : []);
  const calls = [];
  const confirms = [];
  const manager = createModelManager({ root, storage: {
    getItem: (key) => store.get(key), setItem: (key, value) => store.set(key, value),
    removeItem: (key) => store.delete(key),
  }, confirm: async (message) => { confirms.push(message); return true; },
  request: async (path, options) => {
    calls.push({ path, options });
    const response = responses[path];
    if (response instanceof Error) throw response;
    if (typeof response === 'function') return response(options);
    return response ?? (path === '/models' ? catalog : path === '/models/migration' ? { candidates: [] } : {});
  } });
  return { root: root.elements, manager, calls, confirms, store };
}

test('selection lists shared bytes once, unknown sizes, and never starts a download', async () => {
  const t = setup();
  await t.manager.refresh();
  t.root['#model-choices'].children[0].children[0].checked = true;
  t.root['#model-choices'].children[0].children[0].change();
  t.root['#model-choices'].children[1].children[0].checked = true;
  t.root['#model-choices'].children[1].children[0].change();
  assert.deepEqual(choiceAssets(catalog, ['en', 'es']).map((asset) => asset.id), ['shared', 'english', 'spanish']);
  assert.match(t.root['#model-size'].textContent, /unknown size/);
  assert.equal(t.root['#model-assets'].children.filter((item) => item.textContent.includes('shared')).length, 1);
  assert.deepEqual(t.calls.map((call) => call.path), ['/models', '/models/migration']);
});

test('download consent, persisted job reconnection, cancellation, and retry', async () => {
  const t = setup({ responses: {
    '/models/downloads': { job_id: 'job1', status: 'downloading', bytes_done: 50, bytes_total: null },
    '/models/downloads/job1': { job_id: 'job1', status: 'failed', error: 'offline' },
    '/models/downloads/job1/cancel': { job_id: 'job1', status: 'downloading' },
  } });
  await t.manager.refresh();
  t.root['#model-choices'].children[0].children[0].checked = true;
  t.root['#model-choices'].children[0].children[0].change();
  t.root['#model-download'].click(); await flush();
  assert.match(t.confirms[0], /unknown size/);
  assert.equal(t.store.get('local-voice-model-job'), 'job1');
  assert.match(t.root['#model-progress'].textContent, /unknown total/);
  t.root['#model-cancel'].click(); await flush();
  assert.ok(t.calls.some((call) => call.path === '/models/downloads/job1/cancel'));
  await t.manager.poll();
  assert.match(t.root['#model-message'].textContent, /failed: offline/);
  assert.equal(t.store.has('local-voice-model-job'), false);
  t.root['#model-download'].click(); await flush();
  assert.equal(t.calls.filter((call) => call.path === '/models/downloads').length, 2);
  const reopened = setup({ savedJob: 'job1', responses: {
    '/models/downloads/job1': { job_id: 'job1', status: 'downloading', bytes_done: 50, bytes_total: 100 },
  } });
  await reopened.manager.refresh();
  assert.match(reopened.root['#model-progress'].textContent, /downloading/);
});

test('English 409, removal refusal, and explicit migration keep errors visible', async () => {
  const t = setup({ responses: {
    '/models/downloads': new Error('409 digest unavailable'),
    '/models/removals': new Error('409 assets in use'),
    '/models/migration': (options) => options?.method === 'POST'
      ? { migrated: ['shared'] }
      : { candidates: [{ id: 'candidate', asset_id: 'shared', source: '/old/shared' }] },
  } });
  await t.manager.refresh();
  t.root['#model-choices'].children[0].children[0].checked = true;
  t.root['#model-choices'].children[0].children[0].change();
  t.root['#model-download'].click(); await flush();
  assert.match(t.root['#model-message'].textContent, /spaCy wheel digest/);
  t.root['#model-choices'].children[2].children[0].checked = true;
  t.root['#model-choices'].children[2].children[0].change();
  t.root['#model-remove'].click(); await flush();
  assert.match(t.root['#model-message'].textContent, /in use/);
  assert.match(t.confirms[1], /Shared assets/);
  assert.equal(t.root['#model-migration'].children.length, 1);
  t.root['#model-migration'].children[0].click(); await flush();
  assert.ok(t.calls.some((call) => call.path === '/models/migration' && call.options?.method === 'POST'
    && JSON.parse(call.options.body).candidates[0] === 'candidate'));
  assert.match(t.confirms[2], /original is kept/);
});

test('lost service job reports restart without declaring completion', async () => {
  const t = setup({ savedJob: 'lost', responses: { '/models/downloads/lost': new Error('404') } });
  await t.manager.refresh();
  assert.match(t.root['#model-message'].textContent, /service restart/);
  assert.equal(t.store.has('local-voice-model-job'), false);
});

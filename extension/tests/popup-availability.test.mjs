import test from 'node:test';
import assert from 'node:assert/strict';

function element() {
  const item = { style: {}, classList: { add() {}, remove() {} }, children: [], value: '', textContent: '', disabled: false };
  Object.defineProperty(item, 'innerHTML', { set(value) { item.children = []; item.html = value; }, get() { return item.html; } });
  item.appendChild = (child) => item.children.push(child);
  item.addEventListener = (name, fn) => { item[`on${name}`] = fn; };
  return item;
}

test('popup marks unavailable voices and retains the stored selection', async () => {
  const nodes = new Map();
  globalThis.document = {
    querySelector(selector) {
      if (!nodes.has(selector)) nodes.set(selector, element());
      return nodes.get(selector);
    },
    createElement: element,
  };
  let replyState;
  globalThis.chrome = {
    storage: { local: { get: async () => ({}), set: async () => {} } },
    runtime: {
      getManifest: () => ({ version: '1.0' }),
      sendMessage: (_message, callback) => { replyState = callback; },
      onMessage: { addListener() {} },
    },
  };
  globalThis.fetch = async (url) => url.endsWith('/health')
    ? Response.json({ status: 'setup_needed', ready: false, engine: 'kokoro', dependencies: [] })
    : Response.json({ voices: [
      { id: 'af_bella', label: 'Bella', language: 'en', gender: 'f', sample_rate: 24000, available: false },
      { id: 'ef_dora', label: 'Dora', language: 'es', gender: 'f', sample_rate: 24000, available: true },
    ] });
  await import('../src/popup.js');
  await new Promise((resolve) => setTimeout(resolve, 10));
  const voices = nodes.get('#voice-select');
  assert.equal(voices.value, 'af_bella');
  assert.equal(voices.children[0].disabled, true);
  assert.match(voices.children[0].textContent, /not installed/);
  assert.equal(voices.children[1].disabled, false);
  assert.equal(nodes.get('#btn-speak').disabled, true);
  assert.match(nodes.get('#status-text').textContent, /Model Manager/);
  replyState({ job: { status: 'idle', chunksTotal: 0, chunksDone: 0 } });
  assert.match(nodes.get('#status-text').textContent, /Model Manager/);
  voices.onchange({ target: { value: 'ef_dora', selectedOptions: [voices.children[1]] } });
  await new Promise((resolve) => setTimeout(resolve, 10));
  assert.equal(nodes.get('#btn-speak').disabled, false);
});

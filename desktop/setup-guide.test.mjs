import assert from 'node:assert/strict';
import test from 'node:test';
import { createSetupGuide, noVerifiedVoice } from './setup-guide.js';

const catalog = (installed) => ({ languages: [{ voices: [{ id: 'af_bella', installed }] }] });

test('setup-needed opens the model manager once after the catalog is checked', () => {
  let opens = 0;
  const guide = createSetupGuide(() => { opens += 1; });
  const state = { setupNeeded: true, modelsChecked: true, catalog: catalog(false) };
  assert.equal(guide.promptOnce({ ...state, modelsChecked: false }), false);
  assert.equal(guide.promptOnce(state), true);
  assert.equal(guide.promptOnce(state), false);
  assert.equal(opens, 1);
  assert.equal(noVerifiedVoice(state.catalog), true);
});

test('Speak without a voice gives setup guidance and opens the manager', async () => {
  const events = [];
  const guide = createSetupGuide((refresh) => events.push(['open', refresh]),
    async (message) => { events.push(['notice', message]); });
  assert.equal(await guide.requireVoice({ setupNeeded: true, catalog: catalog(false) }), false);
  assert.match(events[0][1], /Model manager.*choose a language/);
  assert.deepEqual(events[1], ['open', true]);
  assert.equal(await guide.requireVoice({ setupNeeded: true, catalog: catalog(true) }), true);
  assert.equal(events.length, 2);
});

test('installed voice and ready service do not interrupt the user', () => {
  let opens = 0;
  const guide = createSetupGuide(() => { opens += 1; });
  assert.equal(guide.promptOnce({ setupNeeded: true, modelsChecked: true, catalog: catalog(true) }), false);
  assert.equal(guide.promptOnce({ setupNeeded: false, modelsChecked: true, catalog: catalog(false) }), false);
  assert.equal(opens, 0);
});

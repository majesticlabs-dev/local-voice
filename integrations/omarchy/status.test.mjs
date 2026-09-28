import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';

const source = readFileSync(new URL('./local-voice.panel/Status.js', import.meta.url), 'utf8');
const status = runInNewContext(`${source}\n({ controller, service, label })`);
const fakeController = state => status.controller(JSON.stringify({ state, error: null }), 0);

assert.equal(status.label(fakeController('playing'), 'ready'), 'Playing');
assert.equal(status.label(fakeController('reading'), 'ready'), 'Reading');
assert.equal(status.label(fakeController('idle'), 'ready'), 'Ready');
assert.equal(status.label(fakeController('offline'), 'ready'), 'Ready');
assert.equal(status.label(fakeController('idle'), 'setup_needed'), 'Setup needed');
assert.equal(status.label(fakeController('setup_needed'), 'ready'), 'Setup needed');
assert.equal(status.label(fakeController('playing'), 'down'), 'Service down');
assert.equal(status.label(fakeController('error'), 'ready'), 'Playback error');
assert.equal(status.service('{"status":"setup_needed"}', 0), 'setup_needed');
assert.equal(status.service('{"status":"ok"}', 0), 'ready');
assert.equal(status.service('{"status":"ok"}', 7), 'down');
assert.equal(status.service('not json', 0), 'down');
assert.equal(status.controller('not json', 0).state, 'offline');
assert.equal(status.controller('{"state":"unrecognized"}', 0).state, 'offline');
console.log('Omarchy panel status tests passed');

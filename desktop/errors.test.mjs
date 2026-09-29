import assert from 'node:assert/strict';
import test from 'node:test';
import { createErrorPresenter, serviceFetch, SERVICE_UNAVAILABLE } from './errors.js';

test('WebKit network failure becomes actionable service guidance', async () => {
  await assert.rejects(serviceFetch(async () => { throw new TypeError('Load failed'); }, '/synthesize'),
    (error) => error.message === SERVICE_UNAVAILABLE && !error.message.includes('Load failed'));
});

test('service failure stays inline and concurrent native errors share one dialog', async () => {
  const inline = [];
  let dialogs = 0;
  let close;
  const presenter = createErrorPresenter(async () => {
    dialogs += 1;
    await new Promise((resolve) => { close = resolve; });
  }, (message) => inline.push(message));
  await presenter.show(SERVICE_UNAVAILABLE);
  await presenter.show(SERVICE_UNAVAILABLE);
  assert.deepEqual(inline, [SERVICE_UNAVAILABLE, SERVICE_UNAVAILABLE]);
  assert.equal(dialogs, 0);
  const first = presenter.show('Other error');
  await presenter.show('Another error');
  assert.equal(dialogs, 1);
  close();
  await first;
  await presenter.show(SERVICE_UNAVAILABLE);
  assert.equal(dialogs, 1);
});

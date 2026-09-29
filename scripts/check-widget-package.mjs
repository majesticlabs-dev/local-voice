import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { spawnSync } from 'node:child_process';
import { runInNewContext } from 'node:vm';

const root = process.argv[2];
if (!root) throw new Error('Provide an extracted package root');
const source = readFileSync(join(root, 'usr/share/local-voice/local-voice.panel/Status.js'), 'utf8');
const commands = runInNewContext(`${source}\ncommands()`);
for (const [action, argv] of Object.entries(commands)) {
  const lookup = spawnSync('/bin/sh', ['-c', 'command -v "$1"', '_', argv[0]], {
    encoding: 'utf8',
    env: { PATH: join(root, 'usr/bin') },
  });
  assert.equal(lookup.status, 0, `${action}: ${argv[0]} is not an installed executable`);
  assert.equal(lookup.stdout.trim(), join(root, 'usr/bin', argv[0]));
}
console.log('Packaged widget commands resolve to installed executables');

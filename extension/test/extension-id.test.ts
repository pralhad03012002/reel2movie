import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { EXTENSION_ID } from '../../app/src/lib.js';

test('app EXTENSION_ID matches the id derived from manifest.json "key"', () => {
  const { key } = JSON.parse(readFileSync(new URL('../manifest.json', import.meta.url), 'utf8'));
  const hex = createHash('sha256').update(Buffer.from(key, 'base64')).digest('hex').slice(0, 32);
  const id = [...hex].map((c) => String.fromCharCode(97 + parseInt(c, 16))).join('');
  assert.equal(EXTENSION_ID, id);
});

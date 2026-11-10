// Synthesises the test audio corpus (tests/audio/corpus.json) with macOS `say`
// into tests/audio/wav/<id>.wav (16 kHz mono PCM16), plus a silent microphone
// track. Skips files that are newer than the manifest.
//
//   node tests/audio/build-corpus.mjs
import { execFileSync } from 'node:child_process';
import { existsSync, mkdirSync, readFileSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

const here = import.meta.dirname;
const manifest = join(here, 'corpus.json');
const out = join(here, 'wav');
mkdirSync(out, { recursive: true });
const { scenarios } = JSON.parse(readFileSync(manifest, 'utf8'));
const fresh = (file) => existsSync(file) && statSync(file).mtimeMs > statSync(manifest).mtimeMs;

for (const scenario of scenarios) {
  const wav = join(out, `${scenario.id}.wav`);
  if (fresh(wav)) continue;
  const aiff = join(out, `${scenario.id}.aiff`);
  execFileSync('say', ['-v', scenario.voice, '-r', '165', '-o', aiff, scenario.text]);
  execFileSync('afconvert', ['-f', 'WAVE', '-d', 'LEI16@16000', '-c', '1', aiff, wav]);
  rmSync(aiff);
  console.log('built', scenario.id);
}

// 60 s of silence for the microphone lane, so only the interviewer is heard.
const silence = join(out, 'silence.wav');
if (!existsSync(silence)) {
  const samples = 16_000 * 60;
  const header = Buffer.alloc(44);
  header.write('RIFF', 0); header.writeUInt32LE(36 + samples * 2, 4); header.write('WAVE', 8); header.write('fmt ', 12);
  header.writeUInt32LE(16, 16); header.writeUInt16LE(1, 20); header.writeUInt16LE(1, 22); header.writeUInt32LE(16_000, 24);
  header.writeUInt32LE(32_000, 28); header.writeUInt16LE(2, 32); header.writeUInt16LE(16, 34); header.write('data', 36); header.writeUInt32LE(samples * 2, 40);
  writeFileSync(silence, Buffer.concat([header, Buffer.alloc(samples * 2)]));
  console.log('built silence');
}

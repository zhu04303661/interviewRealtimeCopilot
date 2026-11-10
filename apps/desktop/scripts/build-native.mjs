// Builds the macOS system-audio helper (Core Audio process tap, macOS 14.2+).
// Skipped on other platforms and when it is already up to date.
import { execFileSync } from 'node:child_process';
import { existsSync, mkdirSync, statSync } from 'node:fs';
import { join } from 'node:path';

if (process.platform !== 'darwin') process.exit(0);
const root = join(import.meta.dirname, '..');
const source = join(root, 'native/system-audio/main.swift');
const binary = join(root, 'native/bin/irc-system-audio');
if (existsSync(binary) && statSync(binary).mtimeMs > statSync(source).mtimeMs) process.exit(0);
mkdirSync(join(root, 'native/bin'), { recursive: true });
const sdk = execFileSync('xcrun', ['--show-sdk-path']).toString().trim();
execFileSync('swiftc', ['-O', '-target', `${process.arch === 'arm64' ? 'arm64' : 'x86_64'}-apple-macos14.2`, '-sdk', sdk, source, '-o', binary], { stdio: 'inherit' });
console.log('built', binary);

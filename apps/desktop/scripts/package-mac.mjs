// Packages the macOS app (Apple Silicon) and a DMG, self-contained:
//   Contents/Resources/app     — the built Electron app (dist/, system-audio helper)
//   Contents/Resources/engine  — the engine source (engine/src)
//   Contents/Resources/python  — a standalone CPython 3.12 with the engine's dependencies
// Usage: node scripts/package-mac.mjs   (needs uv with a managed CPython 3.12: `uv python install 3.12`)
// The result is ad-hoc signed, not notarised: first launch needs System Settings → Privacy & Security → Open Anyway.
import { execFileSync } from 'node:child_process';
import { cpSync, existsSync, mkdirSync, readdirSync, readFileSync, rmSync, statSync, symlinkSync, writeFileSync } from 'node:fs';
import { homedir, tmpdir } from 'node:os';
import { join } from 'node:path';

const root = join(import.meta.dirname, '..');
const repo = join(root, '../..');
const pkg = JSON.parse(readFileSync(join(root, 'package.json'), 'utf8'));
const name = pkg.productName;
const out = join(root, 'dist-mac');
const app = join(out, `${name}.app`);
const resources = join(app, 'Contents/Resources');
const run = (cmd, args, opts = {}) => execFileSync(cmd, args, { stdio: ['ignore', 'pipe', 'inherit'], ...opts }).toString().trim();
const step = (text) => console.log(`• ${text}`);
if (process.platform !== 'darwin' || process.arch !== 'arm64') throw new Error('Run this on an Apple Silicon Mac.');

step('build');
execFileSync('npm', ['run', 'build'], { cwd: root, stdio: 'inherit' });

step('app bundle');
rmSync(out, { recursive: true, force: true });
mkdirSync(out, { recursive: true });
run('ditto', [join(root, 'node_modules/electron/dist/Electron.app'), app]);
rmSync(join(resources, 'default_app.asar'), { force: true });
const appDir = join(resources, 'app');
mkdirSync(join(appDir, 'native/bin'), { recursive: true });
cpSync(join(root, 'dist'), join(appDir, 'dist'), { recursive: true });
cpSync(join(root, 'native/bin/irc-system-audio'), join(appDir, 'native/bin/irc-system-audio'));
writeFileSync(join(appDir, 'package.json'), JSON.stringify({ name: pkg.name, productName: name, version: pkg.version, main: pkg.main }, null, 2));

step('icon');
const iconset = join(tmpdir(), 'irc.iconset');
rmSync(iconset, { recursive: true, force: true });
mkdirSync(iconset);
const html = join(tmpdir(), 'irc-icon.html');
writeFileSync(html, `<html><body style="margin:0;background:transparent"><div style="width:1024px;height:1024px;display:grid;place-items:center">
<div style="width:824px;height:824px;border-radius:186px;background:linear-gradient(135deg,#7c5cff,#4f7cff 50%,#2ad4ff);display:grid;place-items:center;box-shadow:inset 0 0 80px rgba(255,255,255,.25)">
<span style="font:800 330px -apple-system,Helvetica;color:#fff;letter-spacing:-12px">IR</span></div></div></body></html>`);
const png = join(tmpdir(), 'irc-icon.png');
run('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', ['--headless=new', '--disable-gpu', '--hide-scrollbars', '--default-background-color=00000000',
  '--window-size=1024,1024', `--screenshot=${png}`, `file://${html}`]);
for (const size of [16, 32, 128, 256, 512]) {
  run('sips', ['-z', String(size), String(size), png, '--out', join(iconset, `icon_${size}x${size}.png`)]);
  run('sips', ['-z', String(size * 2), String(size * 2), png, '--out', join(iconset, `icon_${size}x${size}@2x.png`)]);
}
rmSync(join(resources, 'electron.icns'), { force: true });
run('iconutil', ['-c', 'icns', iconset, '-o', join(resources, 'icon.icns')]);

step('Info.plist');
const plist = join(app, 'Contents/Info.plist');
const set = (key, value) => { try { run('/usr/libexec/PlistBuddy', ['-c', `Set :${key} ${value}`, plist]); } catch { run('/usr/libexec/PlistBuddy', ['-c', `Add :${key} string ${value}`, plist]); } };
set('CFBundleName', name);
set('CFBundleDisplayName', name);
set('CFBundleIdentifier', 'com.xichiuk.interview-realtime-copilot');
set('CFBundleShortVersionString', pkg.version);
set('CFBundleVersion', pkg.version);
set('CFBundleIconFile', 'icon.icns');
set('LSMinimumSystemVersion', '14.2');
set('NSMicrophoneUsageDescription', `${name} transcribes your answers during practice and live interviews.`);
set('NSAudioCaptureUsageDescription', `${name} listens to the interviewer in your meeting app during a live interview.`);
set('NSCameraUsageDescription', `${name} does not use the camera.`);

step('engine source');
cpSync(join(repo, 'engine/src'), join(resources, 'engine/src'), { recursive: true, filter: (p) => !p.includes('__pycache__') });

step('Python 3.12 + dependencies');
const pythons = join(homedir(), '.local/share/uv/python');
const cpython = readdirSync(pythons).filter((d) => /^cpython-3\.12\.\d+-macos-aarch64-none$/.test(d)).sort().at(-1);
if (!cpython) throw new Error('No uv-managed CPython 3.12: run `uv python install 3.12`.');
const python = join(resources, 'python');
run('ditto', [join(pythons, cpython), python]);
const lib = join(python, 'lib/python3.12');
for (const unused of ['test', 'idlelib', 'tkinter', 'turtledemo', 'ensurepip', 'lib2to3', 'pydoc_data']) rmSync(join(lib, unused), { recursive: true, force: true });
for (const unused of ['include', 'share']) rmSync(join(python, unused), { recursive: true, force: true });
for (const entry of readdirSync(join(python, 'lib'))) if (/^(tcl|tk|itcl|thread)/i.test(entry)) rmSync(join(python, 'lib', entry), { recursive: true, force: true });
rmSync(join(lib, 'EXTERNALLY-MANAGED'), { force: true });
const requirements = join(tmpdir(), 'irc-requirements.txt');
run('uv', ['export', '--project', join(repo, 'engine'), '--no-dev', '--no-hashes', '--no-emit-project', '--format', 'requirements-txt', '-o', requirements]);
execFileSync('uv', ['pip', 'install', '--python', join(python, 'bin/python3'), '--no-cache', '-q', '-r', requirements], { stdio: 'inherit' });
run(join(python, 'bin/python3'), ['-c', 'import aiohttp, aiohttp_socks, pypdfium2; print("ok")']);
run(join(python, 'bin/python3'), ['-m', 'compileall', '-q', '-j0', lib, join(resources, 'engine/src')]);

step('sign (ad-hoc)');
const machO = [];
const walk = (dir) => { for (const entry of readdirSync(dir, { withFileTypes: true })) {
  const p = join(dir, entry.name);
  if (entry.isDirectory()) walk(p);
  else if (entry.isFile() && (statSync(p).mode & 0o111 || /\.(so|dylib)$/.test(p)) && run('file', ['-b', p]).includes('Mach-O')) machO.push(p);
} };
walk(python); walk(join(appDir, 'native'));
for (let i = 0; i < machO.length; i += 50) run('codesign', ['--force', '--sign', '-', ...machO.slice(i, i + 50)]);
run('codesign', ['--force', '--deep', '--sign', '-', app], { stdio: ['ignore', 'pipe', 'pipe'] });  // frameworks, helpers, then the app
run('codesign', ['--verify', '--deep', '--strict', app]);

step('DMG');
const stage = join(out, 'dmg');
mkdirSync(stage);
run('ditto', [app, join(stage, `${name}.app`)]);
symlinkSync('/Applications', join(stage, 'Applications'));
const dmg = join(out, `Interview-Realtime-Copilot-${pkg.version}-arm64.dmg`);
run('hdiutil', ['create', '-volname', name, '-srcfolder', stage, '-format', 'UDZO', '-ov', dmg]);
rmSync(stage, { recursive: true, force: true });
const size = statSync(dmg).size;
writeFileSync(join(out, 'latest.json'), JSON.stringify({ version: pkg.version, file: dmg.split('/').at(-1), size_mb: Math.round(size / 1e6), date: new Date().toISOString().slice(0, 10), arch: 'arm64' }, null, 2));
console.log(`done: ${dmg} (${Math.round(size / 1e6)} MB)`);

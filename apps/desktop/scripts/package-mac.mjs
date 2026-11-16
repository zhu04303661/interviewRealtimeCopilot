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
writeFileSync(html, `<html><body style="margin:0;background:transparent"><img src="file://${join(root, 'assets/icon.svg')}" width="1024" height="1024"></body></html>`);
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
const chromeShot = (file, width, height, htmlText) => {
  const page = join(tmpdir(), 'irc-dmg-page.html');
  writeFileSync(page, htmlText);
  run('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', ['--headless=new', '--disable-gpu', '--hide-scrollbars', `--window-size=${width},${height}`,
    '--force-device-scale-factor=2', `--screenshot=${file}`, `file://${page}`]);
};
const stage = join(out, 'dmg');
mkdirSync(join(stage, '.background'), { recursive: true });
run('ditto', [app, join(stage, `${name}.app`)]);
symlinkSync('/Applications', join(stage, 'Applications'));
// Installer window background (660x420 points, rendered at 2x): app on the left, arrow, Applications on the right.
chromeShot(join(stage, '.background/background.png'), 660, 420, `<html><body style="margin:0;width:660px;height:420px;overflow:hidden;position:relative;
  background:radial-gradient(420px 300px at 18% 0%,#3a2f8f 0%,transparent 70%),radial-gradient(420px 300px at 100% 10%,#0f5f8a 0%,transparent 70%),#0b0d18;
  font-family:-apple-system,'PingFang SC',Helvetica,sans-serif;color:#fff">
  <div style="position:absolute;top:34px;width:100%;text-align:center;font-size:21px;font-weight:650;letter-spacing:-.2px">${name}</div>
  <div style="position:absolute;top:66px;width:100%;text-align:center;font-size:13px;color:#aab1cc">Drag the app into Applications to install · 拖入「应用程序」即可安装</div>
  <svg style="position:absolute;left:270px;top:170px" width="120" height="60" viewBox="0 0 120 60" fill="none" stroke="url(#g)" stroke-width="7" stroke-linecap="round" stroke-linejoin="round">
    <defs><linearGradient id="g" x1="0" x2="1"><stop stop-color="#8b6bff"/><stop offset="1" stop-color="#16c8f5"/></linearGradient></defs><path d="M8 30h98M82 8l24 22-24 22"/></svg>
  </body></html>`);
run('sips', ['-s', 'dpiWidth', '144', '-s', 'dpiHeight', '144', join(stage, '.background/background.png')]);  // 2x: Finder sizes it as 660x420 points
const dmg = join(out, `Interview-Realtime-Copilot-${pkg.version}-arm64.dmg`);
const rw = join(out, 'rw.dmg');
run('hdiutil', ['create', '-volname', name, '-srcfolder', stage, '-fs', 'HFS+', '-format', 'UDRW', '-ov', rw]);
rmSync(stage, { recursive: true, force: true });
const mount = run('hdiutil', ['attach', rw, '-readwrite', '-noverify', '-noautoopen']).split('\n').map((l) => l.match(/\/Volumes\/.*$/)?.[0]).find(Boolean);
try {
  // Finder lays out the window (needs Automation permission for Finder; without it the DMG still works, just unstyled).
  const volume = mount.split('/').at(-1);
  try {
    run('osascript', ['-e', `tell application "Finder" to tell disk "${volume}"
      open
      set current view of container window to icon view
      set toolbar visible of container window to false
      set statusbar visible of container window to false
      set the bounds of container window to {200, 120, 860, 568}
      set opts to the icon view options of container window
      set arrangement of opts to not arranged
      set icon size of opts to 112
      set text size of opts to 13
      set background picture of opts to file ".background:background.png"
      set position of item "${name}.app" of container window to {165, 215}
      set position of item "Applications" of container window to {495, 215}
      update without registering applications
      delay 1
      close
    end tell`], { timeout: 60_000, stdio: ['ignore', 'pipe', 'pipe'] });
  } catch (error) { console.log(`  (window layout skipped: ${String(error.stderr ?? error.message).trim().split('\n').at(-1)})`); }
  // Volume icon, set after the Finder layout (Finder's update removes a custom volume icon set earlier).
  cpSync(join(resources, 'icon.icns'), join(mount, '.VolumeIcon.icns'));
  run('SetFile', ['-a', 'C', mount]);
  run('sync', []);
} finally {
  run('hdiutil', ['detach', mount, '-force']);
}
run('hdiutil', ['convert', rw, '-format', 'UDZO', '-imagekey', 'zlib-level=9', '-ov', '-o', dmg]);
rmSync(rw, { force: true });
const size = statSync(dmg).size;
writeFileSync(join(out, 'latest.json'), JSON.stringify({ version: pkg.version, file: dmg.split('/').at(-1), size_mb: Math.round(size / 1e6), date: new Date().toISOString().slice(0, 10), arch: 'arm64' }, null, 2));
console.log(`done: ${dmg} (${Math.round(size / 1e6)} MB)`);

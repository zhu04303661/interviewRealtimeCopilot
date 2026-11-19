// Packages the Windows app (x64 by default) and a per-user NSIS installer, self-contained:
//   <app>\Interview Realtime Copilot.exe   — Electron's electron.exe, renamed
//   <app>\resources\app      — the built Electron app (dist/)
//   <app>\resources\engine   — the engine source (engine/src)
//   <app>\resources\python   — a standalone CPython 3.12 for Windows with the engine's dependencies
//   <app>\resources\icon.ico — window/shortcut icon
// Runs on Windows, and also cross-builds from macOS or Linux (everything is downloaded for the Windows target).
// Usage: node scripts/package-win.mjs [--arch x64|arm64] [--dir]
//   --dir   stop after the unpacked app folder (dist-win/win-unpacked), no installer
// Needs: uv, curl and tar (Windows 10+ ships both), and NSIS's makensis for the installer
//   (Windows: `winget install NSIS.NSIS` or `choco install nsis`; Linux: `apt install nsis`; macOS: `brew install makensis`).
// Optional: IRC_WIN_PYTHON_URL (a python-build-standalone install_only archive) overrides the Python download;
//   ELECTRON_MIRROR is honoured for the Electron download.
// The result is not code-signed: SmartScreen shows "Windows protected your PC" → More info → Run anyway.
import { execFileSync, spawnSync } from 'node:child_process';
import { cpSync, existsSync, mkdirSync, readdirSync, readFileSync, renameSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import * as ResEdit from 'resedit';

const root = join(import.meta.dirname, '..');
const repo = join(root, '../..');
const pkg = JSON.parse(readFileSync(join(root, 'package.json'), 'utf8'));
const name = pkg.productName;
const exeName = `${name}.exe`;
const args = process.argv.slice(2);
const arch = args.includes('--arch') ? args[args.indexOf('--arch') + 1] : 'x64';
if (!['x64', 'arm64'].includes(arch)) throw new Error(`Unsupported arch ${arch} (x64 or arm64).`);
const onWindows = process.platform === 'win32';
const out = join(root, 'dist-win');
const cache = join(out, 'cache');
const app = join(out, 'win-unpacked');
const resources = join(app, 'resources');
const run = (cmd, argv, opts = {}) => execFileSync(cmd, argv, { stdio: ['ignore', 'pipe', 'inherit'], shell: false, ...opts }).toString().trim();
const has = (cmd, flag) => spawnSync(cmd, [flag], { stdio: 'ignore' }).status === 0;
const py312 = ['uv', 'run', '--no-project', '--python', '3.12', 'python'];  // any CPython 3.12 on the build machine
const step = (text) => console.log(`• ${text}`);
const download = (url, file) => {
  if (existsSync(file)) return file;
  execFileSync('curl', ['-fsSL', '--retry', '3', '-o', `${file}.part`, url], { stdio: ['ignore', 'inherit', 'inherit'] });
  renameSync(`${file}.part`, file);
  return file;
};

step('build');
execFileSync('npm', ['run', 'build'], { cwd: root, stdio: 'inherit', shell: onWindows });  // npm is npm.cmd on Windows

rmSync(app, { recursive: true, force: true });
mkdirSync(cache, { recursive: true });

step(`Electron ${pkg.devDependencies.electron} (win32-${arch})`);
// @electron/get is Electron's own downloader (a dependency of the electron package, so already in node_modules).
const electronGet = await import('@electron/get')
  .catch(() => import(pathToFileURL(join(root, 'node_modules/electron/node_modules/@electron/get/dist/index.js')).href));
if (process.env.HTTPS_PROXY || process.env.https_proxy) { process.env.ELECTRON_GET_USE_PROXY ??= '1'; electronGet.initializeProxy(); }
const electronVersion = JSON.parse(readFileSync(join(root, 'node_modules/electron/package.json'), 'utf8')).version;
const electronZip = await electronGet.downloadArtifact({ version: electronVersion, artifactName: 'electron', platform: 'win32', arch });
execFileSync(py312[0], [...py312.slice(1), '-m', 'zipfile', '-e', electronZip, app], { stdio: 'inherit' });
renameSync(join(app, 'electron.exe'), join(app, exeName));
rmSync(join(resources, 'default_app.asar'), { force: true });

step('app');
const appDir = join(resources, 'app');
mkdirSync(appDir, { recursive: true });
cpSync(join(root, 'dist'), join(appDir, 'dist'), { recursive: true });
writeFileSync(join(appDir, 'package.json'), JSON.stringify({ name: pkg.name, productName: name, version: pkg.version, main: pkg.main }, null, 2));
cpSync(join(root, 'assets/icon.ico'), join(resources, 'icon.ico'));

step('exe icon and version info');
// resedit rewrites the .exe's resources in JavaScript, so this works on any build machine (no rcedit/wine).
const exePath = join(app, exeName);
const exe = ResEdit.NtExecutable.from(readFileSync(exePath), { ignoreCert: true });
const exeResources = ResEdit.NtExecutableResource.from(exe);
const [iconGroup] = ResEdit.Resource.IconGroupEntry.fromEntries(exeResources.entries);
const icons = ResEdit.Data.IconFile.from(readFileSync(join(root, 'assets/icon.ico'))).icons.map((icon) => icon.data);
ResEdit.Resource.IconGroupEntry.replaceIconsForResource(exeResources.entries, iconGroup.id, iconGroup.lang, icons);
const [versionInfo] = ResEdit.Resource.VersionInfo.fromEntries(exeResources.entries);
const [major, minor, patch] = pkg.version.split(/[.-]/).map(Number);
for (const language of versionInfo.getAllLanguagesForStringValues()) {
  versionInfo.setStringValues(language, { ProductName: name, FileDescription: name, CompanyName: name, InternalName: name,
    OriginalFilename: exeName, ProductVersion: pkg.version, FileVersion: pkg.version, LegalCopyright: '' });
}
versionInfo.setFileVersion(major, minor, patch, 0);
versionInfo.setProductVersion(major, minor, patch, 0);
versionInfo.outputToResourceEntries(exeResources.entries);
exeResources.outputResource(exe);
writeFileSync(exePath, Buffer.from(exe.generate()));

step('engine source');
cpSync(join(repo, 'engine/src'), join(resources, 'engine/src'), { recursive: true, filter: (p) => !p.includes('__pycache__') });

step('Python 3.12 (Windows) + dependencies');
const pythonArch = arch === 'x64' ? 'x86_64' : 'aarch64';
let pythonUrl = process.env.IRC_WIN_PYTHON_URL;
if (!pythonUrl) {
  // uv knows the python-build-standalone download for every platform (and applies UV_PYTHON_INSTALL_MIRROR).
  const listed = JSON.parse(run('uv', ['python', 'list', '--all-platforms', '--only-downloads', '--output-format', 'json']));
  const candidates = listed.filter((p) => p.implementation === 'cpython' && p.os === 'windows' && p.arch === pythonArch
    && p.version.startsWith('3.12.') && p.url && !/freethreaded|debug/.test(p.key) && (p.variant ?? 'default') === 'default');
  candidates.sort((a, b) => Number(b.version.split('.')[2]) - Number(a.version.split('.')[2]));
  pythonUrl = candidates[0]?.url;
  if (!pythonUrl) throw new Error(`uv lists no CPython 3.12 for windows-${pythonArch}; set IRC_WIN_PYTHON_URL.`);
}
const pythonArchive = download(pythonUrl, join(cache, decodeURIComponent(pythonUrl.split('/').at(-1))));
const unpack = join(cache, 'python-unpack');
rmSync(unpack, { recursive: true, force: true });
mkdirSync(unpack);
run('tar', ['-xzf', pythonArchive, '-C', unpack]);  // install_only archives hold one folder, python\
const python = join(resources, 'python');
renameSync(join(unpack, 'python'), python);
rmSync(unpack, { recursive: true, force: true });
if (!existsSync(join(python, 'python.exe'))) throw new Error(`${pythonUrl} is not a Windows install_only build (no python.exe).`);
const lib = join(python, 'Lib');
for (const unused of ['test', 'idlelib', 'tkinter', 'turtledemo', 'ensurepip', 'lib2to3', 'pydoc_data']) rmSync(join(lib, unused), { recursive: true, force: true });
for (const unused of ['include', 'libs', 'tcl', 'Scripts']) rmSync(join(python, unused), { recursive: true, force: true });
for (const entry of readdirSync(join(python, 'DLLs'))) if (/^(_tkinter|tcl|tk)/i.test(entry)) rmSync(join(python, 'DLLs', entry), { force: true });
rmSync(join(lib, 'EXTERNALLY-MANAGED'), { force: true });
const requirements = join(cache, 'requirements.txt');
run('uv', ['export', '--project', join(repo, 'engine'), '--no-dev', '--no-hashes', '--no-emit-project', '--format', 'requirements-txt', '-o', requirements]);
// Wheels for the Windows target, whatever the build machine is.
execFileSync('uv', ['pip', 'install', '--python', '3.12', '--target', join(lib, 'site-packages'), '--python-version', '3.12',
  '--python-platform', arch === 'x64' ? 'x86_64-pc-windows-msvc' : 'aarch64-pc-windows-msvc',
  '--only-binary', ':all:', '--no-cache', '-q', '-r', requirements], { stdio: 'inherit' });
rmSync(join(lib, 'site-packages', 'bin'), { recursive: true, force: true });  // console-script launchers --target writes; unused
// Byte-code: any CPython 3.12 writes the same .pyc files (same magic number), so cross-builds compile with uv's.
const compileWith = onWindows && arch === 'x64' ? [join(python, 'python.exe')] : py312;
execFileSync(compileWith[0], [...compileWith.slice(1), '-m', 'compileall', '-q', '-j0', lib, join(resources, 'engine/src')], { stdio: ['ignore', 'ignore', 'inherit'] });
if (onWindows && arch === 'x64') {
  run(join(python, 'python.exe'), ['-c', 'import aiohttp, aiohttp_socks, pypdfium2; print("ok")'],
    { env: { ...process.env, PYTHONPATH: join(resources, 'engine/src'), PYTHONNOUSERSITE: '1' } });
}

const sizeOf = (dir) => readdirSync(dir, { withFileTypes: true }).reduce((sum, e) => sum + (e.isDirectory() ? sizeOf(join(dir, e.name)) : statSync(join(dir, e.name)).size), 0);
console.log(`  unpacked: ${app} (${Math.round(sizeOf(app) / 1e6)} MB)`);
if (args.includes('--dir')) process.exit(0);

step('installer (NSIS)');
const makensis = ['makensis', ...(onWindows ? ['C:\\Program Files (x86)\\NSIS\\makensis.exe', 'C:\\Program Files\\NSIS\\makensis.exe'] : [])]
  .find((c) => c === 'makensis' ? has('makensis', '-VERSION') : existsSync(c));
if (!makensis) throw new Error('makensis not found: install NSIS (see the top of this script), or pass --dir for the unpacked app only.');
const setup = `Interview-Realtime-Copilot-${pkg.version}-${arch}-setup.exe`;
const nsi = join(out, 'installer.nsi');
const id = 'InterviewRealtimeCopilot';
// Build-machine paths stay native (makensis on macOS/Linux reads POSIX paths); install-time paths use backslashes.
// Per-user install (no administrator prompt) to %LOCALAPPDATA%\Programs, like most Electron apps. Uninstalling keeps
// the user's data (%APPDATA%\Interview Realtime Copilot): accounts, documents and sessions survive a reinstall.
writeFileSync(nsi, `Unicode true
ManifestDPIAware true
SetCompressor /SOLID lzma
RequestExecutionLevel user
!include "MUI2.nsh"
Name "${name}"
OutFile "${join(out, setup)}"
InstallDir "$LOCALAPPDATA\\Programs\\${name}"
InstallDirRegKey HKCU "Software\\${id}" "InstallDir"
BrandingText "${name} ${pkg.version}"
VIProductVersion "${pkg.version.split('-')[0].split('.').concat(['0', '0', '0']).slice(0, 4).join('.')}"
VIAddVersionKey "ProductName" "${name}"
VIAddVersionKey "ProductVersion" "${pkg.version}"
VIAddVersionKey "FileDescription" "${name} installer"
VIAddVersionKey "FileVersion" "${pkg.version}"
VIAddVersionKey "LegalCopyright" "Interview Realtime Copilot"
!define MUI_ICON "${join(root, 'assets', 'icon.ico')}"
!define MUI_UNICON "${join(root, 'assets', 'icon.ico')}"
!define MUI_ABORTWARNING
!define MUI_FINISHPAGE_RUN "$INSTDIR\\${exeName}"
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"
!insertmacro MUI_LANGUAGE "SimpChinese"

Section "Install"
  ; A running copy holds its files open; its engine exits on its own once the app is gone.
  nsExec::Exec 'taskkill /f /t /im "${exeName}"'
  Sleep 500
  RMDir /r "$INSTDIR\\resources"
  SetOutPath "$INSTDIR"
  File /r "${join(app, '*.*')}"
  WriteUninstaller "$INSTDIR\\Uninstall.exe"
  CreateShortcut "$SMPROGRAMS\\${name}.lnk" "$INSTDIR\\${exeName}" "" "$INSTDIR\\resources\\icon.ico" 0
  CreateShortcut "$DESKTOP\\${name}.lnk" "$INSTDIR\\${exeName}" "" "$INSTDIR\\resources\\icon.ico" 0
  WriteRegStr HKCU "Software\\${id}" "InstallDir" "$INSTDIR"
  !define UNINSTALL_KEY "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\${id}"
  WriteRegStr HKCU "\${UNINSTALL_KEY}" "DisplayName" "${name}"
  WriteRegStr HKCU "\${UNINSTALL_KEY}" "DisplayVersion" "${pkg.version}"
  WriteRegStr HKCU "\${UNINSTALL_KEY}" "Publisher" "Interview Realtime Copilot"
  WriteRegStr HKCU "\${UNINSTALL_KEY}" "URLInfoAbout" "https://copilot.xichiuk.com"
  WriteRegStr HKCU "\${UNINSTALL_KEY}" "DisplayIcon" "$INSTDIR\\resources\\icon.ico"
  WriteRegStr HKCU "\${UNINSTALL_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "\${UNINSTALL_KEY}" "UninstallString" '"$INSTDIR\\Uninstall.exe"'
  WriteRegStr HKCU "\${UNINSTALL_KEY}" "QuietUninstallString" '"$INSTDIR\\Uninstall.exe" /S'
  WriteRegDWORD HKCU "\${UNINSTALL_KEY}" "NoModify" 1
  WriteRegDWORD HKCU "\${UNINSTALL_KEY}" "NoRepair" 1
  WriteRegDWORD HKCU "\${UNINSTALL_KEY}" "EstimatedSize" ${Math.round(sizeOf(app) / 1024)}
SectionEnd

Section "Uninstall"
  nsExec::Exec 'taskkill /f /t /im "${exeName}"'
  Sleep 500
  Delete "$SMPROGRAMS\\${name}.lnk"
  Delete "$DESKTOP\\${name}.lnk"
  ; "Launch at login" (Settings) registers the .exe under Run; remove it with the app.
  DeleteRegValue HKCU "Software\\Microsoft\\Windows\\CurrentVersion\\Run" "com.xichiuk.interview-realtime-copilot"
  DeleteRegKey HKCU "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\${id}"
  DeleteRegKey HKCU "Software\\${id}"
  RMDir /r "$INSTDIR"
SectionEnd
`);
execFileSync(makensis, ['-V2', nsi], { stdio: 'inherit' });
const size = statSync(join(out, setup)).size;
writeFileSync(join(out, 'latest-win.json'), JSON.stringify({ version: pkg.version, file: setup, size_mb: Math.round(size / 1e6),
  date: new Date().toISOString().slice(0, 10), arch, platform: 'windows' }, null, 2));
console.log(`done: ${join(out, setup)} (${Math.round(size / 1e6)} MB)`);

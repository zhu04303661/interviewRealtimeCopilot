// Device settings (this computer only): cockpit appearance, stealth, screen
// capture and shortcuts. Stored as JSON in the data folder; account-level
// preferences (languages, playbook, consents) live in the engine instead.
import { readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

export const SHORTCUTS = {
  toggleResults: 'Alt+C',
  solveScreen: 'Alt+S',
  toggleAssistant: 'Alt+A',
  moveUp: 'Alt+Up',
  moveDown: 'Alt+Down',
  moveLeft: 'Alt+Left',
  moveRight: 'Alt+Right',
  grow: 'Alt+=',
  shrink: 'Alt+-',
} as const;
export type ShortcutId = keyof typeof SHORTCUTS;

export interface Settings {
  launchAtLogin: boolean;
  /** Content protection: the cockpit never appears in a shared screen or recording. */
  stealth: boolean;
  /** Capture the screen automatically when a question needs it (coding, system design). */
  autoCapture: boolean;
  /** Cockpit background opacity, 0.7–1 (below 0.7 text stops surviving busy meeting content). */
  opacity: number;
  background: string;
  text: string;
  shortcuts: Record<ShortcutId, string>;
}

export const DEFAULTS: Settings = {
  launchAtLogin: false, stealth: true, autoCapture: true, opacity: 0.8, background: '#0c0d10', text: '#e9eaec',
  shortcuts: { ...SHORTCUTS },
};

const COLOR = /^#[0-9a-f]{6}$/i;
const ACCELERATOR = /^(?:(?:Alt|Option|Shift|Control|Ctrl|Command|Cmd|CommandOrControl|Super)\+)+(?:[A-Z0-9]|F\d{1,2}|Up|Down|Left|Right|Space|Tab|Enter|=|-|\[|\]|;|'|,|\.|\/|\\|`)$/i;

/** Merge a (possibly partial or malformed) value over the defaults, keeping only valid fields. */
export function normalize(value: unknown, base: Settings = DEFAULTS): Settings {
  const v = (value && typeof value === 'object' ? value : {}) as Partial<Settings>;
  const shortcuts = { ...base.shortcuts };
  for (const id of Object.keys(SHORTCUTS) as ShortcutId[]) {
    const key = v.shortcuts?.[id];
    if (typeof key === 'string' && ACCELERATOR.test(key)) shortcuts[id] = key;
  }
  const flag = (key: 'launchAtLogin' | 'stealth' | 'autoCapture') => (typeof v[key] === 'boolean' ? v[key] as boolean : base[key]);
  return {
    launchAtLogin: flag('launchAtLogin'), stealth: flag('stealth'), autoCapture: flag('autoCapture'),
    opacity: typeof v.opacity === 'number' && Number.isFinite(v.opacity) ? Math.min(1, Math.max(0.7, v.opacity)) : base.opacity,
    background: typeof v.background === 'string' && COLOR.test(v.background) ? v.background.toLowerCase() : base.background,
    text: typeof v.text === 'string' && COLOR.test(v.text) ? v.text.toLowerCase() : base.text,
    shortcuts,
  };
}

export class SettingsStore {
  private readonly file: string;
  value: Settings;

  constructor(dataDir: string) {
    this.file = join(dataDir, 'settings.json');
    let stored: unknown = {};
    try { stored = JSON.parse(readFileSync(this.file, 'utf8')); } catch { /* first run or unreadable: defaults */ }
    this.value = normalize(stored);
  }

  update(patch: unknown): Settings {
    const merged = { ...this.value, ...(patch && typeof patch === 'object' ? patch : {}) } as Settings;
    if (patch && typeof patch === 'object' && 'shortcuts' in patch) merged.shortcuts = { ...this.value.shortcuts, ...(patch as Settings).shortcuts };
    this.value = normalize(merged, this.value);
    writeFileSync(this.file, JSON.stringify(this.value, null, 2), { mode: 0o600 });
    return this.value;
  }
}

interface DeviceSettings {
  launchAtLogin: boolean; stealth: boolean; autoCapture: boolean; opacity: number; background: string; text: string;
  shortcuts: Record<'toggleResults' | 'solveScreen' | 'toggleAssistant' | 'moveUp' | 'moveDown' | 'moveLeft' | 'moveRight' | 'grow' | 'shrink', string>;
}
interface Window {
  copilot: {
    request(method: string, path: string, body?: unknown): Promise<any>;
    importDocuments(kind: 'resume' | 'material'): Promise<any[]>;
    startSession(request: { topology: 'general' | 'mock'; goalId: string; documentIds: string[]; language: string;
      codingLanguage?: string | null; playbookId?: string | null; practiceMode?: string }): Promise<unknown>;
    currentSession(): Promise<{ sessionId: string; wsUrl: string; topology: 'general' | 'mock'; jwt: string; testSystemAudio?: string } | null>;
    endSession(): Promise<void>;
    permissions(): Promise<{ microphone: string; screen: string }>;
    requestMicrophone(): Promise<boolean>;
    openScreenSettings(): Promise<void>;
    saveRecording(sessionId: string, bytes: Uint8Array, contentType: string, durationMs: number): Promise<string>;
    loadRecording(sessionId: string): Promise<{ contentType: string; durationMs: number | null; data: Uint8Array } | null>;
    startSystemAudio(): Promise<boolean>;
    stopSystemAudio(): Promise<void>;
    onSystemAudio(listener: (frame: Uint8Array) => void): void;
    getSettings(): Promise<DeviceSettings>;
    apiKeyStatus(): Promise<{ configured: boolean; source: 'app' | 'environment' | 'none' }>;
    setApiKey(key: string): Promise<void>;
    cloudStatus(): Promise<{ signedIn: boolean; email?: string; user?: CloudUser; offline?: boolean; local?: LocalCredentials }>;
    cloudAuth(mode: 'register' | 'login', email: string, password: string): Promise<{ user: CloudUser; local: LocalCredentials }>;
    cloudSignOut(): Promise<void>;
    cloudOpen(next: string): Promise<void>;
    defaultSettings(): Promise<DeviceSettings>;
    setSettings(patch: Partial<DeviceSettings>): Promise<DeviceSettings>;
    onSettings(listener: (value: DeviceSettings) => void): void;
    onCockpitCommand(listener: (command: string) => void): void;
    solveScreen(origin: 'manual' | 'automatic'): Promise<unknown>;
    appInfo(): Promise<{ version: string; electron: string; platform: string; systemAudio: boolean }>;
    testSetSystemAudio(path: string): Promise<void>;
    testImportPaths(kind: 'resume' | 'material', paths: string[]): Promise<any[]>;
  };
}

type LocalCredentials = { username: string; password: string };
type CloudUser = { email: string; plan: 'free' | 'monthly' | 'yearly'; status: string; current_period_end: number | null;
  usage: { month: string; allowance_usd: number; used_usd: number; credit_usd: number; balance_usd: number; used_percent: number } };

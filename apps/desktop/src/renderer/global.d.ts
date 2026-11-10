interface DeviceSettings {
  launchAtLogin: boolean; stealth: boolean; autoCapture: boolean; opacity: number; background: string; text: string;
  shortcuts: Record<'toggleResults' | 'solveScreen' | 'toggleAssistant' | 'moveUp' | 'moveDown' | 'moveLeft' | 'moveRight' | 'grow' | 'shrink', string>;
}
interface Window {
  copilot: {
    request(method: string, path: string, body?: unknown): Promise<any>;
    importDocuments(kind: 'resume' | 'material'): Promise<any[]>;
    startSession(request: { topology: 'general' | 'mock'; goalId: string; documentIds: string[]; language: string }): Promise<unknown>;
    currentSession(): Promise<{ sessionId: string; wsUrl: string; topology: 'general' | 'mock'; jwt: string; testSystemAudio?: string } | null>;
    endSession(): Promise<void>;
    permissions(): Promise<{ microphone: string; screen: string }>;
    requestMicrophone(): Promise<boolean>;
    openScreenSettings(): Promise<void>;
    startSystemAudio(): Promise<boolean>;
    stopSystemAudio(): Promise<void>;
    onSystemAudio(listener: (frame: Uint8Array) => void): void;
    getSettings(): Promise<DeviceSettings>;
    defaultSettings(): Promise<DeviceSettings>;
    setSettings(patch: Partial<DeviceSettings>): Promise<DeviceSettings>;
    onSettings(listener: (value: DeviceSettings) => void): void;
    onCockpitCommand(listener: (command: string) => void): void;
    solveScreen(origin: 'manual' | 'automatic'): Promise<unknown>;
    appInfo(): Promise<{ version: string; electron: string; platform: string }>;
    testImportPaths(kind: 'resume' | 'material', paths: string[]): Promise<any[]>;
  };
}

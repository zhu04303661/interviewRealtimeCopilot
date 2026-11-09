interface Window {
  copilot: {
    request(method: string, path: string, body?: unknown): Promise<any>;
    importDocuments(kind: 'resume' | 'material'): Promise<any[]>;
    startSession(request: { topology: 'general' | 'mock'; goalId: string; documentIds: string[]; language: string }): Promise<unknown>;
    currentSession(): Promise<{ sessionId: string; wsUrl: string; topology: 'general' | 'mock'; jwt: string } | null>;
    endSession(): Promise<void>;
    permissions(): Promise<{ microphone: string; screen: string }>;
    requestMicrophone(): Promise<boolean>;
    openScreenSettings(): Promise<void>;
  };
}

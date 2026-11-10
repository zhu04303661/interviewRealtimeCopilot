// The only bridge between the renderers and the main process (window.copilot).
import { contextBridge, ipcRenderer } from 'electron';

const api = {
  request: (method: string, path: string, body?: unknown) => ipcRenderer.invoke('engine:request', method, path, body),
  importDocuments: (kind: 'resume' | 'material') => ipcRenderer.invoke('documents:pick-and-import', kind),
  startSession: (request: { topology: 'general' | 'mock'; goalId: string; documentIds: string[]; language: string }) =>
    ipcRenderer.invoke('session:start', request),
  currentSession: () => ipcRenderer.invoke('session:current'),
  endSession: () => ipcRenderer.invoke('session:end'),
  permissions: () => ipcRenderer.invoke('permissions:status'),
  requestMicrophone: () => ipcRenderer.invoke('permissions:request-microphone'),
  openScreenSettings: () => ipcRenderer.invoke('permissions:open-screen-settings'),
  getSettings: () => ipcRenderer.invoke('settings:get'),
  defaultSettings: () => ipcRenderer.invoke('settings:defaults'),
  setSettings: (patch: unknown) => ipcRenderer.invoke('settings:set', patch),
  onSettings: (listener: (value: unknown) => void) => { ipcRenderer.on('settings:changed', (_event, value) => listener(value)); },
  onCockpitCommand: (listener: (command: string) => void) => { ipcRenderer.on('cockpit:command', (_event, command) => listener(command)); },
  solveScreen: (origin: 'manual' | 'automatic') => ipcRenderer.invoke('screen:solve', origin),
  appInfo: () => ipcRenderer.invoke('app:info'),
  testImportPaths: (kind: 'resume' | 'material', paths: string[]) => ipcRenderer.invoke('test:import-paths', kind, paths),
};

contextBridge.exposeInMainWorld('copilot', api);
export type CopilotApi = typeof api;

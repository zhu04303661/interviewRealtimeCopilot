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
};

contextBridge.exposeInMainWorld('copilot', api);
export type CopilotApi = typeof api;

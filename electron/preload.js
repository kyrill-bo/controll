const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('kvm', {
  onDevicesUpdate: (cb) => ipcRenderer.on('devices:update', (_e, data) => cb(data)),
  onStatusUpdate: (cb) => ipcRenderer.on('status:update', (_e, text) => cb(text)),
  onSetupLog: (cb) => ipcRenderer.on('setup:log', (_e, text) => cb(text)),
  startServer: (options) => ipcRenderer.invoke('server:start', options),
  stopServer: () => ipcRenderer.invoke('server:stop'),
  setServerPort: (port) => ipcRenderer.invoke('server:setPort', port),
  disconnectClient: () => ipcRenderer.invoke('client:stop'),
  requestControl: (ip, optionsOrBody) => ipcRenderer.invoke('request:control', { ip, ...(optionsOrBody.options ? optionsOrBody : { options: optionsOrBody }) }),
  manualRequest: (host, optionsOrBody) => ipcRenderer.invoke('manual:request', { host, ...(optionsOrBody.options ? optionsOrBody : { options: optionsOrBody }) }),
  // Setup & config
  getConfig: () => ipcRenderer.invoke('config:get'),
  setPythonPath: (path) => ipcRenderer.invoke('config:setPython', path),
  choosePython: () => ipcRenderer.invoke('python:choose'),
  runSetup: () => ipcRenderer.invoke('setup:run'),
  openPermissions: (which) => ipcRenderer.invoke('permissions:open', which)
});

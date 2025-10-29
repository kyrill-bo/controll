import { app, BrowserWindow, ipcMain, dialog } from 'electron';
import path from 'path';
import { fileURLToPath } from 'url';
import dgram from 'dgram';
import os from 'os';
import { spawn } from 'child_process';
import fs from 'fs';
import { v4 as uuidv4 } from 'uuid';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// Multicast settings
const MCAST_GRP = '239.255.255.250';
const MCAST_PORT = 54545;
const BEACON_INTERVAL = 2000; // ms
const DEVICE_TTL = BEACON_INTERVAL * 3 + 2000; // ms

// Python executables (override with env PYTHON)
function getPythonCmd() {
  return config.pythonPath || process.env.PYTHON || 'python3';
}

function getPrimaryIp() {
  const ifaces = os.networkInterfaces();
  for (const name of Object.keys(ifaces)) {
    for (const iface of ifaces[name] || []) {
      if (iface.family === 'IPv4' && !iface.internal) {
        return iface.address;
      }
    }
  }
  return '127.0.0.1';
}

let mainWindow;
let instanceId = uuidv4();
let instanceName = os.hostname();

// Simple persisted config
let config = { pythonPath: process.env.PYTHON || 'python3', wsPort: 8765 };
let wsPort = config.wsPort;
let configPath; // initialized after app.whenReady

let devices = new Map(); // instId -> {name, ip, ws_port, last_seen}
let udpSocket;
let beaconTimer;
let pruneTimer;

let serverProc = null;
let clientProc = null;
let serverStarted = false;

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 800,
    height: 520,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js')
    },
    title: 'KVM Control'
  });
  mainWindow.loadFile(path.join(__dirname, 'renderer', 'index.html'));
}

function startDiscovery() {
  udpSocket = dgram.createSocket({ type: 'udp4', reuseAddr: true });
  udpSocket.on('error', (err) => console.error('UDP error', err));
  udpSocket.on('message', (msgBuf, rinfo) => {
    let msg;
    try { msg = JSON.parse(msgBuf.toString('utf8')); } catch { return; }
    if (!msg || typeof msg !== 'object') return;
    const type = msg.type;
    if (type === 'BEACON') {
      const inst = msg.instance_id;
      if (!inst || inst === instanceId) return;
      const info = {
        name: msg.name || 'Unbekannt',
        ip: msg.ip || rinfo.address,
        ws_port: Number(msg.ws_port || 8765),
        last_seen: Date.now(),
        instance_id: inst
      };
      devices.set(inst, info);
      sendDevicesToUi();
    } else if (type === 'REQUEST_CONTROL') {
      const to = msg.to;
      if (to && to !== instanceId) return;
      // Prompt user for approval
      const host = msg.ws_host;
      const port = Number(msg.ws_port || 8765);
      const name = msg.name || host;
      dialog.showMessageBox(mainWindow, {
        type: 'question',
        buttons: ['Erlauben', 'Ablehnen'],
        defaultId: 0,
        cancelId: 1,
        title: 'Remote-Zugriff',
        message: `${name} möchte diesen Rechner steuern. Erlauben?`
      }).then((res) => {
        const accepted = res.response === 0;
        sendResponse(rinfo.address, { accepted });
        if (accepted) {
          // Start client to connect to the requester's server
          startClient(host, port, msg.options || {});
          sendStatusToUi('Als Client verbunden');
        }
      });
    } else if (type === 'RESPONSE_CONTROL') {
      // Forward to UI so it can update state
      sendDevicesToUi({ _response: { msg, addr: rinfo } });
    }
  });
  udpSocket.bind(MCAST_PORT, () => {
    try { udpSocket.addMembership(MCAST_GRP); } catch {}
  });

  // Beacon sender
  beaconTimer = setInterval(() => {
    const payload = JSON.stringify({
      type: 'BEACON',
      instance_id: instanceId,
      name: instanceName,
      ip: getPrimaryIp(),
      ws_port: wsPort,
      version: 1
    });
    udpSocket.send(Buffer.from(payload, 'utf8'), MCAST_PORT, MCAST_GRP);
  }, BEACON_INTERVAL);

  // Prune stale devices
  pruneTimer = setInterval(() => {
    const now = Date.now();
    let removed = false;
    for (const [inst, info] of Array.from(devices.entries())) {
      if (now - (info.last_seen || now) > DEVICE_TTL) {
        devices.delete(inst);
        removed = true;
      }
    }
    if (removed) sendDevicesToUi();
  }, 2000);
}

function stopDiscovery() {
  clearInterval(beaconTimer); beaconTimer = null;
  clearInterval(pruneTimer); pruneTimer = null;
  try { udpSocket.dropMembership(MCAST_GRP); } catch {}
  try { udpSocket.close(); } catch {}
  udpSocket = null;
}

function sendRequest(targetIp, payload) {
  const enriched = {
    ...payload,
    ws_host: getPrimaryIp(),
    ws_port: wsPort
  };
  const buf = Buffer.from(JSON.stringify({
    ...enriched,
    type: 'REQUEST_CONTROL',
    from: instanceId
  }), 'utf8');
  try { udpSocket.send(buf, MCAST_PORT, targetIp); } catch {}
}

function sendResponse(targetIp, payload) {
  const buf = Buffer.from(JSON.stringify({
    ...payload,
    type: 'RESPONSE_CONTROL',
    from: instanceId
  }), 'utf8');
  try { udpSocket.send(buf, MCAST_PORT, targetIp); } catch {}
}

function sendDevicesToUi(extra) {
  if (!mainWindow) return;
  const list = Array.from(devices.values()).sort((a, b) => a.name.localeCompare(b.name));
  mainWindow.webContents.send('devices:update', { devices: list, extra });
}

function sendStatusToUi(text) {
  if (!mainWindow) return;
  mainWindow.webContents.send('status:update', text);
}

function startServer(options) {
  if (serverStarted) return;
  serverStarted = true;
  const python = getPythonCmd();
  const serverPath = path.join(path.dirname(__dirname), 'server.py');
  const args = [serverPath, '--host', '0.0.0.0', '--port', String(wsPort), '--hotkey', options.hotkey || 'f13', '--start-capturing'];
  if (options.noTxMouse) args.push('--no-tx-mouse');
  if (options.noTxKeyboard) args.push('--no-tx-keyboard');
  serverProc = spawn(python, args, { stdio: 'ignore' });
  serverProc.on('exit', () => { serverStarted = false; serverProc = null; sendStatusToUi('Server beendet'); });
  sendStatusToUi(`Server gestartet auf Port ${wsPort}`);
}

function stopServer() {
  if (serverProc) { try { serverProc.kill(); } catch {} }
  serverProc = null; serverStarted = false;
}

function startClient(host, port, options) {
  const python = getPythonCmd();
  const clientPath = path.join(path.dirname(__dirname), 'client.py');
  const args = [clientPath, host, '--port', String(port || 8765), '--map', options.map || 'relative', '--interp-rate-hz', String(options.interp_rate_hz || 240), '--interp-step-px', String(options.interp_step_px || 10), '--deadzone-px', String(options.deadzone_px || 1), '--speed', String(options.speed || 1.0)];
  if (options.interp) args.splice(5, 0, '--interp');
  clientProc = spawn(python, args, { stdio: 'ignore' });
  clientProc.on('exit', () => { clientProc = null; sendStatusToUi('Client getrennt'); });
}

function stopClient() {
  if (clientProc) { try { clientProc.kill(); } catch {} }
  clientProc = null;
}

// IPC wiring
ipcMain.handle('server:start', (e, options) => startServer(options || {}));
ipcMain.handle('server:stop', () => stopServer());
ipcMain.handle('server:setPort', (e, newPort) => {
  const p = Number(newPort);
  if (!Number.isFinite(p) || p <= 0) return;
  wsPort = p; config.wsPort = p; saveConfig();
  if (serverProc) { stopServer(); startServer({}); }
});
ipcMain.handle('client:stop', () => stopClient());
ipcMain.handle('request:control', (e, payload) => {
  const ip = payload.ip;
  const body = payload.body || { options: payload.options || {} };
  if (!body.options) body.options = payload.options || {};
  sendRequest(ip, body);
});
ipcMain.handle('manual:request', (e, payload) => {
  const host = payload.host;
  const body = payload.body || { options: payload.options || {} };
  if (!body.options) body.options = payload.options || {};
  sendRequest(host, body);
});

// Setup & config
function loadConfig() {
  try {
    const raw = fs.readFileSync(configPath, 'utf8');
    const parsed = JSON.parse(raw);
    config = { ...config, ...parsed };
  } catch {}
}
function saveConfig() {
  try { fs.mkdirSync(path.dirname(configPath), { recursive: true }); fs.writeFileSync(configPath, JSON.stringify(config, null, 2)); } catch {}
}
ipcMain.handle('config:get', () => ({ ...config }));
ipcMain.handle('config:setPython', (e, pythonPath) => { config.pythonPath = pythonPath; saveConfig(); });
ipcMain.handle('python:choose', async () => {
  const res = await dialog.showOpenDialog(mainWindow, { properties: ['openFile'], title: 'Select Python Interpreter' });
  if (res.canceled || !res.filePaths?.length) return null;
  const p = res.filePaths[0]; config.pythonPath = p; saveConfig();
  return p;
});
ipcMain.handle('setup:run', async () => {
  const python = getPythonCmd();
  const cwd = path.dirname(__dirname);
  const reqPath = path.join(cwd, 'requirements.txt');
  const steps = [
    { cmd: [python, '--version'], label: 'Python Version prüfen' },
    { cmd: [python, '-m', 'pip', '--version'], label: 'Pip prüfen' },
    { cmd: [python, '-m', 'pip', 'install', '-r', reqPath], label: 'Abhängigkeiten installieren' }
  ];
  for (const s of steps) {
    sendStatusToUi(`${s.label}…`);
    await new Promise((resolve) => {
      const proc = spawn(s.cmd[0], s.cmd.slice(1), { cwd });
      proc.stdout.on('data', (d) => mainWindow?.webContents.send('setup:log', d.toString()));
      proc.stderr.on('data', (d) => mainWindow?.webContents.send('setup:log', d.toString()));
      proc.on('exit', () => resolve());
    });
  }
  sendStatusToUi('Setup abgeschlossen');
});
ipcMain.handle('permissions:open', (e, which) => {
  if (process.platform !== 'darwin') return;
  const map = {
    accessibility: 'x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility',
    input: 'x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent'
  };
  const url = map[which];
  if (url) spawn('open', [url]);
});

app.whenReady().then(() => {
  configPath = path.join(app.getPath('userData'), 'config.json');
  loadConfig();
  wsPort = config.wsPort;
  createWindow();
  startDiscovery();
  app.on('activate', () => { if (BrowserWindow.getAllWindows().length === 0) createWindow(); });
});

app.on('window-all-closed', () => {
  stopClient();
  stopServer();
  stopDiscovery();
  if (process.platform !== 'darwin') app.quit();
});

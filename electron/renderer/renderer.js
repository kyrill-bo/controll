const $ = (sel) => document.querySelector(sel);

let devices = [];
let selectedIndex = null;

// Elements
const devicesList = $('#devicesList');
const statusBar = $('#statusBar');
const pythonPath = $('#pythonPath');
const inputPort = $('#inputPort');

// Render devices
function renderDevices() {
  if (!devices.length) {
    devicesList.innerHTML = '<div style="text-align: center; padding: 20px; opacity: 0.5;">Keine Geräte gefunden</div>';
    return;
  }
  devicesList.innerHTML = devices.map((d, i) => `
    <div class="device-item ${i === selectedIndex ? 'selected' : ''}" data-index="${i}">
      <div class="device-name">${d.name}</div>
      <div class="device-ip">${d.ip}:${d.ws_port}</div>
    </div>
  `).join('');
  
  devicesList.querySelectorAll('.device-item').forEach((el, i) => {
    el.onclick = () => { selectedIndex = i; renderDevices(); };
    el.ondblclick = () => requestControl();
  });
}

// Get options from UI
function getOptions() {
  return {
    map: $('#selMap').value,
    interp: $('#chkInterp').checked,
    interp_rate_hz: 240,
    interp_step_px: 10,
    deadzone_px: 1,
    speed: parseFloat($('#numSpeed').value) || 1.0,
    hotkey: $('#selHotkey').value,
    txMouse: true,
    txKeyboard: true
  };
}

// Request control
async function requestControl() {
  if (selectedIndex === null) {
    statusBar.textContent = '⚠️ Bitte ein Gerät auswählen';
    statusBar.className = 'status-bar status-error';
    return;
  }
  const device = devices[selectedIndex];
  const opts = getOptions();
  
  await window.kvm.startServer({ 
    hotkey: opts.hotkey, 
    noTxMouse: !opts.txMouse, 
    noTxKeyboard: !opts.txKeyboard 
  });
  
  window.kvm.requestControl(device.ip, opts);
  statusBar.textContent = '📡 Anfrage gesendet...';
  statusBar.className = 'status-bar';
}

// Manual connect
async function manualConnect() {
  const host = prompt('Ziel-Host oder IP-Adresse:');
  if (!host) return;
  
  const opts = getOptions();
  await window.kvm.startServer({ 
    hotkey: opts.hotkey, 
    noTxMouse: !opts.txMouse, 
    noTxKeyboard: !opts.txKeyboard 
  });
  
  window.kvm.manualRequest(host, opts);
  statusBar.textContent = '📡 Verbinde manuell mit ' + host;
  statusBar.className = 'status-bar';
}

// Button handlers
$('#btnRequest').onclick = requestControl;
$('#btnDisconnect').onclick = () => {
  window.kvm.disconnectClient();
  statusBar.textContent = '✅ Getrennt';
  statusBar.className = 'status-bar status-ok';
};
$('#btnManual').onclick = manualConnect;

$('#btnChoosePython').onclick = async () => {
  const path = await window.kvm.choosePython();
  if (path) pythonPath.textContent = path;
};

$('#btnInstall').onclick = async () => {
  statusBar.textContent = '⚙️ Installiere Abhängigkeiten...';
  statusBar.className = 'status-bar';
  await window.kvm.runSetup();
};

$('#btnOpenAcc').onclick = () => window.kvm.openPermissions('accessibility');
$('#btnOpenInput').onclick = () => window.kvm.openPermissions('input');

inputPort.onchange = () => {
  const port = parseInt(inputPort.value, 10);
  if (port > 0) window.kvm.setServerPort(port);
};

// IPC listeners
window.kvm.onDevicesUpdate((data) => {
  const { devices: list, extra } = data;
  devices = list || [];
  renderDevices();
  
  if (extra?._response) {
    const accepted = extra._response.msg.accepted;
    statusBar.textContent = accepted ? '✅ Verbunden!' : '❌ Verbindung abgelehnt';
    statusBar.className = accepted ? 'status-bar status-ok' : 'status-bar status-error';
  }
});

window.kvm.onStatusUpdate((text) => {
  statusBar.textContent = text;
  statusBar.className = 'status-bar';
});

window.kvm.onSetupLog((log) => {
  console.log('[Setup]', log);
});

// Initialize
(async () => {
  const cfg = await window.kvm.getConfig();
  if (cfg?.pythonPath) pythonPath.textContent = cfg.pythonPath;
  if (cfg?.wsPort) inputPort.value = cfg.wsPort;
})();

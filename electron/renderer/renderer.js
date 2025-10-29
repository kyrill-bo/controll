const $ = (sel) => document.querySelector(sel);
const devicesEl = $('#devices');
const statusEl = $('#status');

let devices = [];
let selected = null;

function renderDevices() {
  devicesEl.innerHTML = '';
  devices.forEach((d, i) => {
    const row = document.createElement('div');
    row.className = 'device';
    row.dataset.index = i;
    const left = document.createElement('div');
    left.textContent = `${d.name}`;
    const right = document.createElement('div');
    right.textContent = `${d.ip}:${d.ws_port}`;
    row.appendChild(left); row.appendChild(right);
    row.onclick = () => {
      selected = i;
      for (const el of devicesEl.querySelectorAll('.device')) el.style.background = '';
      row.style.background = '#daf0ff';
    };
    row.ondblclick = () => doRequest();
    devicesEl.appendChild(row);
  });
}

function getOptions() {
  return {
    map: $('#selMap').value,
    interp: $('#chkInterp').checked,
    interp_rate_hz: parseInt($('#numRate').value, 10) || 240,
    interp_step_px: parseInt($('#numStep').value, 10) || 10,
    deadzone_px: parseInt($('#numDead').value, 10) || 1,
    speed: parseFloat($('#numSpeed').value) || 1.0,
    hotkey: $('#selHotkey').value,
    txMouse: $('#chkTxMouse').checked,
    txKeyboard: $('#chkTxKeyboard').checked
  };
}

function doRequest() {
  if (selected == null) {
    alert('Bitte ein Gerät auswählen.');
    return;
  }
  const d = devices[selected];
  const opts = getOptions();
  // Ensure server running
  window.kvm.startServer({ hotkey: opts.hotkey, noTxMouse: !opts.txMouse, noTxKeyboard: !opts.txKeyboard });
  // Let main enrich with ws_host/ws_port
  window.kvm.requestControl(d.ip, {
    map: opts.map,
    interp: opts.interp,
    interp_rate_hz: opts.interp_rate_hz,
    interp_step_px: opts.interp_step_px,
    deadzone_px: opts.deadzone_px,
    speed: opts.speed
  });
  statusEl.textContent = 'Anfrage gesendet – warte auf Bestätigung…';
}

$('#btnRequest').onclick = doRequest;
$('#btnDisconnect').onclick = () => window.kvm.disconnectClient();
$('#btnManual').onclick = () => {
  const host = prompt('Ziel-Host/IP:');
  if (!host) return;
  const opts = getOptions();
  window.kvm.startServer({ hotkey: opts.hotkey, noTxMouse: !opts.txMouse, noTxKeyboard: !opts.txKeyboard });
  window.kvm.manualRequest(host, {
    map: opts.map,
    interp: opts.interp,
    interp_rate_hz: opts.interp_rate_hz,
    interp_step_px: opts.interp_step_px,
    deadzone_px: opts.deadzone_px,
    speed: opts.speed
  });
  statusEl.textContent = 'Anfrage gesendet – warte auf Bestätigung…';
};
$('#btnStartServer').onclick = () => {
  const opts = getOptions();
  window.kvm.startServer({ hotkey: opts.hotkey, noTxMouse: !opts.txMouse, noTxKeyboard: !opts.txKeyboard });
};
$('#btnStopServer').onclick = () => window.kvm.stopServer && window.kvm.stopServer();

window.kvm.onDevicesUpdate((data) => {
  const { devices: list, extra } = data;
  devices = list || [];
  renderDevices();
  if (extra && extra._response) {
    const accepted = !!extra._response.msg.accepted;
    statusEl.textContent = accepted ? 'Freigabe erteilt – Remote aktiv' : 'Freigabe abgelehnt';
  }
});

window.kvm.onStatusUpdate((text) => {
  statusEl.textContent = text;
});

// Setup UI wiring
const lblPython = $('#lblPython');
const numPort = $('#numPort');
$('#btnChoosePy').onclick = async () => {
  const p = await window.kvm.choosePython();
  if (p) lblPython.textContent = `Python: ${p}`;
};
$('#btnInstallDeps').onclick = async () => {
  statusEl.textContent = 'Setup läuft…';
  await window.kvm.runSetup();
};
$('#btnOpenAcc').onclick = () => window.kvm.openPermissions('accessibility');
$('#btnOpenInput').onclick = () => window.kvm.openPermissions('input');
$('#btnApplyPort').onclick = () => {
  const p = parseInt(numPort.value, 10);
  if (!p || p <= 0) return alert('Bitte gültigen Port angeben.');
  window.kvm.setServerPort(p);
};

// Initialize config view
(async () => {
  const cfg = await window.kvm.getConfig();
  if (cfg?.pythonPath) lblPython.textContent = `Python: ${cfg.pythonPath}`;
  if (cfg?.wsPort) numPort.value = cfg.wsPort;
})();

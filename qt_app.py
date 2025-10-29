#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Qt GUI for KVM Control (PySide6)
- Multicast discovery (BEACON)
- Request/approval flow via UDP
- Spawns Python server.py and client.py as subprocesses (QProcess)
- Compact, native-feeling UI; avoids Electron

Run: python3 qt_app.py
"""
import sys
import os
import json
import uuid
import time
import socket
from dataclasses import dataclass
from typing import Dict

from PySide6 import QtCore, QtWidgets, QtNetwork

MCAST_GRP = '239.255.255.250'
MCAST_PORT = 54545
BEACON_INTERVAL_MS = 2000
DEVICE_TTL_MS = BEACON_INTERVAL_MS * 3 + 2000


def get_primary_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'


@dataclass
class Device:
    instance_id: str
    name: str
    ip: str
    ws_port: int
    last_seen: float


class Discovery(QtCore.QObject):
    devicesChanged = QtCore.Signal(dict)
    requestReceived = QtCore.Signal(dict, str)  # (request msg, sender ip)
    responseReceived = QtCore.Signal(dict, str)

    def __init__(self, instance_id: str, name: str, ws_port: int, parent=None):
        super().__init__(parent)
        self.instance_id = instance_id
        self.name = name
        self.ws_port = ws_port
        self._devices: Dict[str, Device] = {}

        self.sock = QtNetwork.QUdpSocket(self)
        # Reuse address
        self.sock.bind(QtNetwork.QHostAddress.AnyIPv4, MCAST_PORT, QtNetwork.QUdpSocket.ShareAddress | QtNetwork.QUdpSocket.ReuseAddressHint)
        # Join multicast
        self.sock.joinMulticastGroup(QtNetwork.QHostAddress(MCAST_GRP))
        self.sock.readyRead.connect(self._on_ready_read)

        # Beacon + prune timers
        self.beacon_timer = QtCore.QTimer(self)
        self.beacon_timer.timeout.connect(self._send_beacon)
        self.beacon_timer.start(BEACON_INTERVAL_MS)

        self.prune_timer = QtCore.QTimer(self)
        self.prune_timer.timeout.connect(self._prune_devices)
        self.prune_timer.start(2000)

        # Kick initial update
        QtCore.QTimer.singleShot(100, self._send_beacon)

    def _send(self, payload: dict, target_ip: str):
        data = json.dumps(payload).encode('utf-8')
        self.sock.writeDatagram(data, QtNetwork.QHostAddress(target_ip), MCAST_PORT)

    def _broadcast(self, payload: dict):
        data = json.dumps(payload).encode('utf-8')
        # Multicast
        self.sock.writeDatagram(data, QtNetwork.QHostAddress(MCAST_GRP), MCAST_PORT)
        # Broadcast fallback
        self.sock.writeDatagram(data, QtNetwork.QHostAddress.Broadcast, MCAST_PORT)

    def _send_beacon(self):
        msg = {
            'type': 'BEACON',
            'instance_id': self.instance_id,
            'name': self.name,
            'ip': get_primary_ip(),
            'ws_port': self.ws_port,
            'version': 1,
        }
        self._broadcast(msg)

    def _prune_devices(self):
        now = time.time() * 1000
        removed = False
        for inst, dev in list(self._devices.items()):
            if now - dev.last_seen > DEVICE_TTL_MS:
                del self._devices[inst]
                removed = True
        if removed:
            self.devicesChanged.emit({k: vars(v) for k, v in self._devices.items()})

    def _on_ready_read(self):
        while self.sock.hasPendingDatagrams():
            datagram, host, port = self.sock.readDatagram(self.sock.pendingDatagramSize())
            try:
                msg = json.loads(datagram.decode('utf-8'))
            except Exception:
                continue
            if not isinstance(msg, dict):
                continue
            mtype = msg.get('type')
            if mtype == 'BEACON':
                inst = msg.get('instance_id')
                if not inst or inst == self.instance_id:
                    continue
                dev = Device(
                    instance_id=inst,
                    name=msg.get('name', 'Unbekannt'),
                    ip=msg.get('ip', host.toString()),
                    ws_port=int(msg.get('ws_port', 8765)),
                    last_seen=time.time()*1000
                )
                self._devices[inst] = dev
                self.devicesChanged.emit({k: vars(v) for k, v in self._devices.items()})
            elif mtype == 'REQUEST_CONTROL':
                to = msg.get('to')
                if to and to != self.instance_id:
                    continue
                self.requestReceived.emit(msg, host.toString())
            elif mtype == 'RESPONSE_CONTROL':
                self.responseReceived.emit(msg, host.toString())

    def send_request(self, target_ip: str, options: dict, to: str | None = None):
        msg = {
            'type': 'REQUEST_CONTROL',
            'from': self.instance_id,
            'to': to,
            'name': self.name,
            'ws_host': get_primary_ip(),
            'ws_port': self.ws_port,
            'options': options,
        }
        self._send(msg, target_ip)

    def send_response(self, target_ip: str, accepted: bool):
        msg = {
            'type': 'RESPONSE_CONTROL',
            'from': self.instance_id,
            'accepted': bool(accepted),
        }
        self._send(msg, target_ip)


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('KVM Control')
        self.setFixedSize(900, 600)

        # Identity
        self.instance_id = str(uuid.uuid4())
        self.name = socket.gethostname()
        self.ws_port = 8765

        # Processes
        self.server_proc = QtCore.QProcess(self)
        self.client_proc = QtCore.QProcess(self)

        # UI
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        v = QtWidgets.QVBoxLayout(central)

        # Setup row
        setup_box = QtWidgets.QGroupBox('Setup')
        v.addWidget(setup_box)
        setup = QtWidgets.QGridLayout(setup_box)
        self.lbl_python = QtWidgets.QLabel(sys.executable)
        setup.addWidget(QtWidgets.QLabel('Python:'), 0, 0)
        setup.addWidget(self.lbl_python, 0, 1)
        self.btn_install = QtWidgets.QPushButton('Abhängigkeiten installieren')
        setup.addWidget(self.btn_install, 0, 2)
        setup.addWidget(QtWidgets.QLabel('WS-Port:'), 1, 0)
        self.spin_port = QtWidgets.QSpinBox()
        self.spin_port.setRange(1024, 65535)
        self.spin_port.setValue(self.ws_port)
        setup.addWidget(self.spin_port, 1, 1)
        self.btn_apply_port = QtWidgets.QPushButton('Übernehmen')
        setup.addWidget(self.btn_apply_port, 1, 2)

        # Devices
        dev_box = QtWidgets.QGroupBox('Verfügbare Geräte')
        v.addWidget(dev_box)
        dev_layout = QtWidgets.QVBoxLayout(dev_box)
        self.list = QtWidgets.QListWidget()
        dev_layout.addWidget(self.list)
        row = QtWidgets.QHBoxLayout()
        self.btn_request = QtWidgets.QPushButton('Steuerung anfordern')
        self.btn_manual = QtWidgets.QPushButton('Manuell verbinden…')
        self.btn_disconnect = QtWidgets.QPushButton('Trennen')
        row.addWidget(self.btn_request)
        row.addWidget(self.btn_manual)
        row.addWidget(self.btn_disconnect)
        dev_layout.addLayout(row)

        # Settings
        set_box = QtWidgets.QGroupBox('Einstellungen')
        v.addWidget(set_box)
        grid = QtWidgets.QGridLayout(set_box)
        self.combo_map = QtWidgets.QComboBox(); self.combo_map.addItems(['relative','normalized','preserve'])
        self.chk_interp = QtWidgets.QCheckBox('Interpolation'); self.chk_interp.setChecked(True)
        self.spin_rate = QtWidgets.QSpinBox(); self.spin_rate.setRange(30,1000); self.spin_rate.setValue(240)
        self.spin_step = QtWidgets.QSpinBox(); self.spin_step.setRange(1,200); self.spin_step.setValue(10)
        self.spin_dead = QtWidgets.QSpinBox(); self.spin_dead.setRange(0,20); self.spin_dead.setValue(1)
        self.dbl_speed = QtWidgets.QDoubleSpinBox(); self.dbl_speed.setRange(0.1,5.0); self.dbl_speed.setSingleStep(0.1); self.dbl_speed.setValue(1.0)
        self.combo_hotkey = QtWidgets.QComboBox(); self.combo_hotkey.addItems(['f13','f12','f11','f14'])
        self.chk_tx_mouse = QtWidgets.QCheckBox('Maus senden'); self.chk_tx_mouse.setChecked(True)
        self.chk_tx_kb = QtWidgets.QCheckBox('Tastatur senden'); self.chk_tx_kb.setChecked(True)
        labels = ['Mapping','Rate (Hz)','Schritt (px)','Deadzone (px)','Speed ×','Hotkey','Übertragen']
        widgets = [self.combo_map, self.spin_rate, self.spin_step, self.spin_dead, self.dbl_speed, self.combo_hotkey]
        for i,(lab, w) in enumerate(zip(labels, widgets)):
            grid.addWidget(QtWidgets.QLabel(lab+':'), i, 0); grid.addWidget(w, i, 1)
        grid.addWidget(self.chk_interp, 0, 2)
        grid.addWidget(self.chk_tx_mouse, 5, 2)
        grid.addWidget(self.chk_tx_kb, 6, 2)

        # Status
        self.lbl_status = QtWidgets.QLabel('Bereit')
        v.addWidget(self.lbl_status)

        # Discovery
        self.discovery = Discovery(self.instance_id, self.name, self.ws_port, self)
        self.discovery.devicesChanged.connect(self.on_devices_changed)
        self.discovery.requestReceived.connect(self.on_request_received)
        self.discovery.responseReceived.connect(self.on_response_received)

        # Signals
        self.list.itemDoubleClicked.connect(self.request_control)
        self.btn_request.clicked.connect(self.request_control)
        self.btn_manual.clicked.connect(self.manual_connect)
        self.btn_disconnect.clicked.connect(self.disconnect_client)
        self.btn_apply_port.clicked.connect(self.apply_port)
        self.btn_install.clicked.connect(self.install_requirements)

        # QProcess logging
        self.server_proc.readyReadStandardOutput.connect(lambda: self._proc_log(self.server_proc, '[Server]'))
        self.server_proc.readyReadStandardError.connect(lambda: self._proc_log(self.server_proc, '[Server]'))
        self.client_proc.readyReadStandardOutput.connect(lambda: self._proc_log(self.client_proc, '[Client]'))
        self.client_proc.readyReadStandardError.connect(lambda: self._proc_log(self.client_proc, '[Client]'))
        self.server_proc.finished.connect(lambda code, _s: self._set_status(f'Server beendet ({code})'))
        self.client_proc.finished.connect(lambda code, _s: self._set_status(f'Client beendet ({code})'))

    def _set_status(self, text: str):
        self.lbl_status.setText(text)

    def _proc_log(self, proc: QtCore.QProcess, prefix: str):
        data = bytes(proc.readAllStandardOutput()).decode('utf-8') + bytes(proc.readAllStandardError()).decode('utf-8')
        if data.strip():
            print(prefix, data.strip())
            self._set_status(prefix + ' ' + data.strip()[:100])

    def apply_port(self):
        self.ws_port = int(self.spin_port.value())
        self.discovery.ws_port = self.ws_port
        # Restart server if running
        if self.server_proc.state() != QtCore.QProcess.NotRunning:
            try:
                self.server_proc.kill()
            except Exception:
                pass
            self.start_server()

    def on_devices_changed(self, devices: dict):
        self.list.clear()
        for inst, info in sorted(devices.items(), key=lambda kv: kv[1]['name']):
            item = QtWidgets.QListWidgetItem(f"{info['name']}  {info['ip']}:{info['ws_port']}  [{inst[:8]}]")
            item.setData(QtCore.Qt.UserRole, (inst, info))
            self.list.addItem(item)

    def on_request_received(self, req: dict, addr: str):
        name = req.get('name', addr)
        host = req.get('ws_host')
        port = int(req.get('ws_port', 8765))
        options = req.get('options', {})
        ans = QtWidgets.QMessageBox.question(self, 'Remote-Zugriff', f"{name} möchte diesen Rechner steuern. Erlauben?",
                                             QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
        self.discovery.send_response(addr, ans == QtWidgets.QMessageBox.Yes)
        if ans == QtWidgets.QMessageBox.Yes:
            self.start_client(host, port, options)
            self._set_status('Als Client verbunden')

    def on_response_received(self, resp: dict, _addr: str):
        if resp.get('accepted'):
            self._set_status('Freigabe erteilt – Remote aktiv')
        else:
            self._set_status('Freigabe abgelehnt')

    def current_options(self) -> dict:
        return {
            'map': self.combo_map.currentText(),
            'interp': self.chk_interp.isChecked(),
            'interp_rate_hz': int(self.spin_rate.value()),
            'interp_step_px': int(self.spin_step.value()),
            'deadzone_px': int(self.spin_dead.value()),
            'speed': float(self.dbl_speed.value()),
        }

    def request_control(self):
        item = self.list.currentItem()
        if not item:
            self._set_status('Bitte ein Gerät wählen')
            return
        inst, info = item.data(QtCore.Qt.UserRole)
        # Ensure server running
        self.start_server()
        self.discovery.send_request(info['ip'], self.current_options(), to=inst)
        self._set_status('Anfrage gesendet – warte auf Bestätigung…')

    def manual_connect(self):
        host, ok = QtWidgets.QInputDialog.getText(self, 'Manuell verbinden', 'Ziel-Host/IP:')
        if not ok or not host:
            return
        # Ensure server running
        self.start_server()
        self.discovery.send_request(host, self.current_options(), to=None)
        self._set_status('Anfrage gesendet – warte auf Bestätigung…')

    def start_server(self):
        if self.server_proc.state() != QtCore.QProcess.NotRunning:
            return
        args = [os.path.join(os.path.dirname(__file__), 'server.py'), '--host', '0.0.0.0', '--port', str(self.ws_port), '--hotkey', self.combo_hotkey.currentText(), '--start-capturing']
        if not self.chk_tx_mouse.isChecked():
            args.append('--no-tx-mouse')
        if not self.chk_tx_kb.isChecked():
            args.append('--no-tx-keyboard')
        self.server_proc.start(sys.executable, args)
        self._set_status(f'Server gestartet auf Port {self.ws_port}')

    def start_client(self, host: str, port: int, options: dict):
        if self.client_proc.state() != QtCore.QProcess.NotRunning:
            try:
                self.client_proc.kill()
            except Exception:
                pass
        args = [os.path.join(os.path.dirname(__file__), 'client.py'), host, '--port', str(port), '--map', options.get('map','relative'),
                '--interp-rate-hz', str(int(options.get('interp_rate_hz',240))), '--interp-step-px', str(int(options.get('interp_step_px',10))),
                '--deadzone-px', str(int(options.get('deadzone_px',1))), '--speed', str(float(options.get('speed',1.0)))]
        if options.get('interp', True):
            args.insert(6, '--interp')
        self.client_proc.start(sys.executable, args)

    def disconnect_client(self):
        if self.client_proc.state() != QtCore.QProcess.NotRunning:
            try:
                self.client_proc.kill()
            except Exception:
                pass
            self._set_status('Client getrennt')
        else:
            self._set_status('Kein aktiver Client')

    def install_requirements(self):
        # Run: python -m pip install -r requirements.txt
        proc = QtCore.QProcess(self)
        proc.readyReadStandardOutput.connect(lambda: print('[Setup]', bytes(proc.readAllStandardOutput()).decode()))
        proc.readyReadStandardError.connect(lambda: print('[Setup]', bytes(proc.readAllStandardError()).decode()))
        proc.start(sys.executable, ['-m', 'pip', 'install', '-r', os.path.join(os.path.dirname(__file__), 'requirements.txt')])


def main():
    app = QtWidgets.QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GUI for KVM Control (PySimpleGUI)
- Multicast discovery (BEACON)
- Request/approval flow via UDP
- Spawns Python server.py and client.py as subprocesses
- Compact, native-feeling UI

Run: python3 qt_app.py
"""
import sys
import os
import json
import uuid
import time
import socket
import subprocess
import threading
from dataclasses import dataclass
from typing import Dict

import FreeSimpleGUI as sg

MCAST_GRP = '239.255.255.250'
MCAST_PORT = 54545
BEACON_INTERVAL_S = 2
DEVICE_TTL_S = BEACON_INTERVAL_S * 3 + 2


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


class Discovery(threading.Thread):
    def __init__(self, instance_id: str, name: str, ws_port: int, window: sg.Window):
        super().__init__(daemon=True)
        self.instance_id = instance_id
        self.name = name
        self.ws_port = ws_port
        self.window = window
        self._devices: Dict[str, Device] = {}
        self.sock = self._create_socket()
        self._running = True

    def _create_socket(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(('', MCAST_PORT))
        mreq = socket.inet_aton(MCAST_GRP) + socket.inet_aton('0.0.0.0')
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        sock.settimeout(1.0)
        return sock

    def run(self):
        last_beacon = 0
        last_prune = 0

        while self._running:
            now = time.time()
            if now - last_beacon > BEACON_INTERVAL_S:
                self._send_beacon()
                last_beacon = now

            if now - last_prune > 2:
                self._prune_devices()
                last_prune = now

            try:
                data, addr = self.sock.recvfrom(1024)
                self._handle_message(data, addr[0])
            except socket.timeout:
                continue
            except Exception as e:
                print(f"[Discovery] Error: {e}")

    def stop(self):
        self._running = False

    def _send(self, payload: dict, target_ip: str):
        data = json.dumps(payload).encode('utf-8')
        self.sock.sendto(data, (target_ip, MCAST_PORT))

    def _broadcast(self, payload: dict):
        data = json.dumps(payload).encode('utf-8')
        self.sock.sendto(data, (MCAST_GRP, MCAST_PORT))

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
        now = time.time()
        removed = False
        for inst, dev in list(self._devices.items()):
            if now - dev.last_seen > DEVICE_TTL_S:
                del self._devices[inst]
                removed = True
        if removed:
            self.window.write_event_value(('-DEVICES_CHANGED-', {k: vars(v) for k, v in self._devices.items()}), None)

    def _handle_message(self, data: bytes, addr: str):
        try:
            msg = json.loads(data.decode('utf-8'))
        except Exception:
            return
        if not isinstance(msg, dict):
            return
        mtype = msg.get('type')
        if mtype == 'BEACON':
            inst = msg.get('instance_id')
            if not inst or inst == self.instance_id:
                return
            dev = Device(
                instance_id=inst,
                name=msg.get('name', 'Unknown'),
                ip=msg.get('ip', addr),
                ws_port=int(msg.get('ws_port', 8765)),
                last_seen=time.time()
            )
            if self._devices.get(inst) != dev:
                self._devices[inst] = dev
                self.window.write_event_value(('-DEVICES_CHANGED-', {k: vars(v) for k, v in self._devices.items()}), None)

        elif mtype == 'REQUEST_CONTROL':
            to = msg.get('to')
            if to and to != self.instance_id:
                return
            self.window.write_event_value(('-REQUEST_RECEIVED-', (msg, addr)), None)
        elif mtype == 'RESPONSE_CONTROL':
            self.window.write_event_value(('-RESPONSE_RECEIVED-', (msg, addr)), None)

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


class App:
    def __init__(self):
        self.instance_id = str(uuid.uuid4())
        self.name = socket.gethostname()
        self.ws_port = 8765
        self.server_proc = None
        self.client_proc = None
        self.discovery = None

        sg.theme('DarkBlue')

        setup_layout = [
            [sg.Text('Python:'), sg.Text(sys.executable, key='-PYTHON-')],
            [sg.Text('WS-Port:'), sg.Spin(list(range(1024, 65535)), initial_value=self.ws_port, key='-WS_PORT-'),
             sg.Button('Apply', key='-APPLY_PORT-')],
            [sg.Button('Install Dependencies', key='-INSTALL-')]
        ]

        devices_layout = [
            [sg.Listbox([], size=(60, 10), key='-DEVICES-', enable_events=True)],
            [sg.Button('Request Control', key='-REQUEST-'), sg.Button('Manual Connect...', key='-MANUAL-'),
             sg.Button('Disconnect', key='-DISCONNECT-')]
        ]

        settings_layout = [
            [sg.Text('Mapping:'), sg.Combo(['relative', 'normalized', 'preserve'], default_value='relative', key='-MAP-')],
            [sg.Text('Rate (Hz):'), sg.Spin(list(range(30, 1001)), initial_value=240, key='-RATE-')],
            [sg.Text('Step (px):'), sg.Spin(list(range(1, 201)), initial_value=10, key='-STEP-')],
            [sg.Text('Deadzone (px):'), sg.Spin(list(range(0, 21)), initial_value=1, key='-DEADZONE-')],
            [sg.Text('Speed ×:'), sg.Spin([f'{i/10:.1f}' for i in range(1, 51)], initial_value='1.0', key='-SPEED-')],
            [sg.Text('Hotkey:'), sg.Combo(['f13', 'f12', 'f11', 'f14'], default_value='f13', key='-HOTKEY-')],
            [sg.Checkbox('Interpolation', default=True, key='-INTERP-'),
             sg.Checkbox('Send Mouse', default=True, key='-TX_MOUSE-'),
             sg.Checkbox('Send Keyboard', default=True, key='-TX_KB-')]
        ]

        layout = [
            [sg.Frame('Setup', setup_layout)],
            [sg.Frame('Available Devices', devices_layout)],
            [sg.Frame('Settings', settings_layout)],
            [sg.StatusBar('Ready', key='-STATUS-')]
        ]

        self.window = sg.Window('KVM Control', layout, finalize=True)
        self.discovery = Discovery(self.instance_id, self.name, self.ws_port, self.window)
        self.discovery.start()

    def _set_status(self, text: str):
        self.window['-STATUS-'].update(text)

    def _get_script_path(self, name: str) -> str:
        return os.path.join(os.path.dirname(__file__), name)

    def handle_event(self, event, values):
        if event == sg.WIN_CLOSED:
            return False
        elif event == '-DEVICES_CHANGED-':
            devices = values[event]
            self.window['-DEVICES-'].update([f"{info['name']}  {info['ip']}:{info['ws_port']}  [{inst[:8]}]" for inst, info in sorted(devices.items(), key=lambda kv: kv[1]['name'])],
                                           set_to_index=0 if devices else None)
        elif event == '-REQUEST_RECEIVED-':
            req, addr = values[event]
            name = req.get('name', addr)
            if sg.popup_yes_no(f'{name} wants to control this computer. Allow?', title='Remote Access') == 'Yes':
                self.discovery.send_response(addr, True)
                self.start_client(req.get('ws_host'), int(req.get('ws_port', 8765)), req.get('options', {}))
                self._set_status('Connected as client')
            else:
                self.discovery.send_response(addr, False)

        elif event == '-RESPONSE_RECEIVED-':
            resp, _addr = values[event]
            if resp.get('accepted'):
                self._set_status('Control granted - Remote active')
            else:
                self._set_status('Control denied')

        elif event == '-APPLY_PORT-':
            self.ws_port = int(values['-WS_PORT-'])
            self.discovery.ws_port = self.ws_port
            if self.server_proc:
                self.server_proc.kill()
                self.server_proc = None
            self.start_server()

        elif event == '-INSTALL-':
            self.install_requirements()

        elif event == '-REQUEST-':
            if not values['-DEVICES-']:
                self._set_status('Please select a device')
                return True
            selected_device_str = values['-DEVICES-'][0]
            # This is a bit fragile, we should store the device info properly
            # For now, let's parse the string
            try:
                ip = selected_device_str.split('  ')[1].split(':')[0]
                inst = selected_device_str.split('[')[1].split(']')[0]
                self.start_server()
                self.discovery.send_request(ip, self.current_options(values), to=inst)
                self._set_status('Request sent - waiting for confirmation...')
            except IndexError:
                self._set_status('Could not parse device info.')


        elif event == '-MANUAL-':
            host = sg.popup_get_text('Enter target host/IP:')
            if host:
                self.start_server()
                self.discovery.send_request(host, self.current_options(values), to=None)
                self._set_status('Request sent - waiting for confirmation...')

        elif event == '-DISCONNECT-':
            self.disconnect_client()

        return True

    def current_options(self, values) -> dict:
        return {
            'map': values['-MAP-'],
            'interp': values['-INTERP-'],
            'interp_rate_hz': int(values['-RATE-']),
            'interp_step_px': int(values['-STEP-']),
            'deadzone_px': int(values['-DEADZONE-']),
            'speed': float(values['-SPEED-']),
        }

    def start_server(self):
        if self.server_proc and self.server_proc.poll() is None:
            return
        args = [sys.executable, self._get_script_path('server.py'), '--host', '0.0.0.0', '--port', str(self.ws_port),
                '--hotkey', self.window['-HOTKEY-'].get(), '--start-capturing']
        if not self.window['-TX_MOUSE-'].get():
            args.append('--no-tx-mouse')
        if not self.window['-TX_KB-'].get():
            args.append('--no-tx-keyboard')
        self.server_proc = subprocess.Popen(args)
        self._set_status(f'Server started on port {self.ws_port}')

    def start_client(self, host: str, port: int, options: dict):
        if self.client_proc and self.client_proc.poll() is None:
            self.client_proc.kill()
        args = [sys.executable, self._get_script_path('client.py'), host, '--port', str(port),
                '--map', options.get('map', 'relative'),
                '--interp-rate-hz', str(int(options.get('interp_rate_hz', 240))),
                '--interp-step-px', str(int(options.get('interp_step_px', 10))),
                '--deadzone-px', str(int(options.get('deadzone_px', 1))),
                '--speed', str(float(options.get('speed', 1.0)))]
        if options.get('interp', True):
            args.insert(6, '--interp')
        self.client_proc = subprocess.Popen(args)

    def disconnect_client(self):
        if self.client_proc and self.client_proc.poll() is None:
            self.client_proc.kill()
            self.client_proc = None
            self._set_status('Client disconnected')
        else:
            self._set_status('No active client')

    def install_requirements(self):
        subprocess.Popen([sys.executable, '-m', 'pip', 'install', '-r', self._get_script_path('requirements.txt')])

    def cleanup(self):
        if self.discovery:
            self.discovery.stop()
            self.discovery.join()
        if self.server_proc:
            self.server_proc.kill()
        if self.client_proc:
            self.client_proc.kill()
        self.window.close()


def main():
    app = App()
    while True:
        event, values = app.window.read()
        if not app.handle_event(event, values):
            break
    app.cleanup()


if __name__ == '__main__':
    main()
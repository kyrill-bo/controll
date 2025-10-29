#!/usr/bin/env python3
"""
KVM Control GUI
- Geräte-Erkennung im lokalen Netz (Multicast Beacon)
- Verbindungsanfrage mit Bestätigung auf dem Zielgerät
- Startet Server/Client mit einstellbaren Optionen
"""
import socket
import struct
import json
import threading
import time
import uuid
import subprocess
import sys
import os
import tkinter as tk
from tkinter import ttk, messagebox

MCAST_GRP = '239.255.255.250'
MCAST_PORT = 54545
BEACON_INTERVAL = 2.0


def get_primary_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'


class DiscoveryService:
    def __init__(self, instance_id: str, name: str, ws_port: int, on_update, on_request):
        self.instance_id = instance_id
        self.name = name
        self.ws_port = ws_port
        self.on_update = on_update  # callback(devices_dict)
        self.on_request = on_request  # callback(request_dict, addr)
        self._stop = threading.Event()
        self._devices = {}
        self._lock = threading.Lock()
        self._ip = get_primary_ip()
        self._sender_thread = None
        self._recv_thread = None

    def start(self):
        self._sender_thread = threading.Thread(target=self._beacon_loop, daemon=True)
        self._recv_thread = threading.Thread(target=self._recv_loop, daemon=True)
        self._sender_thread.start()
        self._recv_thread.start()

    def stop(self):
        self._stop.set()

    def devices(self):
        with self._lock:
            return dict(self._devices)

    def _beacon_loop(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        try:
            # TTL 1 (lokales Netz)
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
            while not self._stop.is_set():
                msg = {
                    'type': 'BEACON',
                    'instance_id': self.instance_id,
                    'name': self.name,
                    'ip': self._ip,
                    'ws_port': self.ws_port,
                    'version': 1,
                }
                data = json.dumps(msg).encode('utf-8')
                try:
                    sock.sendto(data, (MCAST_GRP, MCAST_PORT))
                except Exception:
                    pass
                self._stop.wait(BEACON_INTERVAL)
        finally:
            sock.close()

    def _recv_loop(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(('', MCAST_PORT))
            except OSError:
                # macOS may require binding to group
                sock.bind((MCAST_GRP, MCAST_PORT))
            mreq = struct.pack('4s4s', socket.inet_aton(MCAST_GRP), socket.inet_aton('0.0.0.0'))
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
            sock.settimeout(1.0)
            while not self._stop.is_set():
                try:
                    data, addr = sock.recvfrom(65535)
                except socket.timeout:
                    continue
                try:
                    msg = json.loads(data.decode('utf-8'))
                except Exception:
                    continue
                if not isinstance(msg, dict):
                    continue
                mtype = msg.get('type')
                if mtype == 'BEACON':
                    inst = msg.get('instance_id')
                    if not inst or inst == self.instance_id:
                        continue
                    with self._lock:
                        self._devices[inst] = {
                            'name': msg.get('name', 'Unbekannt'),
                            'ip': msg.get('ip', addr[0]),
                            'ws_port': int(msg.get('ws_port', 8765)),
                            'last_seen': time.time(),
                            'instance_id': inst,
                        }
                    if self.on_update:
                        self.on_update(self.devices())
                elif mtype == 'REQUEST_CONTROL':
                    # Direkt an diese Instanz gerichtet?
                    to = msg.get('to')
                    if to and to != self.instance_id:
                        continue
                    if self.on_request:
                        self.on_request(msg, addr)
                elif mtype == 'RESPONSE_CONTROL':
                    # Erlaubnis-/Ablehnungs-Antwort -> über on_update, GUI kann darauf reagieren
                    if self.on_update:
                        self.on_update({'_response': {'msg': msg, 'addr': addr}})
        finally:
            try:
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_DROP_MEMBERSHIP, mreq)
            except Exception:
                pass
            sock.close()

    def send_request(self, target_ip: str, payload: dict):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        try:
            payload = dict(payload)
            payload['type'] = 'REQUEST_CONTROL'
            payload['from'] = self.instance_id
            data = json.dumps(payload).encode('utf-8')
            sock.sendto(data, (target_ip, MCAST_PORT))
        finally:
            sock.close()

    def send_response(self, target_ip: str, payload: dict):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        try:
            payload = dict(payload)
            payload['type'] = 'RESPONSE_CONTROL'
            payload['from'] = self.instance_id
            data = json.dumps(payload).encode('utf-8')
            sock.sendto(data, (target_ip, MCAST_PORT))
        finally:
            sock.close()


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title('KVM Control')
        self.instance_id = str(uuid.uuid4())
        self.name = socket.gethostname()
        self.ws_port = 8765
        self.server_proc = None
        self.client_proc = None
        self.server_started = False
        self._loop_lock = threading.Lock()

        # Settings
        self.var_speed = tk.DoubleVar(value=1.0)
        self.var_map = tk.StringVar(value='relative')
        self.var_interp = tk.BooleanVar(value=True)
        self.var_interp_rate = tk.IntVar(value=240)
        self.var_interp_step = tk.IntVar(value=10)
        self.var_deadzone = tk.IntVar(value=1)
        self.var_tx_mouse = tk.BooleanVar(value=True)
        self.var_tx_keyboard = tk.BooleanVar(value=True)
        self.var_hotkey = tk.StringVar(value='f13')

        # UI Layout
        frm = ttk.Frame(root, padding=12)
        frm.grid(sticky='nsew')
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)

        ttk.Label(frm, text='Gefundene Geräte:').grid(row=0, column=0, sticky='w')
        self.listbox = tk.Listbox(frm, height=8)
        self.listbox.grid(row=1, column=0, columnspan=3, sticky='nsew', pady=6)
        frm.rowconfigure(1, weight=1)
        frm.columnconfigure(0, weight=1)

        self.btn_connect = ttk.Button(frm, text='Steuerung anfordern', command=self.request_control)
        self.btn_connect.grid(row=2, column=0, sticky='w')
        self.btn_settings = ttk.Button(frm, text='Einstellungen', command=self.open_settings)
        self.btn_settings.grid(row=2, column=1, sticky='w', padx=8)
        self.lbl_status = ttk.Label(frm, text='Bereit')
        self.lbl_status.grid(row=2, column=2, sticky='e')

        # Discovery
        self.discovery = DiscoveryService(
            self.instance_id, self.name, self.ws_port,
            on_update=self.on_discovery_update,
            on_request=self.on_request_control)
        self.discovery.start()
        # Cleanup on close
        self.root.protocol('WM_DELETE_WINDOW', self.on_close)

        # Devices model {instance_id: {...}}
        self.devices = {}

    def on_discovery_update(self, devices_dict):
        # Called from background thread
        def _update():
            if '_response' in devices_dict:
                # Handle incoming response
                r = devices_dict['_response']['msg']
                accepted = r.get('accepted')
                peer = r.get('from')
                if accepted:
                    self.lbl_status.config(text='Freigabe erteilt – Remote aktiv')
                else:
                    self.lbl_status.config(text='Freigabe abgelehnt')
                return
            self.devices = devices_dict
            self.listbox.delete(0, tk.END)
            for inst, info in sorted(self.devices.items(), key=lambda kv: kv[1]['name']):
                self.listbox.insert(tk.END, f"{info['name']}  {info['ip']}:{info['ws_port']}  [{inst[:8]}]")
        self.root.after(0, _update)

    def on_request_control(self, req: dict, addr):
        # Called from background thread on incoming request
        def _prompt():
            requester = req.get('from')
            host = req.get('ws_host')
            port = int(req.get('ws_port', 8765))
            name = req.get('name', host)
            options = req.get('options', {})
            ans = messagebox.askyesno('Remote-Zugriff', f"{name} möchte diesen Rechner steuern. Erlauben?")
            self.discovery.send_response(addr[0], {'accepted': bool(ans)})
            if ans:
                # Start client with provided options
                self.start_client(host, port, options)
                self.lbl_status.config(text='Als Client verbunden')
        self.root.after(0, _prompt)

    def start_server(self):
        if self.server_started:
            return
        self.server_started = True
        # Launch server as subprocess to keep macOS event taps on main thread of its process
        args = [sys.executable, os.path.join(os.path.dirname(__file__), 'server.py'),
                '--host', '0.0.0.0', '--port', str(self.ws_port),
                '--hotkey', self.var_hotkey.get()]
        if not self.var_tx_mouse.get():
            args.append('--no-tx-mouse')
        if not self.var_tx_keyboard.get():
            args.append('--no-tx-keyboard')
        try:
            self.server_proc = subprocess.Popen(args)
        except Exception as e:
            messagebox.showerror('Fehler', f'Server konnte nicht gestartet werden: {e}')
            self.server_started = False
            return
        self.lbl_status.config(text=f'Server gestartet auf Port {self.ws_port}')

    def start_client(self, host: str, port: int, options: dict):
        # Build client subprocess args
        map_mode = options.get('map', self.var_map.get())
        interp = bool(options.get('interp', self.var_interp.get()))
        interp_rate = int(options.get('interp_rate_hz', self.var_interp_rate.get()))
        interp_step = int(options.get('interp_step_px', self.var_interp_step.get()))
        deadzone = int(options.get('deadzone_px', self.var_deadzone.get()))
        speed = float(options.get('speed', self.var_speed.get()))
        args = [sys.executable, os.path.join(os.path.dirname(__file__), 'client.py'),
                host, '--port', str(port), '--map', map_mode,
                '--interp-rate-hz', str(interp_rate), '--interp-step-px', str(interp_step),
                '--deadzone-px', str(deadzone), '--speed', str(speed)]
        if interp:
            args.insert(6, '--interp')  # after map
        try:
            self.client_proc = subprocess.Popen(args)
        except Exception as e:
            messagebox.showerror('Fehler', f'Client konnte nicht gestartet werden: {e}')
            return

    def request_control(self):
        # Get selection
        try:
            sel = self.listbox.curselection()
            if not sel:
                messagebox.showinfo('Hinweis', 'Bitte ein Gerät aus der Liste wählen.')
                return
            idx = sel[0]
            # Map index back to instance id
            inst_id = list(sorted(self.devices.items(), key=lambda kv: kv[1]['name']))[idx][0]
            info = self.devices[inst_id]
        except Exception:
            messagebox.showerror('Fehler', 'Auswahl fehlgeschlagen.')
            return

        # Ensure server running
        self.start_server()
        # Build options to send
        options = {
            'map': self.var_map.get(),
            'interp': self.var_interp.get(),
            'interp_rate_hz': self.var_interp_rate.get(),
            'interp_step_px': self.var_interp_step.get(),
            'deadzone_px': self.var_deadzone.get(),
            'speed': self.var_speed.get(),
        }
        payload = {
            'to': inst_id,
            'name': self.name,
            'ws_host': get_primary_ip(),
            'ws_port': self.ws_port,
            'options': options,
        }
        self.discovery.send_request(info['ip'], payload)
        self.lbl_status.config(text='Anfrage gesendet – warte auf Bestätigung…')

    def open_settings(self):
        w = tk.Toplevel(self.root)
        w.title('Einstellungen')
        frm = ttk.Frame(w, padding=12)
        frm.grid(sticky='nsew')
        w.columnconfigure(0, weight=1)
        w.rowconfigure(0, weight=1)

        # Speed
        ttk.Label(frm, text='Mausgeschwindigkeit (relative):').grid(row=0, column=0, sticky='w')
        ttk.Entry(frm, textvariable=self.var_speed, width=8).grid(row=0, column=1, sticky='w')
        # Map mode
        ttk.Label(frm, text='Mapping:').grid(row=1, column=0, sticky='w')
        ttk.OptionMenu(frm, self.var_map, self.var_map.get(), 'relative', 'normalized', 'preserve').grid(row=1, column=1, sticky='w')
        # Interp
        ttk.Checkbutton(frm, text='Interpolation aktiv', variable=self.var_interp).grid(row=2, column=0, sticky='w')
        ttk.Label(frm, text='Rate (Hz):').grid(row=3, column=0, sticky='w')
        ttk.Entry(frm, textvariable=self.var_interp_rate, width=8).grid(row=3, column=1, sticky='w')
        ttk.Label(frm, text='Schritt (px):').grid(row=4, column=0, sticky='w')
        ttk.Entry(frm, textvariable=self.var_interp_step, width=8).grid(row=4, column=1, sticky='w')
        ttk.Label(frm, text='Deadzone (px):').grid(row=5, column=0, sticky='w')
        ttk.Entry(frm, textvariable=self.var_deadzone, width=8).grid(row=5, column=1, sticky='w')

        # Transmit
        ttk.Checkbutton(frm, text='Maus übertragen', variable=self.var_tx_mouse).grid(row=6, column=0, sticky='w')
        ttk.Checkbutton(frm, text='Tastatur übertragen', variable=self.var_tx_keyboard).grid(row=6, column=1, sticky='w')
        # Hotkey
        ttk.Label(frm, text='Remote-Hotkey:').grid(row=7, column=0, sticky='w')
        ttk.OptionMenu(frm, self.var_hotkey, self.var_hotkey.get(), 'f13', 'f12', 'f11', 'f14').grid(row=7, column=1, sticky='w')

        ttk.Button(frm, text='Schließen', command=w.destroy).grid(row=8, column=0, pady=8, sticky='w')

    def on_close(self):
        try:
            if self.client_proc and self.client_proc.poll() is None:
                self.client_proc.terminate()
        except Exception:
            pass
        try:
            if self.server_proc and self.server_proc.poll() is None:
                self.server_proc.terminate()
        except Exception:
            pass
        self.root.destroy()


def main():
    root = tk.Tk()
    app = App(root)
    root.mainloop()

if __name__ == '__main__':
    main()

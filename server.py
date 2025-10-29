#!/usr/bin/env python3
"""
KVM Server (Laptop A) - Fängt Tastatur/Maus Events ab und sendet sie über WebSocket
"""
import asyncio
import websockets
import json
import threading
import time
import argparse
import queue
from pynput import mouse, keyboard
from pynput.mouse import Button
import pyautogui

class KVMServer:
    def __init__(self, host='0.0.0.0', port=8765):
        self.host = host
        self.port = port
        self.clients = set()
        self.capturing = False
        self.mouse_listener = None
        self.keyboard_listener = None
        
        # Event-Queue für Thread-sichere Kommunikation
        self.event_queue = queue.Queue(maxsize=100)  # Begrenzte Queue-Größe
        self.loop = None
        
        # Performance-Optimierungen
        self.last_mouse_time = 0
        # Standard-Throttle (~4ms ≈ 250 Hz) für flüssigere Bewegung
        self.mouse_throttle = 0.004
        
        # Optionen für lokale Unterbindung
        self.suppress_mouse = True      # Lokale Maus unterbinden wenn Remote aktiv
        self.suppress_keyboard = True   # Lokale Tastatur unterbinden wenn Remote aktiv
        
        # Hotkey für das Umschalten (F13)
        self.switch_hotkey = {keyboard.Key.f13}
        self.pressed_keys = set()
        
        print(f"KVM Server wird gestartet auf {self.host}:{self.port}")
        print("Hotkey zum Umschalten: F13")
        if self.host == '0.0.0.0':
            print("⚠️  Remote-Modus: Stellen Sie sicher, dass Port 8765 in der Firewall freigegeben ist")
    
    async def register_client(self, websocket):
        """Neuen Client registrieren"""
        self.clients.add(websocket)
        client_info = f"{websocket.remote_address[0]}:{websocket.remote_address[1]}"
        print(f"Client verbunden: {client_info}")
        
        try:
            await websocket.wait_closed()
        finally:
            self.clients.remove(websocket)
            print(f"Client getrennt: {client_info}")
    
    async def send_to_clients(self, message):
        """Nachricht an alle verbundenen Clients senden (optimiert)"""
        if not (self.clients and self.capturing):
            return
            
        # JSON nur einmal serialisieren
        json_message = json.dumps(message, separators=(',', ':'))
        
        # Parallel an alle Clients senden
        tasks = []
        for client in list(self.clients):
            tasks.append(self._send_to_client(client, json_message))
        
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Getrennte Clients entfernen
            disconnected = set()
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    client = list(self.clients)[i] if i < len(self.clients) else None
                    if client:
                        disconnected.add(client)
            
            self.clients -= disconnected
    
    async def send_mouse_sync(self, message):
        """Mausbewegung synchron an alle Clients senden (optimiert)"""
        if not self.clients:
            return
            
        # JSON nur einmal serialisieren für alle Clients
        json_message = json.dumps(message, separators=(',', ':'))  # Kompakte JSON-Ausgabe
        
        # Parallel an alle Clients senden
        tasks = []
        for client in list(self.clients):  # Kopie der Liste für Thread-Sicherheit
            tasks.append(self._send_to_client(client, json_message))
        
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Getrennte Clients entfernen
            disconnected = set()
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    client = list(self.clients)[i] if i < len(self.clients) else None
                    if client:
                        disconnected.add(client)
            
            self.clients -= disconnected
    
    async def _send_to_client(self, client, json_message):
        """Hilfsfunktion um Nachrichten an einzelne Clients zu senden"""
        try:
            await client.send(json_message)
            return True
        except websockets.exceptions.ConnectionClosed:
            raise  # Exception wird von send_mouse_sync behandelt
        except Exception as e:
            raise e
    
    async def process_event_queue(self):
        """Verarbeitet Events aus der Queue in der Async-Loop"""
        while True:
            try:
                # Mehrere Events auf einmal verarbeiten für bessere Performance
                events_to_process = []
                
                # Sammle alle verfügbaren Events (bis zu 25 auf einmal)
                for _ in range(25):
                    try:
                        message = self.event_queue.get_nowait()
                        events_to_process.append(message)
                    except queue.Empty:
                        break
                
                if events_to_process:
                    # Mausbewegungen zusammenfassen: nur die letzte Position senden
                    last_mouse_move = None
                    others = []
                    for message in events_to_process:
                        if message.get('type') == 'mouse_move':
                            last_mouse_move = message
                        else:
                            others.append(message)

                    tasks = []
                    for message in others:
                        if message.get('sync', False):
                            tasks.append(self.send_mouse_sync(message))
                        else:
                            tasks.append(self.send_to_clients(message))
                    if last_mouse_move is not None:
                        tasks.append(self.send_to_clients(last_mouse_move))

                    # Alle Tasks parallel ausführen
                    if tasks:
                        await asyncio.gather(*tasks, return_exceptions=True)
                else:
                    # Keine Events, minimale Pause
                    await asyncio.sleep(0.00005)  # 0.05ms
                    
            except Exception as e:
                print(f"Fehler beim Verarbeiten des Events: {e}")
    
    def on_mouse_move(self, x, y):
        """Maus-Bewegung abfangen mit Throttling"""
        current_time = time.time()
        
        # Throttling: Nur senden wenn genug Zeit vergangen ist
        if current_time - self.last_mouse_time < self.mouse_throttle:
            return
            
        self.last_mouse_time = current_time
        
        # Nur im Remote-Capturing senden (ein Gerät aktiv)
        if self.clients and self.capturing:  # Nur senden wenn Clients verbunden und Capturing aktiv ist
            # Koordinaten normalisieren, damit Client-Bildschirmgröße voll genutzt wird
            try:
                sw, sh = pyautogui.size()
                x_norm = max(0.0, min(1.0, x / sw)) if sw else 0.0
                y_norm = max(0.0, min(1.0, y / sh)) if sh else 0.0
            except Exception:
                # Fallback: falls Größe nicht ermittelbar ist, sende Rohdaten
                x_norm, y_norm = None, None
                sw, sh = None, None

            message = {
                'type': 'mouse_move',
                'coord': 'normalized' if x_norm is not None else 'absolute',
                'x': x_norm if x_norm is not None else x,
                'y': y_norm if y_norm is not None else y,
                'timestamp': current_time,
                'src_w': sw,
                'src_h': sh,
                'sync': False
            }
            try:
                self.event_queue.put_nowait(message)
            except queue.Full:
                # Queue voll, älteste Events verwerfen
                try:
                    self.event_queue.get_nowait()  # Ältestes Event entfernen
                    self.event_queue.put_nowait(message)  # Neues Event hinzufügen
                except queue.Empty:
                    pass
    
    def on_mouse_click(self, x, y, button, pressed):
        """Maus-Klick abfangen"""
        if self.capturing:
            message = {
                'type': 'mouse_click',
                'x': x,
                'y': y,
                'button': button.name,
                'pressed': pressed,
                'timestamp': time.time(),
                'sync': False  # Nur im Capturing-Modus
            }
            try:
                self.event_queue.put_nowait(message)
            except queue.Full:
                pass
    
    def on_mouse_scroll(self, x, y, dx, dy):
        """Maus-Scroll abfangen"""
        if self.capturing:
            message = {
                'type': 'mouse_scroll',
                'x': x,
                'y': y,
                'dx': dx,
                'dy': dy,
                'timestamp': time.time(),
                'sync': False  # Nur im Capturing-Modus
            }
            try:
                self.event_queue.put_nowait(message)
            except queue.Full:
                pass
    
    def on_key_press(self, key):
        """Tastendruck abfangen"""
        self.pressed_keys.add(key)
        
        # Prüfen ob Hotkey gedrückt wurde
        if self.switch_hotkey.issubset(self.pressed_keys):
            self.toggle_capturing()
            return
        
        if self.capturing:
            try:
                key_data = key.char if hasattr(key, 'char') and key.char else str(key)
            except AttributeError:
                key_data = str(key)
            
            message = {
                'type': 'key_press',
                'key': key_data,
                'timestamp': time.time(),
                'sync': False  # Nur im Capturing-Modus
            }
            try:
                self.event_queue.put_nowait(message)
            except queue.Full:
                pass
    
    def on_key_release(self, key):
        """Taste loslassen abfangen"""
        try:
            self.pressed_keys.discard(key)
        except KeyError:
            pass
        
        if self.capturing:
            try:
                key_data = key.char if hasattr(key, 'char') and key.char else str(key)
            except AttributeError:
                key_data = str(key)
            
            message = {
                'type': 'key_release',
                'key': key_data,
                'timestamp': time.time(),
                'sync': False  # Nur im Capturing-Modus
            }
            try:
                self.event_queue.put_nowait(message)
            except queue.Full:
                pass
    
    def toggle_capturing(self):
        """Umschalten zwischen lokalem und Remote-Modus.
        - Wenn aktiv: Maus/Klicks/Tastatur werden remote gesendet und lokale Maus wird unterbunden.
        - Wenn inaktiv: Alles bleibt lokal; Remote erhält nichts.
        """
        self.capturing = not self.capturing
        status = "REMOTE AKTIV (nur Remote bewegt Maus)" if self.capturing else "LOKAL AKTIV (nur lokal bewegt Maus)"
        print(f"\n{'='*50}")
        print(f"Status: {status}")
        print(f"Hotkey: F13 zum Umschalten")
        print(f"{'='*50}")

        # Lokale Eingaben unterbinden wenn Capturing aktiv, sonst erlauben
        self._set_mouse_suppression(self.capturing and self.suppress_mouse)
        self._set_keyboard_suppression(self.capturing and self.suppress_keyboard)

        if self.capturing:
            print("➡️  Remote aktiv: Sende Maus/Tastatur/Klicks an Client. Lokale Maus unterbunden.")
        else:
            print("⬅️  Lokal aktiv: Maus/Tastatur/Klicks lokal. Remote-Eingaben pausiert.")

    def _set_mouse_suppression(self, suppress: bool):
        """Maus-Listener mit gewünschter Suppression neu starten."""
        try:
            if self.mouse_listener:
                self.mouse_listener.stop()
        except Exception:
            pass
        # Maus-Listener neu erstellen mit Suppression
        try:
            self.mouse_listener = mouse.Listener(
                on_move=self.on_mouse_move,
                on_click=self.on_mouse_click,
                on_scroll=self.on_mouse_scroll,
                suppress=suppress
            )
            self.mouse_listener.start()
        except Exception as e:
            # Fallback ohne Suppression und Hinweis anzeigen
            import sys
            print("⚠️  Konnte Maus-Unterdrückung nicht aktivieren:", e)
            print("   Hinweis: Auf macOS müssen Sie der App Zugriff unter Einstellungen > Datenschutz & Sicherheit > Bedienungshilfen gewähren.")
            print(f"   Fügen Sie Ihren Terminal/Editor und den Python-Interpreter hinzu: {sys.executable}")
            self.suppress_mouse = False
            self.mouse_listener = mouse.Listener(
                on_move=self.on_mouse_move,
                on_click=self.on_mouse_click,
                on_scroll=self.on_mouse_scroll,
                suppress=False
            )
            self.mouse_listener.start()
    
    def _set_keyboard_suppression(self, suppress: bool):
        """Keyboard-Listener mit gewünschter Suppression neu starten."""
        try:
            if self.keyboard_listener:
                self.keyboard_listener.stop()
        except Exception:
            pass
        try:
            self.keyboard_listener = keyboard.Listener(
                on_press=self.on_key_press,
                on_release=self.on_key_release,
                suppress=suppress
            )
            self.keyboard_listener.start()
        except Exception as e:
            import sys
            print("⚠️  Konnte Tastatur-Unterdrückung nicht aktivieren:", e)
            print("   Hinweis: Auf macOS müssen Sie der App Zugriff unter Einstellungen > Datenschutz & Sicherheit > Bedienungshilfen gewähren.")
            print(f"   Fügen Sie Ihren Terminal/Editor und den Python-Interpreter hinzu: {sys.executable}")
            self.suppress_keyboard = False
            self.keyboard_listener = keyboard.Listener(
                on_press=self.on_key_press,
                on_release=self.on_key_release,
                suppress=False
            )
            self.keyboard_listener.start()
    
    def start_listeners(self):
        """Event-Listener starten"""
        # Maus-Listener (initial ohne Suppression)
        self.mouse_listener = mouse.Listener(
            on_move=self.on_mouse_move,
            on_click=self.on_mouse_click,
            on_scroll=self.on_mouse_scroll,
            suppress=False
        )

        # Tastatur-Listener (nie suppress, damit Hotkey immer funktioniert)
        self.keyboard_listener = keyboard.Listener(
            on_press=self.on_key_press,
            on_release=self.on_key_release
        )

        self.mouse_listener.start()
        self.keyboard_listener.start()

        print("Event-Listener gestartet")
        print("🖱️  Standard: Lokal aktiv. Drücke F13 für Remote (lokale Maus wird gesperrt)")
    
    def stop_listeners(self):
        """Event-Listener stoppen"""
        if self.mouse_listener:
            self.mouse_listener.stop()
        if self.keyboard_listener:
            self.keyboard_listener.stop()
    
    async def start_server(self):
        """WebSocket-Server starten"""
        self.loop = asyncio.get_running_loop()
        self.start_listeners()
        
        try:
            # Wrapper-Funktion für bessere Kompatibilität
            async def handler(websocket, path=None):
                await self.register_client(websocket)
            
            # Event-Processing-Task starten
            event_task = asyncio.create_task(self.process_event_queue())
            
            async with websockets.serve(
                handler,
                self.host,
                self.port,
                compression=None,  # geringere Latenz (nicht komprimieren)
                max_queue=1        # kleine Warteschlange zur Latenzreduktion
            ):
                print(f"Server läuft auf ws://{self.host}:{self.port}")
                print("Warten auf Client-Verbindungen...")
                await asyncio.Future()  # Läuft für immer
        except KeyboardInterrupt:
            print("\nServer wird beendet...")
        finally:
            self.stop_listeners()

def main():
    parser = argparse.ArgumentParser(description='KVM Server - Remote Tastatur/Maus Steuerung')
    parser.add_argument('--host', default='0.0.0.0', 
                       help='Server Host-Adresse (default: 0.0.0.0 für remote access)')
    parser.add_argument('--port', type=int, default=8765,
                       help='Server Port (default: 8765)')
    parser.add_argument('--no-suppress-mouse', action='store_true',
                        help='Lokale Maus nicht unterbinden (Fallback, wenn macOS Rechte fehlen)')
    parser.add_argument('--no-suppress-keyboard', action='store_true',
                        help='Lokale Tastatur nicht unterbinden (Fallback, wenn macOS Rechte fehlen)')
    parser.add_argument('--mouse-throttle-ms', type=float, default=4.0,
                        help='Mindestabstand zwischen Maus-Events in Millisekunden (Standard 4.0 ≈ 250 Hz)')
    
    args = parser.parse_args()
    
    server = KVMServer(host=args.host, port=args.port)
    if args.no_suppress_mouse:
        server.suppress_mouse = False
    if args.no_suppress_keyboard:
        server.suppress_keyboard = False
    if args.mouse_throttle_ms is not None and args.mouse_throttle_ms >= 0:
        server.mouse_throttle = args.mouse_throttle_ms / 1000.0
    
    print(f"Server startet auf {args.host}:{args.port}")
    if args.host == '0.0.0.0':
        print("🌐 Remote-Zugriff aktiviert - Server ist über das Netzwerk erreichbar")
    else:
        print("🏠 Lokaler Zugriff - Server nur lokal erreichbar")
    
    try:
        asyncio.run(server.start_server())
    except KeyboardInterrupt:
        print("\nProgramm beendet.")

if __name__ == "__main__":
    main()
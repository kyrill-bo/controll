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
        
        # Hotkey für das Umschalten (Command+>)
        self.switch_hotkey = {keyboard.Key.cmd, keyboard.Key.shift, keyboard.KeyCode.from_char('.')}
        self.pressed_keys = set()
        
        print(f"KVM Server wird gestartet auf {host}:{port}")
        print("Hotkey zum Umschalten: Cmd+>")
        if host == '0.0.0.0':
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
        """Nachricht an alle verbundenen Clients senden"""
        if self.clients and self.capturing:
            disconnected = set()
            for client in self.clients:
                try:
                    await client.send(json.dumps(message))
                except websockets.exceptions.ConnectionClosed:
                    disconnected.add(client)
            
            # Getrennte Clients entfernen
            self.clients -= disconnected
    
    async def send_mouse_sync(self, message):
        """Mausbewegung synchron an alle Clients senden (immer aktiv)"""
        if self.clients:
            disconnected = set()
            for client in self.clients:
                try:
                    await client.send(json.dumps(message))
                except websockets.exceptions.ConnectionClosed:
                    disconnected.add(client)
            
            # Getrennte Clients entfernen
            self.clients -= disconnected
    
    def on_mouse_move(self, x, y):
        """Maus-Bewegung abfangen"""
        # Mausbewegung wird immer gesendet für synchrone Bewegung
        if self.clients:  # Nur senden wenn Clients verbunden sind
            message = {
                'type': 'mouse_move',
                'x': x,
                'y': y,
                'timestamp': time.time()
            }
            asyncio.create_task(self.send_mouse_sync(message))
    
    def on_mouse_click(self, x, y, button, pressed):
        """Maus-Klick abfangen"""
        if self.capturing:
            message = {
                'type': 'mouse_click',
                'x': x,
                'y': y,
                'button': button.name,
                'pressed': pressed,
                'timestamp': time.time()
            }
            asyncio.create_task(self.send_to_clients(message))
    
    def on_mouse_scroll(self, x, y, dx, dy):
        """Maus-Scroll abfangen"""
        if self.capturing:
            message = {
                'type': 'mouse_scroll',
                'x': x,
                'y': y,
                'dx': dx,
                'dy': dy,
                'timestamp': time.time()
            }
            asyncio.create_task(self.send_to_clients(message))
    
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
                'timestamp': time.time()
            }
            asyncio.create_task(self.send_to_clients(message))
    
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
                'timestamp': time.time()
            }
            asyncio.create_task(self.send_to_clients(message))
    
    def toggle_capturing(self):
        """Umschalten zwischen lokalem und Remote-Modus für Tastatur/Klicks"""
        self.capturing = not self.capturing
        status = "Remote-Tastatur/Klicks AKTIV" if self.capturing else "Lokale Tastatur/Klicks AKTIV"
        print(f"\n{'='*50}")
        print(f"Status: {status}")
        print(f"🖱️  Maus bewegt sich immer synchron")
        print(f"{'='*50}")
        
        if self.capturing:
            print("Tastatur und Mausklicks werden jetzt an den Remote-Laptop gesendet")
            print("Drücken Sie Cmd+> um zurück zu wechseln")
        else:
            print("Tastatur und Mausklicks sind wieder lokal aktiv")
            print("Drücken Sie Cmd+> um Remote-Modus zu aktivieren")
    
    def start_listeners(self):
        """Event-Listener starten"""
        # Maus-Listener
        self.mouse_listener = mouse.Listener(
            on_move=self.on_mouse_move,
            on_click=self.on_mouse_click,
            on_scroll=self.on_mouse_scroll
        )
        
        # Tastatur-Listener  
        self.keyboard_listener = keyboard.Listener(
            on_press=self.on_key_press,
            on_release=self.on_key_release
        )
        
        self.mouse_listener.start()
        self.keyboard_listener.start()
        
        print("Event-Listener gestartet")
        print("🖱️  Mausbewegung ist immer synchron")
        print("Drücken Sie Cmd+> um Tastatur/Klicks zu aktivieren")
    
    def stop_listeners(self):
        """Event-Listener stoppen"""
        if self.mouse_listener:
            self.mouse_listener.stop()
        if self.keyboard_listener:
            self.keyboard_listener.stop()
    
    async def start_server(self):
        """WebSocket-Server starten"""
        self.start_listeners()
        
        try:
            # Wrapper-Funktion für bessere Kompatibilität
            async def handler(websocket, path=None):
                await self.register_client(websocket)
            
            async with websockets.serve(handler, self.host, self.port):
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
    
    args = parser.parse_args()
    
    server = KVMServer(host=args.host, port=args.port)
    
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
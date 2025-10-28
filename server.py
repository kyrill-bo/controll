#!/usr/bin/env python3
"""
KVM Server (Laptop A) - Fängt Tastatur/Maus Events ab und sendet sie über WebSocket
"""
import asyncio
import websockets
import json
import threading
import time
from pynput import mouse, keyboard
from pynput.mouse import Button
import pyautogui

class KVMServer:
    def __init__(self, host='localhost', port=8765):
        self.host = host
        self.port = port
        self.clients = set()
        self.capturing = False
        self.mouse_listener = None
        self.keyboard_listener = None
        
        # Hotkey für das Umschalten (z.B. Ctrl+Alt+S)
        self.switch_hotkey = {keyboard.Key.ctrl, keyboard.Key.alt, keyboard.KeyCode(char='s')}
        self.pressed_keys = set()
        
        print(f"KVM Server wird gestartet auf {host}:{port}")
        print("Hotkey zum Umschalten: Ctrl+Alt+S")
    
    async def register_client(self, websocket, path):
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
    
    def on_mouse_move(self, x, y):
        """Maus-Bewegung abfangen"""
        if self.capturing:
            message = {
                'type': 'mouse_move',
                'x': x,
                'y': y,
                'timestamp': time.time()
            }
            asyncio.create_task(self.send_to_clients(message))
    
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
        """Umschalten zwischen lokalem und Remote-Modus"""
        self.capturing = not self.capturing
        status = "Remote-Steuerung AKTIV" if self.capturing else "Lokale Steuerung AKTIV"
        print(f"\n{'='*50}")
        print(f"Status: {status}")
        print(f"{'='*50}")
        
        if self.capturing:
            print("Tastatur und Maus werden jetzt an den Remote-Laptop gesendet")
            print("Drücken Sie Ctrl+Alt+S um zurück zu wechseln")
        else:
            print("Tastatur und Maus sind wieder lokal aktiv")
            print("Drücken Sie Ctrl+Alt+S um zu Remote-Laptop zu wechseln")
    
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
        print("Drücken Sie Ctrl+Alt+S um Remote-Steuerung zu aktivieren")
    
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
            async with websockets.serve(self.register_client, self.host, self.port):
                print(f"Server läuft auf ws://{self.host}:{self.port}")
                print("Warten auf Client-Verbindungen...")
                await asyncio.Future()  # Läuft für immer
        except KeyboardInterrupt:
            print("\nServer wird beendet...")
        finally:
            self.stop_listeners()

def main():
    server = KVMServer()
    
    try:
        asyncio.run(server.start_server())
    except KeyboardInterrupt:
        print("\nProgramm beendet.")

if __name__ == "__main__":
    main()
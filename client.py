#!/usr/bin/env python3
"""
KVM Client (Laptop B) - Empfängt Events und simuliert sie lokal
"""
import asyncio
import websockets
import json
import pyautogui
from pynput.keyboard import Key, Listener as KeyboardListener
from pynput import keyboard

class KVMClient:
    def __init__(self, server_host='localhost', server_port=8765):
        self.server_host = server_host
        self.server_port = server_port
        self.uri = f"ws://{server_host}:{server_port}"
        self.connected = False
        
        # PyAutoGUI Einstellungen
        pyautogui.FAILSAFE = False  # Deaktiviert Fail-Safe
        pyautogui.PAUSE = 0.01     # Minimale Pause zwischen Aktionen
        
        # Tastatur-Controller für spezielle Tasten
        self.keyboard_controller = keyboard.Controller()
        
        print(f"KVM Client - Verbinde zu {self.uri}")
    
    async def connect_to_server(self):
        """Mit Server verbinden und Events empfangen"""
        try:
            async with websockets.connect(self.uri) as websocket:
                self.connected = True
                print("✓ Verbunden mit KVM Server")
                print("Bereit zum Empfangen von Remote-Events")
                
                async for message in websocket:
                    try:
                        data = json.loads(message)
                        await self.handle_event(data)
                    except json.JSONDecodeError:
                        print(f"Ungültiges JSON empfangen: {message}")
                    except Exception as e:
                        print(f"Fehler beim Verarbeiten des Events: {e}")
                        
        except websockets.exceptions.ConnectionClosed:
            print("✗ Verbindung zum Server verloren")
        except ConnectionRefusedError:
            print("✗ Kann keine Verbindung zum Server herstellen")
            print("  Stellen Sie sicher, dass der Server läuft")
        except Exception as e:
            print(f"✗ Verbindungsfehler: {e}")
        finally:
            self.connected = False
    
    async def handle_event(self, data):
        """Empfangenes Event verarbeiten"""
        event_type = data.get('type')
        
        try:
            if event_type == 'mouse_move':
                pyautogui.moveTo(data['x'], data['y'])
                
            elif event_type == 'mouse_click':
                button_map = {
                    'left': 'left',
                    'right': 'right', 
                    'middle': 'middle'
                }
                
                button = button_map.get(data['button'], 'left')
                
                if data['pressed']:
                    pyautogui.mouseDown(button=button)
                else:
                    pyautogui.mouseUp(button=button)
                    
            elif event_type == 'mouse_scroll':
                # Scroll-Richtung umkehren für natürliches Scrolling
                scroll_amount = data['dy'] * 3  # Scroll-Geschwindigkeit anpassen
                pyautogui.scroll(scroll_amount)
                
            elif event_type == 'key_press':
                await self.simulate_key_press(data['key'], True)
                
            elif event_type == 'key_release':
                await self.simulate_key_press(data['key'], False)
                
        except Exception as e:
            print(f"Fehler beim Simulieren des Events {event_type}: {e}")
    
    async def simulate_key_press(self, key_data, pressed):
        """Tastendruck simulieren"""
        try:
            # Spezielle Tasten behandeln
            special_keys = {
                'Key.alt': Key.alt,
                'Key.alt_l': Key.alt_l,
                'Key.alt_r': Key.alt_r,
                'Key.ctrl': Key.ctrl,
                'Key.ctrl_l': Key.ctrl_l,
                'Key.ctrl_r': Key.ctrl_r,
                'Key.shift': Key.shift,
                'Key.shift_l': Key.shift_l,
                'Key.shift_r': Key.shift_r,
                'Key.cmd': Key.cmd,
                'Key.cmd_l': Key.cmd_l,
                'Key.cmd_r': Key.cmd_r,
                'Key.space': Key.space,
                'Key.enter': Key.enter,
                'Key.tab': Key.tab,
                'Key.backspace': Key.backspace,
                'Key.delete': Key.delete,
                'Key.esc': Key.esc,
                'Key.up': Key.up,
                'Key.down': Key.down,
                'Key.left': Key.left,
                'Key.right': Key.right,
                'Key.home': Key.home,
                'Key.end': Key.end,
                'Key.page_up': Key.page_up,
                'Key.page_down': Key.page_down,
            }
            
            if key_data in special_keys:
                key = special_keys[key_data]
                if pressed:
                    self.keyboard_controller.press(key)
                else:
                    self.keyboard_controller.release(key)
            else:
                # Normale Zeichen
                if len(key_data) == 1:
                    if pressed:
                        self.keyboard_controller.press(key_data)
                    else:
                        self.keyboard_controller.release(key_data)
                        
        except Exception as e:
            print(f"Fehler beim Simulieren der Taste '{key_data}': {e}")
    
    async def run(self):
        """Client dauerhaft laufen lassen mit Reconnect"""
        while True:
            try:
                await self.connect_to_server()
            except KeyboardInterrupt:
                print("\nClient wird beendet...")
                break
            
            if not self.connected:
                print("Versuche Reconnect in 5 Sekunden...")
                await asyncio.sleep(5)

def main():
    import sys
    
    server_host = 'localhost'
    if len(sys.argv) > 1:
        server_host = sys.argv[1]
    
    client = KVMClient(server_host)
    
    try:
        asyncio.run(client.run())
    except KeyboardInterrupt:
        print("\nProgramm beendet.")

if __name__ == "__main__":
    main()
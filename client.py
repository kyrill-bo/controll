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
    def __init__(self, server_host='localhost', server_port=8765, map_mode='normalized'):
        self.server_host = server_host
        self.server_port = server_port
        self.uri = f"ws://{server_host}:{server_port}"
        self.connected = False
        self.map_mode = map_mode  # 'normalized' (default) or 'preserve'
        
        # PyAutoGUI Einstellungen für maximale Performance
        pyautogui.FAILSAFE = False  # Deaktiviert Fail-Safe
        pyautogui.PAUSE = 0        # Keine Pause zwischen Aktionen
        pyautogui.MINIMUM_DURATION = 0  # Keine Mindestdauer für Bewegungen
        pyautogui.MINIMUM_SLEEP = 0     # Keine Mindest-Sleep-Zeit
        # macOS: Catch-up Zeit auf 0 für weniger Latenz (falls vorhanden)
        if hasattr(pyautogui, 'DARWIN_CATCH_UP_TIME'):
            pyautogui.DARWIN_CATCH_UP_TIME = 0
        
        # Tastatur-Controller für spezielle Tasten
        self.keyboard_controller = keyboard.Controller()
        # Letzte Mausposition, um unnötige Bewegungen zu sparen
        self._last_mouse_pos = None
        
        print(f"KVM Client - Verbinde zu {self.uri}")
    
    async def connect_to_server(self):
        """Mit Server verbinden und Events empfangen"""
        try:
            async with websockets.connect(self.uri, compression=None, max_queue=1) as websocket:
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
                # Koordinaten ggf. von normalisiert [0,1] in Bildschirm-Pixel umrechnen
                coord_mode = data.get('coord')
                if coord_mode == 'normalized':
                    try:
                        cw, ch = pyautogui.size()
                        x_norm = max(0.0, min(1.0, float(data['x'])))
                        y_norm = max(0.0, min(1.0, float(data['y'])))
                        if self.map_mode == 'preserve' and data.get('src_w') and data.get('src_h'):
                            # Aspect-preserving Letterbox/Pillarbox Mapping
                            src_w = float(data['src_w'])
                            src_h = float(data['src_h'])
                            if src_w <= 0 or src_h <= 0:
                                raise ValueError('invalid src size')
                            src_aspect = src_w / src_h
                            dst_aspect = cw / ch if ch else 1.0
                            if dst_aspect >= src_aspect:
                                # Client ist relativ breiter -> Höhe voll, Seitenbänder
                                target_h = ch
                                target_w = int(round(target_h * src_aspect))
                                x_off = (cw - target_w) // 2
                                y_off = 0
                            else:
                                # Client ist relativ höher -> Breite voll, obere/untere Bänder
                                target_w = cw
                                target_h = int(round(target_w / src_aspect))
                                x_off = 0
                                y_off = (ch - target_h) // 2
                            x = int(x_off + x_norm * max(1, target_w-1))
                            y = int(y_off + y_norm * max(1, target_h-1))
                        else:
                            # Vollflächig strecken (Standard)
                            x = int(x_norm * max(1, cw-1))
                            y = int(y_norm * max(1, ch-1))
                    except Exception:
                        # Fallback auf Mitte, wenn etwas schief geht
                        cw, ch = pyautogui.size()
                        x, y = cw // 2, ch // 2
                else:
                    x, y = int(data['x']), int(data['y'])

                # Optimierte Mausbewegung ohne Dauer-Parameter, Duplikate vermeiden
                if self._last_mouse_pos != (x, y):
                    pyautogui.moveTo(x, y, duration=0)
                    self._last_mouse_pos = (x, y)
                
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
    import argparse
    parser = argparse.ArgumentParser(description='KVM Client - Remote Event Simulator')
    parser.add_argument('server_host', nargs='?', default='localhost', help='Server Host (default: localhost)')
    parser.add_argument('--port', type=int, default=8765, help='Server Port (default: 8765)')
    parser.add_argument('--map', choices=['normalized','preserve'], default='normalized',
                        help='Mapping-Modus für Mausbewegung (normalized=volle Fläche, preserve=Seitenverhältnis erhalten)')
    args = parser.parse_args()

    client = KVMClient(args.server_host, args.port, map_mode=args.map)

    try:
        asyncio.run(client.run())
    except KeyboardInterrupt:
        print("\nProgramm beendet.")

if __name__ == "__main__":
    main()
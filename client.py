#!/usr/bin/env python3
"""
KVM Client (Laptop B) - Empfängt Events und simuliert sie lokal
"""
import asyncio
import websockets
import json
import pyautogui
# Optional macOS fast path for cursor movement
try:
    import Quartz
    _HAS_QUARTZ = True
except Exception:
    _HAS_QUARTZ = False
from pynput.keyboard import Key, Listener as KeyboardListener
from pynput import keyboard

class KVMClient:
    def __init__(self, server_host='localhost', server_port=8765, map_mode='normalized',
                 interp_enabled=False, interp_rate_hz=240, interp_step_px=10, deadzone_px=1):
        self.server_host = server_host
        self.server_port = server_port
        self.uri = f"ws://{server_host}:{server_port}"
        self.connected = False
        self.map_mode = map_mode  # 'normalized' (default) or 'preserve'
        self.interp_enabled = interp_enabled
        self.interp_rate_hz = max(30, int(interp_rate_hz))  # sanity bounds
        self.interp_step_px = max(1, int(interp_step_px))
        self.deadzone_px = max(0, int(deadzone_px))
        
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
        # Letzte eingehende Koordinaten für Relative-Mode
        self._last_incoming_norm = None  # (x_norm, y_norm)
        self._last_incoming_abs = None   # (x_abs, y_abs)
        # Interpolation-Status
        self._target_pos = None  # (x, y) Zielposition für absolute Modi
        self._pending_dx = 0
        self._pending_dy = 0
        self._smoother_task = None
        
        print(f"KVM Client - Verbinde zu {self.uri}")
    
    async def connect_to_server(self):
        """Mit Server verbinden und Events empfangen"""
        try:
            async with websockets.connect(self.uri, compression=None, max_queue=1) as websocket:
                self.connected = True
                # Smoother starten, falls aktiviert
                if self.interp_enabled and self._smoother_task is None:
                    self._smoother_task = asyncio.create_task(self._smoothing_loop())
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
            # Smoother stoppen
            try:
                if self._smoother_task:
                    self._smoother_task.cancel()
            except Exception:
                pass
            self._smoother_task = None
    
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

                        # Relative Modus: auf Pixel-Deltas abbilden und relativ bewegen
                        if self.map_mode == 'relative':
                            if self._last_incoming_norm is None:
                                self._last_incoming_norm = (x_norm, y_norm)
                                return
                            last_xn, last_yn = self._last_incoming_norm
                            dx = int((x_norm - last_xn) * max(1, cw-1))
                            dy = int((y_norm - last_yn) * max(1, ch-1))
                            self._last_incoming_norm = (x_norm, y_norm)
                            # Deadzone-Filter gegen Mikro-Jitter
                            if abs(dx) < self.deadzone_px and abs(dy) < self.deadzone_px:
                                return
                            if dx != 0 or dy != 0:
                                if self.interp_enabled:
                                    self._pending_dx += dx
                                    self._pending_dy += dy
                                else:
                                    pyautogui.moveRel(dx, dy, duration=0)
                            return

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
                    if self.map_mode == 'relative':
                        if self._last_incoming_abs is None:
                            self._last_incoming_abs = (x, y)
                            return
                        last_x, last_y = self._last_incoming_abs
                        dx = x - last_x
                        dy = y - last_y
                        self._last_incoming_abs = (x, y)
                        # Deadzone-Filter gegen Mikro-Jitter
                        if abs(dx) < self.deadzone_px and abs(dy) < self.deadzone_px:
                            return
                        if dx != 0 or dy != 0:
                            if self.interp_enabled:
                                self._pending_dx += dx
                                self._pending_dy += dy
                            else:
                                pyautogui.moveRel(dx, dy, duration=0)
                        return

                # Absolute Modi: direkt oder via Interpolation
                if self.interp_enabled:
                    self._target_pos = (x, y)
                else:
                    # Bei direkter Bewegung: nur bewegen, wenn außerhalb der Deadzone
                    if self._last_mouse_pos is None or (
                        abs((self._last_mouse_pos[0] - x)) >= self.deadzone_px or
                        abs((self._last_mouse_pos[1] - y)) >= self.deadzone_px
                    ):
                        if _HAS_QUARTZ:
                            try:
                                Quartz.CGWarpMouseCursorPosition((x, y))
                            except Exception:
                                pyautogui.moveTo(x, y, duration=0)
                        else:
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
    
    async def _smoothing_loop(self):
        """Glättet Mausbewegungen durch kleine Schritte bei hoher Frequenz mit Deadzone und leichtem Easing."""
        try:
            # Initialisiere letzte bekannte Position
            try:
                cx, cy = pyautogui.position()
            except Exception:
                cw, ch = pyautogui.size()
                cx, cy = cw // 2, ch // 2
            self._last_mouse_pos = (cx, cy)

            step_sleep = max(0.001, 1.0 / float(self.interp_rate_hz))
            while True:
                # Relative Modus: verbrauche ausstehende Deltas
                if self.map_mode == 'relative':
                    dx = self._pending_dx
                    dy = self._pending_dy
                    # Deadzone: verwerfe Mikro-Jitter
                    if abs(dx) < self.deadzone_px and abs(dy) < self.deadzone_px:
                        self._pending_dx = 0
                        self._pending_dy = 0
                        await asyncio.sleep(step_sleep)
                    elif dx == 0 and dy == 0:
                        await asyncio.sleep(step_sleep)
                    else:
                        # Begrenze Schrittgröße
                        step_x = max(-self.interp_step_px, min(self.interp_step_px, dx))
                        step_y = max(-self.interp_step_px, min(self.interp_step_px, dy))
                        self._pending_dx -= step_x
                        self._pending_dy -= step_y
                        pyautogui.moveRel(step_x, step_y, duration=0)
                        # last pos ggf. aktualisieren
                        try:
                            cx, cy = pyautogui.position()
                            self._last_mouse_pos = (cx, cy)
                        except Exception:
                            pass
                        await asyncio.sleep(step_sleep)
                    continue

                # Absolute Modi: bewege dich schrittweise auf Zielposition
                tx_ty = self._target_pos
                if not tx_ty:
                    await asyncio.sleep(step_sleep)
                    continue
                tx, ty = tx_ty
                lx, ly = self._last_mouse_pos if self._last_mouse_pos else (tx, ty)
                dx = tx - lx
                dy = ty - ly
                # Deadzone: wenn nahe am Ziel, schnapp auf Ziel und warte
                if abs(dx) <= self.deadzone_px and abs(dy) <= self.deadzone_px:
                    if _HAS_QUARTZ:
                        try:
                            Quartz.CGWarpMouseCursorPosition((int(tx), int(ty)))
                        except Exception:
                            pyautogui.moveTo(int(tx), int(ty), duration=0)
                    else:
                        pyautogui.moveTo(int(tx), int(ty), duration=0)
                    self._last_mouse_pos = (int(tx), int(ty))
                    await asyncio.sleep(step_sleep)
                    continue
                # Easing: Schritt proportional zur verbleibenden Strecke, gekappt
                def _ease_component(delta: int) -> int:
                    mag = abs(delta)
                    # 40% der Reststrecke, mind. 1px, max. interp_step_px
                    step = max(1, min(self.interp_step_px, int(mag * 0.4)))
                    return step if delta > 0 else -step

                step_x = _ease_component(dx)
                step_y = _ease_component(dy)
                nx = lx + step_x
                ny = ly + step_y
                # Setze neue Position
                if _HAS_QUARTZ:
                    try:
                        Quartz.CGWarpMouseCursorPosition((int(nx), int(ny)))
                    except Exception:
                        pyautogui.moveTo(int(nx), int(ny), duration=0)
                else:
                    pyautogui.moveTo(int(nx), int(ny), duration=0)
                self._last_mouse_pos = (int(nx), int(ny))
                await asyncio.sleep(step_sleep)
        except asyncio.CancelledError:
            return
    
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
    parser.add_argument('--map', choices=['normalized','preserve','relative'], default='normalized',
                        help='Mapping-Modus: normalized=volle Fläche, preserve=Seitenverhältnis erhalten, relative=Delta-Bewegung')
    parser.add_argument('--interp', action='store_true', help='Glättung der Mausbewegung aktivieren')
    parser.add_argument('--interp-rate-hz', type=int, default=240, help='Frequenz der Glättungsschritte (Default: 240 Hz)')
    parser.add_argument('--interp-step-px', type=int, default=10, help='Maximale Schrittgröße pro Glättungsschritt (Pixel)')
    parser.add_argument('--deadzone-px', type=int, default=1, help='Deadzone in Pixel zur Jitter-Filterung')
    args = parser.parse_args()

    client = KVMClient(args.server_host, args.port, map_mode=args.map,
                      interp_enabled=args.interp,
                      interp_rate_hz=args.interp_rate_hz,
                      interp_step_px=args.interp_step_px,
                      deadzone_px=args.deadzone_px)

    try:
        asyncio.run(client.run())
    except KeyboardInterrupt:
        print("\nProgramm beendet.")

    

if __name__ == "__main__":
    main()
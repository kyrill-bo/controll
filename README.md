# KVM Over Network - Tastatur/Maus über Netzwerk teilen

Dieses System ermöglicht es, Tastatur und Maus zwischen zwei Laptops über das Netzwerk zu teilen.

## Funktionsweise

- **Server (Laptop A)**: Fängt Tastatur/Maus-Events ab und sendet sie über WebSocket
- **Client (Laptop B)**: Empfängt Events und simuliert sie lokal
- **Hotkey-Switching**: `Ctrl+Alt+S` wechselt zwischen lokalem und Remote-Modus

## Installation

### Beide Laptops

```bash
# Abhängigkeiten installieren
pip install -r requirements.txt
```

**Für macOS**: Eventuell zusätzliche Berechtigungen erforderlich:
- System Preferences → Security & Privacy → Privacy → Accessibility
- Python/Terminal zu erlaubten Apps hinzufügen

## Verwendung

### Schritt 1: Server starten (Laptop A)
```bash
python server.py
```

### Schritt 2: Client starten (Laptop B)
```bash
# Für localhost (gleicher Rechner zum Testen)
python client.py

# Für Remote-Verbindung (IP-Adresse von Laptop A)
python client.py 192.168.1.100
```

### Schritt 3: Zwischen Modi wechseln

- **Lokaler Modus**: Tastatur/Maus funktioniert normal auf Laptop A
- **Remote-Modus**: Tastatur/Maus wird an Laptop B gesendet
- **Umschalten**: `Ctrl+Alt+S` auf Laptop A

## Features

### Unterstützte Events
- ✅ Maus-Bewegung
- ✅ Maus-Klicks (Links, Rechts, Mittel)
- ✅ Maus-Scroll
- ✅ Alle Tastatur-Eingaben
- ✅ Sondertasten (Ctrl, Alt, Shift, etc.)
- ✅ Pfeiltasten, F-Tasten, etc.

### Hotkeys
- `Ctrl+Alt+S`: Zwischen lokal/remote wechseln

### Status-Anzeige
Der Server zeigt deutlich an:
- Verbundene Clients
- Aktueller Modus (Lokal/Remote)
- Event-Übertragung

## Konfiguration

### Server-Port ändern
```python
# In server.py, Zeile ~15
server = KVMServer(host='0.0.0.0', port=8765)
```

### Hotkey ändern  
```python
# In server.py, Zeile ~24
self.switch_hotkey = {keyboard.Key.ctrl, keyboard.Key.alt, keyboard.KeyCode(char='x')}
```

### Maus-Geschwindigkeit
```python  
# In client.py, Zeile ~16
pyautogui.PAUSE = 0.001  # Weniger Pause = schneller
```

## Troubleshooting

### "Permission denied" Fehler
- macOS: Accessibility-Berechtigung erteilen
- Linux: Als sudo ausführen oder User zu input-Gruppe hinzufügen

### "Connection refused"
- Server läuft nicht
- Firewall blockiert Port 8765
- Falsche IP-Adresse

### Tastatur/Maus reagiert nicht
- Accessibility-Berechtigungen prüfen
- pyautogui.FAILSAFE = False gesetzt?

### Langsame Übertragung
- Netzwerk-Latenz
- `pyautogui.PAUSE` reduzieren
- Lokales Netzwerk verwenden

## Sicherheitshinweise

⚠️ **Wichtig**: Dieses Tool gibt vollständigen Zugriff auf Tastatur/Maus.
- Nur in vertrauenswürdigen Netzwerken verwenden
- Firewall-Regeln entsprechend konfigurieren
- Für Produktion: Authentifizierung hinzufügen

## Erweiterte Nutzung

### Mehrere Clients
Der Server unterstützt mehrere gleichzeitige Client-Verbindungen.

### Über Internet
```bash
# Server mit externer IP
python server.py --host 0.0.0.0

# Client mit öffentlicher IP
python client.py your-public-ip.com
```

### Automatischer Start
```bash
# Linux/macOS Autostart
crontab -e
@reboot cd /path/to/kvm && python server.py
```
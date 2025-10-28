#!/usr/bin/env python3
"""
Setup und Test Script für KVM over Network
"""
import subprocess
import sys
import os

def install_requirements():
    """Installiert alle benötigten Pakete"""
    print("📦 Installiere Abhängigkeiten...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
        print("✅ Alle Pakete erfolgreich installiert!")
        return True
    except subprocess.CalledProcessError:
        print("❌ Fehler beim Installieren der Pakete")
        return False

def check_permissions():
    """Prüft Berechtigungen (hauptsächlich für macOS)"""
    print("\n🔐 Berechtigungen prüfen...")
    
    if sys.platform == "darwin":  # macOS
        print("ℹ️  Auf macOS benötigt dieses Programm Accessibility-Berechtigungen:")
        print("   1. Systemeinstellungen → Sicherheit → Datenschutz → Bedienungshilfen")
        print("   2. Python/Terminal zur Liste hinzufügen")
        print("   3. Programm neu starten")
    elif sys.platform.startswith("linux"):
        print("ℹ️  Auf Linux eventuell als sudo ausführen oder User zur input-Gruppe hinzufügen")
    
    return True

def test_imports():
    """Testet ob alle Module importiert werden können"""
    print("\n🧪 Module testen...")
    
    modules = [
        ("websockets", "WebSocket Kommunikation"),
        ("pynput", "Tastatur/Maus Eingabe"),
        ("pyautogui", "Maus/Tastatur Simulation")
    ]
    
    all_good = True
    for module, description in modules:
        try:
            __import__(module)
            print(f"✅ {module} - {description}")
        except ImportError:
            print(f"❌ {module} - {description} (FEHLT)")
            all_good = False
    
    return all_good

def show_usage():
    """Zeigt Verwendungshinweise"""
    print("\n🚀 Verwendung:")
    print("="*50)
    print("1. Server starten (Laptop A mit Tastatur/Maus):")
    print("   python server.py")
    print()
    print("2. Client starten (Laptop B - Remote):")
    print("   python client.py                    # Localhost")
    print("   python client.py 192.168.1.100     # Remote IP")
    print()
    print("3. Umschalten mit Ctrl+Alt+S auf Laptop A")
    print("="*50)
    print()
    print("💡 Tipps:")
    print("- Beide Laptops müssen im gleichen Netzwerk sein")
    print("- Firewall/Router müssen Port 8765 freigeben")
    print("- Bei Problemen: README.md lesen")

def main():
    print("🖥️  KVM over Network - Setup")
    print("="*40)
    
    # Schritt 1: Pakete installieren
    if not install_requirements():
        print("\n❌ Setup fehlgeschlagen - Pakete konnten nicht installiert werden")
        return False
    
    # Schritt 2: Berechtigungen prüfen
    check_permissions()
    
    # Schritt 3: Module testen
    if not test_imports():
        print("\n❌ Setup fehlgeschlagen - Module fehlen")
        return False
    
    # Schritt 4: Verwendungshinweise
    show_usage()
    
    print("\n✅ Setup erfolgreich abgeschlossen!")
    print("Sie können jetzt server.py und client.py verwenden.")
    
    return True

if __name__ == "__main__":
    main()
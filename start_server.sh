#!/bin/bash
# KVM Remote Server Starter für macOS/Linux

echo "🌐 KVM Remote Server wird gestartet..."
echo "📡 Server ist über das Netzwerk erreichbar (0.0.0.0:8765)"
echo "Hotkey zum Umschalten: Cmd+>"
echo "Zum Beenden: Ctrl+C"
echo ""

# Netzwerk-IP anzeigen
echo "📍 Server erreichbar unter folgenden IPs:"
ifconfig | grep "inet " | grep -v 127.0.0.1 | awk '{print "   • " $2 ":8765"}'
echo ""

# Prüfen ob Virtual Environment existiert
if [ -f ".venv/bin/python" ]; then
    ./.venv/bin/python server.py --host 0.0.0.0 --port 8765
else
    python3 server.py --host 0.0.0.0 --port 8765
fi
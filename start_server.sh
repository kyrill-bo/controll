#!/bin/bash
# KVM Remote Server Starter für macOS/Linux

echo "🌐 KVM Remote Server wird gestartet..."
echo "📡 Server ist über das Netzwerk erreichbar (0.0.0.0:8765)"
echo "🖱️  Maus bewegt nur auf einem Gerät (F13 schaltet um)"
echo "Hotkey: F13"
echo "Zum Beenden: Ctrl+C"
echo ""

# Netzwerk-IP anzeigen
echo "📍 Server erreichbar unter folgenden IPs:"
ifconfig | grep "inet " | grep -v 127.0.0.1 | awk '{print "   • " $2 ":8765"}'
echo ""

# Prüfen ob Virtual Environment existiert
RATE_MS=${RATE_MS:-2.0}
if [ -f ".venv/bin/python" ]; then
    ./.venv/bin/python server.py --host 0.0.0.0 --port 8765 --mouse-throttle-ms "$RATE_MS"
else
    python3 server.py --host 0.0.0.0 --port 8765 --mouse-throttle-ms "$RATE_MS"
fi
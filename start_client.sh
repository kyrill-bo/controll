#!/bin/bash
# KVM Client Starter für macOS/Linux

SERVER_IP=${1:-localhost}
# Mapping-Modus: relative (empfohlen), normalized, preserve
MAP_MODE=${MAP:-relative}

echo "🖥️  KVM Client wird gestartet..."
echo "Verbinde zu Server: $SERVER_IP"
echo "Maus-Mapping: $MAP_MODE"
echo "Zum Beenden: Ctrl+C"
echo ""

# Prüfen ob Virtual Environment existiert
if [ -f ".venv/bin/python" ]; then
    ./.venv/bin/python client.py "$SERVER_IP" --map "$MAP_MODE"
else
    python3 client.py "$SERVER_IP" --map "$MAP_MODE"
fi
#!/bin/bash
# KVM Client Starter für macOS/Linux

SERVER_IP=${1:-localhost}

echo "🖥️  KVM Client wird gestartet..."
echo "Verbinde zu Server: $SERVER_IP"
echo "Zum Beenden: Ctrl+C"
echo ""

# Prüfen ob Virtual Environment existiert
if [ -f ".venv/bin/python" ]; then
    ./.venv/bin/python client.py $SERVER_IP
else
    python3 client.py $SERVER_IP
fi
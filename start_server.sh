#!/bin/bash
# KVM Server Starter für macOS/Linux

echo "🖥️  KVM Server wird gestartet..."
echo "Hotkey zum Umschalten: Ctrl+Alt+S"
echo "Zum Beenden: Ctrl+C"
echo ""

# Prüfen ob Virtual Environment existiert
if [ -f ".venv/bin/python" ]; then
    ./.venv/bin/python server.py
else
    python3 server.py
fi
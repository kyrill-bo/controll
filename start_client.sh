#!/bin/bash
# KVM Client Starter für macOS/Linux

SERVER_IP=${1:-localhost}
# Mapping-Modus: relative (empfohlen), normalized, preserve
MAP_MODE=${MAP:-relative}
# Interpolation: 1 aktiv, 0 aus
INTERP=${INTERP:-1}
INTERP_RATE=${INTERP_RATE:-240}
INTERP_STEP=${INTERP_STEP:-10}
DEADZONE_PX=${DEADZONE_PX:-1}

echo "🖥️  KVM Client wird gestartet..."
echo "Verbinde zu Server: $SERVER_IP"
echo "Maus-Mapping: $MAP_MODE"
echo "Interpolation: ${INTERP} (Rate=${INTERP_RATE}Hz, Step=${INTERP_STEP}px, Deadzone=${DEADZONE_PX}px)"
echo "Zum Beenden: Ctrl+C"
echo ""

# Prüfen ob Virtual Environment existiert
if [ -f ".venv/bin/python" ]; then
    ./.venv/bin/python client.py "$SERVER_IP" --map "$MAP_MODE" \
        $( [ "$INTERP" = "1" ] && echo "--interp" ) \
        --interp-rate-hz "$INTERP_RATE" --interp-step-px "$INTERP_STEP" \
        --deadzone-px "$DEADZONE_PX"
else
    python3 client.py "$SERVER_IP" --map "$MAP_MODE" \
        $( [ "$INTERP" = "1" ] && echo "--interp" ) \
        --interp-rate-hz "$INTERP_RATE" --interp-step-px "$INTERP_STEP" \
        --deadzone-px "$DEADZONE_PX"
fi
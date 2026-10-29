#!/bin/bash
# Desliga o EV3 com seguranca para nao corromper o cartao SD quando a energia
# acabar: bateria baixa por 5 min seguidos ou 30 min sem o backend na ponte.
LIMITE_UV=${LIMITE_UV:-6500000}
OCIOSO_MAX_MIN=${OCIOSO_MAX_MIN:-30}
BATERIA=/sys/class/power_supply/lego-ev3-battery/voltage_now
baixa=0
ocioso=0

backend_conectado() {
    # Porta 8765 = 0x223D; estado 01 = ESTABLISHED.
    awk 'NR > 1 { split($2, l, ":"); if (l[2] == "223D" && $4 == "01") ok = 1 } END { exit !ok }' /proc/net/tcp
}

desligar() {
    logger -t inteliesteira-energia "$1; desligando com seguranca."
    systemctl poweroff
    exit 0
}

while true; do
    sleep 60
    if [ -r "$BATERIA" ]; then
        uv=$(cat "$BATERIA")
        if [ "$uv" -lt "$LIMITE_UV" ]; then baixa=$((baixa + 1)); else baixa=0; fi
        [ "$baixa" -ge 5 ] && desligar "Bateria baixa (${uv} uV)"
    fi
    if backend_conectado; then ocioso=0; else ocioso=$((ocioso + 1)); fi
    [ "$ocioso" -ge "$OCIOSO_MAX_MIN" ] && desligar "${ocioso} min sem o backend"
done

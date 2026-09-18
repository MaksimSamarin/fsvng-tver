#!/usr/bin/env bash
# Полное удаление реле с VPS. Ничего, кроме своего, не трогает.
set -uo pipefail
[ "$(id -u)" = 0 ] || { echo "нужен root"; exit 1; }
systemctl disable --now relay.service relay-cert.timer 2>/dev/null
rm -f /etc/systemd/system/relay.service /etc/systemd/system/relay-cert.service /etc/systemd/system/relay-cert.timer
systemctl daemon-reload
# правила ufw с нашей пометкой — удаляем с конца, чтобы номера не съезжали
ufw status numbered | grep 'fsvng relay' | sed -E 's/^\[ *([0-9]+)\].*/\1/' | sort -rn | while read -r n; do yes | ufw delete "$n" >/dev/null; done
rm -rf /opt/relay /etc/relay
userdel relay 2>/dev/null
echo "реле удалено"

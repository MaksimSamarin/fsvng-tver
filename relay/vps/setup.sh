#!/usr/bin/env bash
# Установка реле на VPS (Ubuntu/Debian, root). Идемпотентно — можно запускать повторно.
#   PORT=8443 CERT_SRC=/root/cert/<хост> bash setup.sh
# CERT_SRC — каталог с fullchain.pem и privkey.pem уже имеющегося сертификата этого хоста.
# Ничего существующего не трогает: свой пользователь, свои каталоги, свои юниты, свои правила ufw.
set -euo pipefail
SRC="$(cd "$(dirname "$0")" && pwd)"
PORT="${PORT:-8443}"
CERT_SRC="${CERT_SRC:?укажи CERT_SRC=/root/cert/<хост>}"

[ "$(id -u)" = 0 ] || { echo "нужен root"; exit 1; }
command -v python3 >/dev/null || { echo "нет python3"; exit 1; }
command -v ufw >/dev/null || { echo "нет ufw — правила файрвола придётся сделать вручную"; exit 1; }

echo "== пользователь и каталоги"
id relay >/dev/null 2>&1 || useradd --system --no-create-home --shell /usr/sbin/nologin relay
install -d -o root -g relay -m 750 /etc/relay /etc/relay/tls
install -d -o root -g relay -m 755 /opt/relay
install -o root -g relay -m 640 "$SRC/relay.py" /opt/relay/relay.py
install -o root -g root  -m 755 "$SRC/relay-cert.sh" /opt/relay/relay-cert.sh
if [ ! -f /etc/relay/env ]; then
  install -o root -g relay -m 640 "$SRC/env.example" /etc/relay/env
  echo "!! /etc/relay/env создан из примера — заполни RELAY_SECRET и ключи, потом: systemctl restart relay"
fi

echo "== сертификат"
install -m 644 "$SRC/relay.service" "$SRC/relay-cert.service" "$SRC/relay-cert.timer" /etc/systemd/system/
sed -i "s|^Environment=CERT_SRC=.*|Environment=CERT_SRC=$CERT_SRC|" /etc/systemd/system/relay-cert.service
CERT_SRC="$CERT_SRC" /opt/relay/relay-cert.sh

echo "== файрвол: порт $PORT только для сетей Cloudflare"
tmp="$(mktemp)"
if curl -fsS --max-time 20 https://www.cloudflare.com/ips-v4 > "$tmp" && echo >> "$tmp" \
   && curl -fsS --max-time 20 https://www.cloudflare.com/ips-v6 >> "$tmp"; then
  n=0
  while read -r net; do
    [ -n "$net" ] || continue
    ufw allow from "$net" to any port "$PORT" proto tcp comment 'fsvng relay (Cloudflare only)' >/dev/null && n=$((n+1))
  done < "$tmp"
  echo "правил ufw: $n"
else
  echo "!! список сетей Cloudflare не скачался — порт НЕ открыт, повтори позже"; rm -f "$tmp"; exit 1
fi
rm -f "$tmp"

echo "== сервисы"
systemctl daemon-reload
systemctl enable --now relay-cert.timer >/dev/null
systemctl enable relay.service >/dev/null
systemctl restart relay.service
sleep 1
systemctl --no-pager --lines=4 status relay.service | sed -n '1,12p'
echo "== готово. Проверка: journalctl -u relay -n 20 --no-pager"

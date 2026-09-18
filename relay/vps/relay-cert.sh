#!/usr/bin/env bash
# Кладёт актуальный сертификат для реле. Запускается таймером раз в сутки и при установке.
# Ничего в acme-конфигах не трогает: просто копирует то, что acme.sh уже продлил.
set -euo pipefail
SRC="${CERT_SRC:-/root/cert/relay}"
DST=/etc/relay/tls
for f in fullchain.pem privkey.pem; do
  [ -f "$SRC/$f" ] || { echo "нет $SRC/$f"; exit 1; }
  if ! cmp -s "$SRC/$f" "$DST/$f" 2>/dev/null; then
    install -o root -g relay -m 640 "$SRC/$f" "$DST/$f"
    echo "обновлён $f"
  fi
done

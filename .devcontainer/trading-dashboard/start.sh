#!/usr/bin/env bash
# Läuft bei jedem Start des Codespace: Schnittstelle samt Dashboard hochfahren.
#
# Bewusst `webserver` und nicht `trade`: der Webserver-Modus braucht keine
# Börsenverbindung und startet deshalb immer. Zum Handeln im Dry-Run stattdessen
# im Terminal:
#
#   .venv-frei — hier ist das Paket global installiert:
#   freqtrade trade -c trading_project/bot-config.json \
#     -c user_data/config.local.json --userdir user_data --strategy SampleStrategy
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

if curl -fsS --max-time 2 http://127.0.0.1:8080/api/v1/ping >/dev/null 2>&1; then
  echo "Läuft bereits auf Port 8080."
  exit 0
fi

mkdir -p user_data/logs
nohup freqtrade webserver \
  -c trading_project/bot-config.json \
  -c user_data/config.local.json \
  --userdir user_data \
  > user_data/logs/webserver.log 2>&1 &

for _ in $(seq 1 15); do
  sleep 1
  if curl -fsS --max-time 2 http://127.0.0.1:8080/api/v1/ping >/dev/null 2>&1; then
    echo "Dashboard läuft auf Port 8080."
    echo "Im Reiter PORTS die Adresse zu 8080 öffnen."
    exit 0
  fi
done

echo "Start fehlgeschlagen. Protokoll: user_data/logs/webserver.log" >&2
exit 1

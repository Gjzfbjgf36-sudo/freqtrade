#!/usr/bin/env bash
#
# Richtet Freqtrade samt Dashboard auf einem frischen Debian- oder
# Ubuntu-Server ein. Gedacht zum Einfügen in die Web-Konsole eines
# V-Servers — es wird kein eigener Rechner gebraucht.
#
# Aufruf als root:
#   bash setup-vps.sh
#
# Danach läuft der Bot im Dry-Run als Dienst und liefert das Dashboard unter
# 127.0.0.1:8080 aus. Den Weg nach außen legt cloudflared an; die beiden
# Befehle dafür gibt das Skript am Ende aus, weil sie eine Anmeldung im
# Browser brauchen.
#
# Anpassbar über Umgebungsvariablen:
#   REPO=https://github.com/…/freqtrade.git
#   BRANCH=claude/happy-edison-uhgij2
#   DIR=/opt/freqtrade
#   BOT_USER=freqtrade

set -euo pipefail

REPO="${REPO:-https://github.com/Gjzfbjgf36-sudo/freqtrade.git}"
BRANCH="${BRANCH:-claude/happy-edison-uhgij2}"
DIR="${DIR:-/opt/freqtrade}"
BOT_USER="${BOT_USER:-freqtrade}"

say() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
die() { printf '\n\033[31mAbbruch: %s\033[0m\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "Bitte als root ausführen (oder mit sudo davor)."
command -v apt-get >/dev/null || die "Dieses Skript ist für Debian oder Ubuntu."

say "Systempakete"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq git curl ca-certificates build-essential \
  python3 python3-venv python3-dev

say "Benutzer $BOT_USER"
if ! id -u "$BOT_USER" >/dev/null 2>&1; then
  # Eigener Benutzer ohne Anmelderecht: der Bot braucht keine Shell.
  useradd --system --create-home --shell /usr/sbin/nologin "$BOT_USER"
  echo "angelegt"
else
  echo "vorhanden"
fi

say "Quellcode nach $DIR"
if [ -d "$DIR/.git" ]; then
  git -C "$DIR" fetch --depth 1 origin "$BRANCH"
  git -C "$DIR" checkout -B "$BRANCH" "origin/$BRANCH"
  echo "aktualisiert"
else
  git clone --depth 1 --branch "$BRANCH" "$REPO" "$DIR"
fi
chown -R "$BOT_USER:$BOT_USER" "$DIR"

say "Python-Umgebung (dauert ein paar Minuten)"
sudo -u "$BOT_USER" python3 -m venv "$DIR/.venv"
sudo -u "$BOT_USER" "$DIR/.venv/bin/pip" install --quiet --upgrade pip
sudo -u "$BOT_USER" "$DIR/.venv/bin/pip" install --quiet -e "$DIR"

say "Strategie und Benutzerverzeichnis"
sudo -u "$BOT_USER" mkdir -p "$DIR/user_data/strategies" "$DIR/user_data/logs" "$DIR/user_data/data"
[ -f "$DIR/user_data/strategies/SampleStrategy.py" ] || \
  sudo -u "$BOT_USER" cp "$DIR/freqtrade/templates/sample_strategy.py" \
    "$DIR/user_data/strategies/SampleStrategy.py"

say "Zugangsdaten"
LOCAL_CFG="$DIR/user_data/config.local.json"
if [ -f "$LOCAL_CFG" ]; then
  echo "$LOCAL_CFG besteht bereits — bleibt unverändert"
  API_PASS="$(sudo -u "$BOT_USER" "$DIR/.venv/bin/python" -c \
    "import json;print(json.load(open('$LOCAL_CFG'))['api_server']['password'])")"
else
  API_PASS="$(sudo -u "$BOT_USER" "$DIR/.venv/bin/python" - "$LOCAL_CFG" <<'PY'
import json, secrets, sys

pw = secrets.token_urlsafe(18)
cfg = {
    "api_server": {
        "username": "freqtrader",
        "password": pw,
        "jwt_secret_key": secrets.token_hex(32),
        "ws_token": secrets.token_urlsafe(24),
    }
}
with open(sys.argv[1], "w") as fh:
    json.dump(cfg, fh, indent=4)
print(pw)
PY
)"
  chmod 600 "$LOCAL_CFG"
  chown "$BOT_USER:$BOT_USER" "$LOCAL_CFG"
  echo "neu erzeugt"
fi

say "Dashboard"
sudo -u "$BOT_USER" env PYTHON="$DIR/.venv/bin/python" "$DIR/trading_project/install-dashboard.sh"

say "Dienst"
cat > /etc/systemd/system/freqtrade.service <<UNIT
[Unit]
Description=Freqtrade (Dry-Run)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$BOT_USER
WorkingDirectory=$DIR
ExecStart=$DIR/.venv/bin/freqtrade trade \\
  -c $DIR/trading_project/bot-config.json \\
  -c $DIR/user_data/config.local.json \\
  --userdir $DIR/user_data \\
  --strategy SampleStrategy
Restart=on-failure
RestartSec=30

# Der Bot braucht weder fremde Verzeichnisse noch neue Rechte.
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=true
ReadWritePaths=$DIR/user_data

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable --quiet freqtrade
systemctl restart freqtrade

say "cloudflared"
if ! command -v cloudflared >/dev/null; then
  curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg \
    -o /usr/share/keyrings/cloudflare-main.gpg
  echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main" \
    > /etc/apt/sources.list.d/cloudflared.list
  apt-get update -qq
  apt-get install -y -qq cloudflared
fi
cloudflared --version

say "Kontrolle"
sleep 8
if curl -fsS --max-time 5 http://127.0.0.1:8080/api/v1/ping >/dev/null; then
  echo "Die Schnittstelle antwortet."
else
  echo "Die Schnittstelle antwortet noch nicht. Protokoll ansehen mit:"
  echo "  journalctl -u freqtrade -n 50 --no-pager"
fi

cat <<INFO

========================================================================
Fertig.

  Benutzer:  freqtrader
  Passwort:  $API_PASS

Dieses Passwort steht in $LOCAL_CFG und wird hier nur einmal angezeigt.

Bleibt der Weg nach außen. Zum Ausprobieren, sofort und ohne Konto:

  cloudflared tunnel --url http://127.0.0.1:8080

Das gibt eine Adresse aus, die du vom iPad öffnen kannst. Sie gilt, solange
der Befehl läuft, und ist nur durch das Passwort oben geschützt.

Für eine feste Adresse mit Anmeldung davor:

  cloudflared tunnel login
  cloudflared tunnel create freqtrade
  cloudflared tunnel route dns freqtrade bot.deine-domain.de

Danach die Vorlage einrichten und als Dienst starten:

  mkdir -p /root/.cloudflared
  cp $DIR/trading_project/remote-access/cloudflared-config.example.yml \\
     /root/.cloudflared/config.yml
  nano /root/.cloudflared/config.yml      # Tunnel-ID und Hostname eintragen
  cloudflared service install
  systemctl enable --now cloudflared

Die Schritte im Einzelnen, samt Cloudflare Access als Anmeldung:
  $DIR/trading_project/remote-access/README.md

Hinweis: Der Bot läuft im Dry-Run, also auf Papier. Echtes Geld bewegt er
erst, wenn du in bot-config.json dry_run auf false setzt und Börsenschlüssel
hinterlegst.
========================================================================
INFO

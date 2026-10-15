#!/usr/bin/env bash
# Läuft einmal beim Anlegen des Codespace: Freqtrade installieren, Strategie
# ablegen, Zugangsdaten erzeugen, Dashboard in die Oberfläche des Bots kopieren.
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

echo "== Freqtrade installieren (dauert ein paar Minuten)"
pip install --quiet --upgrade pip
pip install --quiet -e .
pip install --quiet pytest pytest-xdist

echo "== Benutzerverzeichnis und Strategie"
mkdir -p user_data/strategies user_data/logs user_data/data
[ -f user_data/strategies/SampleStrategy.py ] || \
  cp freqtrade/templates/sample_strategy.py user_data/strategies/SampleStrategy.py

echo "== Zugangsdaten"
if [ ! -f user_data/config.local.json ]; then
  python - <<'PY'
import json, secrets

cfg = {
    "api_server": {
        "username": "freqtrader",
        "password": secrets.token_urlsafe(18),
        "jwt_secret_key": secrets.token_hex(32),
        "ws_token": secrets.token_urlsafe(24),
    }
}
with open("user_data/config.local.json", "w") as fh:
    json.dump(cfg, fh, indent=4)
PY
  chmod 600 user_data/config.local.json
fi

echo "== Dashboard"
PYTHON="$(command -v python)" ./trading_project/install-dashboard.sh

echo
echo "Fertig. Anmeldedaten:"
python -c "import json;d=json.load(open('user_data/config.local.json'))['api_server'];print('  Benutzer:',d['username']);print('  Passwort:',d['password'])"

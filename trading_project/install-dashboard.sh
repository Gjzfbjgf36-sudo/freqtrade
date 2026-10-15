#!/usr/bin/env bash
# Legt das Dashboard dorthin, wo Freqtrade seine Weboberfläche ausliefert.
# Danach zeigt die Adresse des Bots direkt das Dashboard — gleiche Herkunft,
# also kein CORS und kein Mixed-Content-Problem.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python="${PYTHON:-$here/../.venv/bin/python}"

if [ ! -x "$python" ]; then
  echo "Python aus dem venv nicht gefunden: $python" >&2
  echo "Mit PYTHON=/pfad/zu/python erneut aufrufen." >&2
  exit 1
fi

target="$("$python" -c 'import freqtrade.rpc.api_server as m, pathlib; print(pathlib.Path(m.__file__).parent / "ui" / "installed")')"

mkdir -p "$target"
cp "$here/dashboard/index.html" "$target/index.html"

echo "Dashboard installiert: $target/index.html"
echo "Es wird unter der Adresse des API-Servers ausgeliefert, standardmäßig http://127.0.0.1:8080"

# Trading-Projekt: Dry-Run-Bot mit eigenem Leitstand

Lauffähiges Freqtrade-Setup im Dry-Run (Binance Spot) plus eine eigene Weboberfläche,
die den Bot über dessen REST-Schnittstelle ausliest.

```
trading_project/
├── bot-config.json        Bot-Konfiguration (Dry-Run, keine Zugangsdaten)
└── dashboard/index.html   Weboberfläche, eine Datei ohne Build-Schritt
```

Die Strategie liegt unter `user_data/strategies/SampleStrategy.py` (Kopie der
mitgelieferten Vorlage). Zugangsdaten gehören in `user_data/config.local.json` —
dieser Pfad ist über `.gitignore` ausgeschlossen und darf nie eingecheckt werden.

## 1. Installation

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
mkdir -p user_data/strategies
cp freqtrade/templates/sample_strategy.py user_data/strategies/SampleStrategy.py
```

## 2. Zugangsdaten anlegen

`user_data/config.local.json` ergänzt `bot-config.json` und überschreibt die
Platzhalter darin:

```json
{
    "api_server": {
        "username": "freqtrader",
        "password": "<eigenes Passwort>",
        "jwt_secret_key": "<zufällige 64 Hex-Zeichen>",
        "ws_token": "<zufälliger Token>"
    }
}
```

Zufallswerte erzeugen:

```bash
.venv/bin/python -c "import secrets; print(secrets.token_urlsafe(18), secrets.token_hex(32))"
```

## 3. Bot starten

```bash
.venv/bin/freqtrade trade \
  -c trading_project/bot-config.json \
  -c user_data/config.local.json \
  --userdir user_data \
  --strategy SampleStrategy
```

Der Bot handelt mit `"dry_run": true` auf Papier, ein Startguthaben von 1.000 USDT
ist in der Konfiguration hinterlegt. Es werden keine Börsen-Zugangsdaten benötigt,
wohl aber eine Netzwerkverbindung zu `api.binance.com` — ohne sie bricht der Start
mit `Could not load markets` ab.

Nur die Schnittstelle ohne Handel (für das Dashboard und für Backtests):

```bash
.venv/bin/freqtrade webserver \
  -c trading_project/bot-config.json \
  -c user_data/config.local.json \
  --userdir user_data
```

## 4. Dashboard öffnen

```bash
npx http-server trading_project/dashboard -p 8081
```

Dann `http://127.0.0.1:8081` aufrufen, oben API-Adresse, Benutzer und Passwort
eintragen und verbinden. Die Seite meldet sich über `/api/v1/token/login` an und
aktualisiert sich alle fünf Sekunden.

Ohne Verbindung zeigt sie klar gekennzeichnete Beispieldaten, damit jedes Element
sichtbar ist.

Die Oberfläche liest ausschließlich: `show_config`, `status`, `profit`, `balance`,
`daily`, `performance`, `whitelist`, `count`, `logs`. Sie löst keine Orders aus.

**Herkunft freischalten:** Der Browser darf eine fremde Herkunft nur abfragen, wenn
sie in `api_server.CORS_origins` steht. Für den Aufruf oben sind
`http://127.0.0.1:8081` und `http://localhost:8081` bereits eingetragen. Wird das
Dashboard anderswo gehostet, muss diese Adresse dort ergänzt werden.

## Konfiguration im Überblick

| Einstellung | Wert |
| --- | --- |
| Modus | Dry-Run, Spot |
| Börse | Binance |
| Einsatzwährung | USDT, 50 je Position |
| Max. gleichzeitige Positionen | 5 |
| Startguthaben (Dry-Run) | 1.000 USDT |
| Zeitrahmen | 5m |
| Paarliste | StaticPairList, 10 Paare |
| API-Server | 127.0.0.1:8080, aktiviert |

## Bekannte Einschränkung in der Cloud-Session

In der Claude-Cloud-Umgebung, in der dieses Setup gebaut wurde, verweigert die
Netzwerk-Policy jede Verbindung zu Börsen-Hosts (`api.binance.com` und andere
antworten mit `403` auf den CONNECT des Proxys). Deshalb läuft dort der
`webserver`-Modus, der eigentliche Handelsstart aber nicht. Lokal oder mit
freigegebener Domain funktioniert `freqtrade trade` unverändert.

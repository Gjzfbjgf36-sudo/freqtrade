# Trading-Projekt: Dry-Run-Bot mit eigenem Leitstand

Lauffähiges Freqtrade-Setup im Dry-Run (Binance Spot) plus eine eigene Weboberfläche,
die den Bot über dessen REST-Schnittstelle ausliest.

```
trading_project/
├── bot-config.json        Bot-Konfiguration (Dry-Run, keine Zugangsdaten)
├── freqai-config.json     Ergänzung für den FreqAI-Betrieb
├── dashboard/index.html   Weboberfläche, eine Datei ohne Build-Schritt
├── install-dashboard.sh   liefert die Oberfläche über den Bot selbst aus
├── strategies/            RealizedVolStrategy (FreqAI, Realized Volatility)
└── tests/                 Prüfungen der Merkmale, ohne Börsenverbindung
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

## 4. Dashboard öffnen (lokal)

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

## 5. Von überall erreichbar

Das Dashboard kann vom Bot selbst ausgeliefert werden:

```bash
./trading_project/install-dashboard.sh
```

Das Skript kopiert die Seite nach `freqtrade/rpc/api_server/ui/installed/`.
Danach zeigt die Adresse des API-Servers direkt das Dashboard, und die Seite
erkennt ihre eigene Herkunft als Bot-Adresse — gleiche Herkunft heißt: kein
CORS-Eintrag nötig und kein Mixed-Content-Problem. Eine Adresse für Oberfläche
und Schnittstelle.

Diese eine Adresse muss nun von außen erreichbar sein. Drei Wege, vom sichersten
zum offensten:

**Tailscale oder WireGuard (empfohlen).** Der Bot bleibt in einem privaten Netz,
kein Port zeigt ins Internet. Von jedem eigenen Gerät erreichbar unter
`http://<rechnername>:8080`. In der Konfiguration dafür
`"listen_ip_address": "0.0.0.0"` setzen.

**Cloudflare Tunnel.** Ergibt eine öffentliche HTTPS-Adresse ohne Portfreigabe:

```bash
cloudflared tunnel --url http://127.0.0.1:8080
```

Davor gehört eine zweite Hürde, etwa Cloudflare Access, sonst steht die
Schnittstelle offen im Netz.

**Eigener Server mit Reverse-Proxy.** Nginx oder Caddy mit TLS-Zertifikat vor
dem Bot. Nur sinnvoll, wenn ohnehin ein Server läuft.

### Was dabei zu beachten ist

Die Schnittstelle kann mehr als lesen: Positionen zwangsweise schließen, den Bot
anhalten, bei Live-Betrieb Orders auslösen. Wer die Adresse und das Passwort hat,
steuert den Bot.

* Niemals ohne TLS über das offene Internet — die Anmeldung ginge im Klartext.
* Langes, einmaliges Passwort in `user_data/config.local.json`, nicht das aus
  irgendeiner Beispielkonfiguration.
* `jwt_secret_key` zufällig erzeugen und nicht weitergeben.
* `listen_ip_address` nur dann auf `0.0.0.0` stellen, wenn ein Tunnel oder ein
  privates Netz davor liegt.

Das Dashboard selbst ruft ausschließlich lesende Endpunkte auf. Die schreibenden
sind davon unberührt erreichbar — die Absicherung hängt am Bot, nicht an der
Seite.

## 6. RealizedVolStrategy (FreqAI)

`trading_project/strategies/RealizedVolStrategy.py` übersetzt die Messgrößen der
Realized-Volatility-Literatur in FreqAI-Merkmale: Realized Variance, Realized
Semivariance (gute gegen schlechte Schwankung), Bipower Variation und die daraus
abgeleitete Sprungkomponente, Realized Skew und Kurtosis, Volatilität der
Volatilität sowie die HAR-Struktur über Stunde, Tag und Woche. Alles wird aus
den eigenen OHLCV-Kerzen gerechnet, ein externer Datensatz ist nicht nötig.

Die Zielgröße ist die vorwärtsgerichtete Rendite geteilt durch die zum
Vorhersagezeitpunkt bekannte Volatilität. Das Modell sagt Bewegung in Einheiten
der Standardabweichung voraus; die Ein- und Ausstiegsschwellen
(`entry_sigma`, `exit_sigma`) sind entsprechend in Sigma angegeben.

Zusätzliche Abhängigkeiten:

```bash
.venv/bin/pip install -r requirements-freqai.txt
```

Backtest:

```bash
.venv/bin/freqtrade backtesting \
  -c trading_project/bot-config.json \
  -c user_data/config.local.json \
  -c trading_project/freqai-config.json \
  --strategy RealizedVolStrategy \
  --strategy-path trading_project/strategies \
  --freqaimodel LightGBMRegressor \
  --timerange 20260801-20260901
```

Vorher die Daten laden: `freqtrade download-data --timeframes 5m 1h 4h --days 120`.

### Prüfungen

```bash
.venv/bin/pip install pytest
.venv/bin/python -m pytest trading_project/tests -q
```

Elf Tests, keine Börsenverbindung nötig. Der wichtigste ist
`test_features_do_not_look_ahead`: er rechnet jedes Merkmal einmal auf dem
vollständigen und einmal auf einem abgeschnittenen Kursverlauf und vergleicht
die gemeinsamen Zeitpunkte. Weicht ein Wert ab, benutzt das Merkmal Daten aus
der Zukunft. Die übrigen prüfen die Messgrößen gegen ihre Definition
(RS⁺ + RS⁻ = RV, BV ≤ RV bei Sprüngen, Anteile in [0, 1]) und schließen NaN,
unendliche und konstante Merkmale nach der Aufwärmphase aus.

Diese Tests sagen nichts über die Ertragskraft aus. Dafür gehören vor jedem
Einsatz zusätzlich `freqtrade lookahead-analysis` und
`freqtrade recursive-analysis` über die Strategie — beide brauchen echte
Marktdaten.

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
antworten mit `403` auf den CONNECT des Proxys).

Freqtrade lädt vor jedem Lauf die Marktliste der Börse — auch beim Backtest, auch
mit bereits vorhandenen Kursdaten. Ohne Freigabe laufen deshalb nur der
`webserver`-Modus und die Tests unter `trading_project/tests`; `freqtrade trade`
und `freqtrade backtesting` brechen mit `Could not load markets` ab. Lokal oder
mit freigegebener Domain funktionieren beide unverändert.

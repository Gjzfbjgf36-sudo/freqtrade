# Den Bot über Cloudflare Tunnel erreichbar machen

Ergebnis: eine HTTPS-Adresse, die von jedem Gerät funktioniert, ohne offenen
Port am Router und ohne feste IP. Davor eine Anmeldung, sodass nicht jeder, der
die Adresse kennt, deinen Bot steuern kann.

Der Tunnel läuft auf demselben Rechner wie der Bot und erreicht ihn über
`127.0.0.1`. Der Bot bleibt dadurch nach außen unsichtbar — `listen_ip_address`
bleibt auf `127.0.0.1`, nichts wird ans Netz gebunden.

```
Browser ──HTTPS──> Cloudflare ──Tunnel──> cloudflared ──127.0.0.1:8080──> Freqtrade
                        │
                   Cloudflare Access (Anmeldung)
```

## Vorbereitung

Dashboard vom Bot ausliefern lassen, damit eine Adresse genügt:

```bash
./trading_project/install-dashboard.sh
```

Bot starten (siehe Haupt-README). Prüfen, dass lokal alles läuft:

```bash
curl -s http://127.0.0.1:8080/api/v1/ping     # {"status":"pong"}
```

## Schritt 1: cloudflared installieren

Debian/Ubuntu/Raspberry Pi OS:

```bash
curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg \
  | sudo tee /usr/share/keyrings/cloudflare-main.gpg >/dev/null
echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main" \
  | sudo tee /etc/apt/sources.list.d/cloudflared.list
sudo apt update && sudo apt install cloudflared
```

macOS: `brew install cloudflared`

## Schritt 2: Schnelltest

Ohne Konto, ohne Domain — zum Ausprobieren:

```bash
cloudflared tunnel --url http://127.0.0.1:8080
```

Im Ausgabetext steht eine Adresse der Form
`https://zufaellige-woerter.trycloudflare.com`. Die zeigt sofort dein Dashboard,
von jedem Gerät aus.

Zwei Einschränkungen: Die Adresse ändert sich bei jedem Neustart, und sie ist
**ungeschützt** — wer sie errät oder mitliest, steht vor der Anmeldemaske deines
Bots. Für den Dauerbetrieb Schritt 3 und 4.

## Schritt 3: Dauerhafte Adresse

Braucht ein kostenloses Cloudflare-Konto und eine Domain, deren Nameserver auf
Cloudflare zeigen.

```bash
cloudflared tunnel login                      # öffnet den Browser
cloudflared tunnel create freqtrade           # legt den Tunnel an
cloudflared tunnel route dns freqtrade bot.deine-domain.de
```

`cloudflared tunnel create` gibt eine Tunnel-ID aus und legt die Zugangsdatei
unter `~/.cloudflared/<TUNNEL-ID>.json` ab. Beides wird in der Konfiguration
gebraucht.

`cloudflared-config.example.yml` aus diesem Ordner kopieren und anpassen:

```bash
mkdir -p ~/.cloudflared
cp trading_project/remote-access/cloudflared-config.example.yml ~/.cloudflared/config.yml
${EDITOR:-nano} ~/.cloudflared/config.yml      # Tunnel-ID und Hostname eintragen
```

Testlauf:

```bash
cloudflared tunnel run freqtrade
```

`https://bot.deine-domain.de` sollte jetzt das Dashboard zeigen.

## Schritt 4: Anmeldung davorschalten

Ohne diesen Schritt steht die Schnittstelle deines Bots öffentlich im Netz,
geschützt nur durch dein Passwort. Cloudflare Access setzt eine Anmeldung davor
— kostenlos bis 50 Nutzer.

Im Cloudflare-Dashboard: **Zero Trust → Access → Applications → Add an
application → Self-hosted**

* Application domain: `bot.deine-domain.de`
* Policy: *Allow*, Include → **Emails** → deine E-Mail-Adresse

Danach fragt Cloudflare vor jedem Zugriff einen Einmalcode per E-Mail ab. Erst
dahinter kommt die Anmeldung von Freqtrade selbst. Das Dashboard funktioniert
unverändert: der Access-Cookie gilt für dieselbe Herkunft und wird bei jedem
Aufruf mitgeschickt.

## Schritt 5: Automatisch starten

```bash
sudo cloudflared service install
sudo systemctl enable --now cloudflared
systemctl status cloudflared
```

Für den Bot selbst liegt im Projektstamm `freqtrade.service` als Vorlage.

## Prüfliste

| Punkt | Soll |
| --- | --- |
| `listen_ip_address` | `127.0.0.1` — der Tunnel läuft lokal, der Bot gehört nicht ans Netz |
| Passwort in `config.local.json` | lang, einmalig, nirgends sonst verwendet |
| `jwt_secret_key` | zufällig erzeugt, nicht aus einer Beispieldatei |
| Cloudflare Access | eingerichtet, bevor die Adresse irgendwo auftaucht |
| `CORS_origins` | bleibt leer — gleiche Herkunft braucht keinen Eintrag |
| `~/.cloudflared/*.json` | ist der Schlüssel zum Tunnel, gehört nicht ins Repository |

Zur Erinnerung, warum das alles: über die Schnittstelle lassen sich Positionen
zwangsweise schließen, der Bot anhalten und im Livebetrieb Orders auslösen. Die
Adresse ist nicht nur eine Anzeige.

## Wenn etwas nicht geht

**502 im Browser** — der Bot läuft nicht oder hört auf einem anderen Port.
`curl http://127.0.0.1:8080/api/v1/ping` auf dem Bot-Rechner prüfen.

**Dashboard lädt, aber „Nicht verbunden"** — die Seite wird nicht vom Bot
ausgeliefert. `install-dashboard.sh` ausführen und den Bot neu starten. Zur
Kontrolle: `curl -s https://bot.deine-domain.de/api/v1/ping` muss `pong` liefern.

**Anmeldung schlägt fehl** — Benutzername und Passwort kommen aus
`user_data/config.local.json`, nicht aus `bot-config.json`; dort stehen nur
Platzhalter.

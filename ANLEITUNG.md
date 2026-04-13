# WoW M+ Shuffle Bot – Einrichtungsanleitung

---

## Schritt 1: Discord Bot erstellen & Token holen

### 1.1 Discord Developer Portal öffnen
1. Gehe zu: **https://discord.com/developers/applications**
2. Melde dich mit deinem Discord-Account an

### 1.2 Neue Anwendung erstellen
1. Klicke oben rechts auf **"New Application"**
2. Gib einen Namen ein, z.B. `WoW Shuffle Bot`
3. Hake die Nutzungsbedingungen ab → **"Create"**

### 1.3 Bot erstellen
1. Im linken Menü auf **"Bot"** klicken
2. Unter **"Token"** auf **"Reset Token"** klicken → bestätigen
3. Den Token **kopieren und sicher aufbewahren** (er wird nur einmal angezeigt!)
   > ⚠️ **Wichtig:** Den Token niemals öffentlich teilen oder in den Code einfügen!

### 1.4 Bot-Berechtigungen setzen
Noch auf der Bot-Seite:
- **"Public Bot"** → ausschalten (damit nur du ihn einladen kannst)
- Unter **"Privileged Gateway Intents"** nichts ändern (werden nicht benötigt)

### 1.5 Bot zum Server einladen
1. Im linken Menü auf **"OAuth2"** → **"URL Generator"**
2. Unter **"Scopes"** auswählen:
   - ✅ `bot`
   - ✅ `applications.commands`
3. Unter **"Bot Permissions"** auswählen:
   - ✅ `Send Messages`
   - ✅ `Read Messages/View Channels`
   - ✅ `Embed Links`
   - ✅ `Read Message History`
4. Die generierte URL kopieren → im Browser öffnen
5. Deinen Gilden-Server auswählen → **"Autorisieren"**

---

## Schritt 2: Python installieren (falls noch nicht vorhanden)

### Windows
1. Gehe zu **https://www.python.org/downloads/**
2. Lade **Python 3.11** oder neuer herunter
3. Beim Installieren **"Add Python to PATH"** anhaken!
4. Installation abschließen

Prüfen ob es funktioniert hat (in der Eingabeaufforderung/cmd):
```
python --version
```

---

## Schritt 3: Bot einrichten

### 3.1 Projektordner öffnen
Öffne ein Terminal / die Eingabeaufforderung im Projektordner:
```
cd "C:\Pfad\zum\discord-wow-shuffle"
```

### 3.2 Abhängigkeiten installieren
```
pip install -r requirements.txt
```

### 3.3 .env Datei erstellen
1. Kopiere die Datei `.env.example` und benenne sie um zu `.env`
2. Öffne `.env` mit einem Texteditor (z.B. Notepad)
3. Füge deinen Token ein:

```
DISCORD_TOKEN=dein_token_den_du_kopiert_hast
TIMEZONE=Europe/Berlin
```

---

## Schritt 4: Bot starten (lokal / auf eigenem PC)

```
python bot.py
```

Im Terminal sollte erscheinen:
```
Bot gestartet als WoW Shuffle Bot#1234 | Zeitzone: Europe/Berlin
```

> **Hinweis:** Der Bot läuft nur solange das Terminal offen ist. Für einen dauerhaft laufenden Bot → siehe Abschnitt "Hosting auf einem Server"

---

## Schritt 5: Bot im Discord benutzen

### Event erstellen (nur für Admins mit "Server verwalten"-Recht):
```
/shuffle create datum:15.04.2024 uhrzeit:20:00 rundendauer:45
```

| Parameter | Erklärung | Beispiel |
|-----------|-----------|---------|
| `datum` | Datum des Events | `15.04.2024` |
| `uhrzeit` | Startzeit (Lokalzeit) | `20:00` |
| `rundendauer` | Minuten pro Runde | `45` |

### Was passiert dann:
1. Anmeldeformular erscheint sofort im Channel
2. Spieler klicken auf 🛡️ Tank, 💚 Heiler oder ⚔️ DD
3. Um 20:00 Uhr → Bot baut automatisch Gruppen
4. Nach 45 Min → Runde 2 (Neushuffle)
5. Nach 45 weiteren Min → Runde 3
6. Nach Runde 3 → Event beendet

---

## Hosting auf einem Server (dauerhaft laufen lassen)

Damit der Bot 24/7 läuft ohne dass dein PC an sein muss, gibt es mehrere Möglichkeiten:

---

### Option A: Railway (kostenlos, einfach) ⭐ Empfohlen für Anfänger

1. Gehe zu **https://railway.app** → kostenlos registrieren
2. **"New Project"** → **"Deploy from GitHub repo"**
3. Verbinde dein GitHub und lade den Projektordner hoch
4. Unter **"Variables"** die Umgebungsvariablen eintragen:
   - `DISCORD_TOKEN` = dein Token
   - `TIMEZONE` = `Europe/Berlin`
5. Railway startet den Bot automatisch

> **Gratis-Limit:** ~500 Stunden/Monat (reicht für einen Bot)

---

### Option B: VPS bei Hetzner (ab ~4€/Monat, professionell)

**Server mieten:**
1. Gehe zu **https://www.hetzner.com/cloud**
2. Neuen Server erstellen: `CX11` (kleinste Größe, ~4€/Monat)
3. Betriebssystem: **Ubuntu 22.04**
4. Server-Zugang per SSH

**Bot einrichten (auf dem Server):**
```bash
# Python & pip installieren
sudo apt update && sudo apt install python3 python3-pip -y

# Projektdateien hochladen (z.B. via FileZilla oder scp)
# Dann im Projektordner:
pip3 install -r requirements.txt

# .env Datei erstellen
nano .env
# Token und Timezone eintragen, dann Strg+X → Y → Enter

# Bot dauerhaft laufen lassen mit screen
sudo apt install screen -y
screen -S wowbot
python3 bot.py
# Strg+A dann D → screen läuft im Hintergrund weiter
```

Bot nach Server-Neustart automatisch starten:
```bash
# Service-Datei erstellen
sudo nano /etc/systemd/system/wowbot.service
```
Inhalt:
```ini
[Unit]
Description=WoW Shuffle Discord Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/discord-wow-shuffle
ExecStart=/usr/bin/python3 bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```
```bash
sudo systemctl enable wowbot
sudo systemctl start wowbot
# Status prüfen:
sudo systemctl status wowbot
```

---

### Option C: Raspberry Pi (einmalig ~50€, dann kostenlos)

Falls du einen Raspberry Pi hast:
1. Python ist bereits installiert
2. Projektdateien kopieren
3. Gleiche Schritte wie bei Option B (systemd Service)

---

## Fehlerbehebung

| Problem | Lösung |
|---------|--------|
| `DISCORD_TOKEN not found` | `.env` Datei prüfen, Token korrekt eintragen |
| Bot erscheint offline | Token prüfen, Bot neu starten |
| Slash Commands erscheinen nicht | 1-2 Minuten warten nach erstem Start (Discord synchronisiert) |
| `Missing Permissions` | Bot-Rolle im Server hat nicht genug Rechte → Bot neu einladen mit korrekten Berechtigungen |
| Bot reagiert nicht auf Buttons nach Neustart | Normal – nach Neustart werden Views neu registriert, dann funktioniert es wieder |

---

## Zusammenfassung: Schnellstart

```
1. discord.com/developers/applications → Bot erstellen → Token kopieren
2. Bot zum Server einladen (OAuth2 URL Generator)
3. .env Datei anlegen mit Token
4. pip install -r requirements.txt
5. python bot.py
6. Im Discord: /shuffle create datum:TT.MM.JJJJ uhrzeit:HH:MM rundendauer:45
```

# Shufflem - World of Warcraft Mythic+ Discord Bot

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Discord.py](https://img.shields.io/badge/Discord.py-2.3+-5865F2?style=for-the-badge&logo=discord&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-local-003B57?style=for-the-badge&logo=sqlite&logoColor=white)
![World of Warcraft](https://img.shields.io/badge/WoW-Mythic+-F8B700?style=for-the-badge)

**Shufflem** ist ein **Discord-Bot für World of Warcraft Mythic+ Events**. Der Bot organisiert Anmeldungen, bildet automatisch faire 5er-Gruppen und reshuffelt die Spieler über mehrere Runden hinweg.

Das Tool ist besonders für Gilden, Communities oder feste M+ Gruppen gedacht, die mehrere Dungeon-Runs parallel planen möchten, ohne Gruppen manuell zusammenstellen und Spieler auf der Bench im Blick behalten zu müssen.

> Kurz gesagt: Shufflem ist ein WoW Mythic+ Discord Bot für Gilden, M+ Communities, Dungeon-Abende, Rollenverteilung, Bench-Rotation und automatische Gruppenbildung.

## 🔎 Suchbegriffe

Dieses Projekt ist relevant für:

`World of Warcraft`, `WoW`, `Mythic+`, `M+`, `Discord Bot`, `Discord.py`, `Python Bot`, `WoW Guild Bot`, `Mythic Plus Bot`, `Dungeon Group Finder`, `M+ Shuffle`, `WoW Event Bot`, `Discord Event Manager`, `Guild Event Tool`

## 🎲 Was kann Shufflem?

- 🗓️ Erstellt M+ Shuffle-Events per Discord Slash Command
- ✅ Verwaltet Anmeldungen direkt über Discord Buttons und Dropdowns
- 🛡️ Unterstützt Rollenwahl für Tank, Heiler, DD und Flex-Spieler
- 👥 Bildet automatisch vollständige M+ Gruppen aus 1 Tank, 1 Heiler und 3 DDs
- 🪑 Priorisiert Spieler von der Bench in der nächsten Runde
- 🔁 Führt bis zu 4 Runden pro Event aus
- 🔀 Reshuffelt Gruppen automatisch nach Ablauf der Rundendauer
- 🧰 Erlaubt Admins manuelle Eingriffe während eines Events
- 🔊 Erstellt optional Voice-Channels pro Gruppe in einer Discord-Kategorie
- 📊 Postet am Ende eine Statistik mit gespielten Runden und Bench-Runden
- ♻️ Unterstützt wiederkehrende Events, zum Beispiel täglich oder wöchentlich

## 🌈 Wofür kann Shufflem verwendet werden?

Shufflem eignet sich für organisierte **World of Warcraft Mythic+ Abende**, bei denen viele Spieler teilnehmen und in mehreren Runden durchgemischt werden sollen. Der Bot hilft vor allem dann, wenn eine WoW-Gilde oder Discord-Community mehrere Mythic+ Gruppen gleichzeitig bauen und fair rotieren möchte.

Typische Einsatzzwecke:

- 🏰 Gildeninterne M+ Shuffle-Abende
- 🌐 Community-Events mit mehreren parallelen Gruppen
- ⚖️ Faire Rotation zwischen aktiven Gruppen und Bench
- ⚡ Spontane M+ Sessions mit automatischer Rollenverteilung
- 📆 Regelmäßige Events, die wiederholt im selben Discord-Channel stattfinden
- 🧑‍🤝‍🧑 WoW-Gilden, die einen einfachen Mythic+ Group Finder im Discord brauchen

## 🧭 Ablauf eines Events

1. Ein Admin erstellt ein Event mit `/shuffle create`.
2. Spieler melden sich über das Dropdown als Tank, Heiler, DD oder Flex-Spieler an.
3. Zum geplanten Start baut der Bot automatisch die erste Runde.
4. Nach jeder Rundendauer wird neu gemischt.
5. Bench-Spieler werden bei der nächsten Gruppenzuteilung bevorzugt.
6. Nach Runde 4 endet das Event.
7. Der Bot postet eine Abschlussmeldung und eine Statistik.

## ⚙️ Installation

### Voraussetzungen

- 🐍 Python 3.11 oder neuer
- 🔐 Ein Discord Bot Token
- 💬 Ein Discord Server, auf dem der Bot eingeladen ist

### Projekt installieren

```bash
pip install -r requirements.txt
```

### Umgebungsvariablen einrichten

Kopiere `.env.example` zu `.env` und trage deinen Discord Token ein:

```env
DISCORD_TOKEN=dein_token_hier
TIMEZONE=Europe/Berlin
```

Optional kann die Discord-Kategorie für automatisch erstellte Voice-Channels gesetzt werden:

```env
VOICE_CATEGORY_NAME=Lobby
```

Wenn die Variable nicht gesetzt ist, verwendet Shufflem standardmäßig die Kategorie `Lobby`.

### Bot starten

```bash
python bot.py
```

Beim Start synchronisiert der Bot seine Slash Commands und stellt aktive Event-Views wieder her.

## 🤖 Discord Bot einladen

Beim Erstellen der OAuth2-Einladungs-URL sollten diese Scopes gesetzt werden:

- `bot`
- `applications.commands`

Empfohlene Bot-Berechtigungen:

- Nachrichten senden
- Channels ansehen
- Nachrichtenverlauf lesen
- Embeds einbetten
- Channels verwalten, falls Voice-Channels automatisch erstellt und gelöscht werden sollen

## 🚀 Verwendung

### Event erstellen

```text
/shuffle create datum:15.04.2026 uhrzeit:20:00 rundendauer:45
```

Mit Wiederholung:

```text
/shuffle create datum:15.04.2026 uhrzeit:20:00 rundendauer:45 wiederholen:wöchentlich
```

Verfügbare Wiederholungen:

- `täglich`
- `wöchentlich`
- `2-wöchentlich`
- `monatlich`

### Wiederholung stoppen

```text
/shuffle stop
```

Das aktuelle Event läuft weiter, aber es wird danach kein neues wiederkehrendes Event erstellt.

### Spieler manuell hinzufügen

```text
/shuffle add spieler:@Name rollen:Tank + DD
```

### Spieler entfernen

```text
/shuffle remove spieler:@Name
```

## 🧰 Admin-Funktionen während eines Events

Admins mit der Discord-Berechtigung `Server verwalten` können während eines laufenden Events:

- 🔄 Spieler tauschen
- ⏭️ Sofort einen Reshuffle auslösen
- ❌ Spieler entfernen
- ➕ Spieler hinzufügen
- ⏸️ Den Timer pausieren und fortsetzen

Diese Aktionen sind direkt über die Buttons an der Gruppen-Nachricht verfügbar.

## 🧩 Gruppenlogik

Eine gültige Mythic+ Gruppe besteht aus:

| Rolle | Anzahl | Farbe im Discord-Kontext |
| --- | ---: | --- |
| 🛡️ Tank | 1 | Blau / Schutz |
| 💚 Heiler | 1 | Grün / Support |
| ⚔️ DD | 3 | Rot / Schaden |

Flex-Spieler können mehrere Rollen angeben. Shufflem weist sie nur einer Rolle pro Runde zu. Spieler, die in der letzten Runde auf der Bench waren, werden bei der nächsten Runde bevorzugt, damit die Rotation fairer bleibt.

## 💾 Datenhaltung

Shufflem speichert Events, Anmeldungen, Gruppenzuweisungen, Voice-Channel-Referenzen und Statistiken lokal in einer SQLite-Datenbank:

```text
shuffle.db
```

Die Datenbank wird beim Start automatisch erstellt, falls sie noch nicht existiert.

## 📁 Projektstruktur

```text
bot.py          Discord Bot, Slash Commands und Scheduler
views.py        Discord Embeds, Buttons, Dropdowns und Admin-Menüs
shuffle.py      Gruppenbildung und Shuffle-Logik
database.py     SQLite-Datenbankzugriff
ANLEITUNG.md    Ausführliche Einrichtungsanleitung
requirements.txt
```



## 🔐 Sicherheit

Lege deinen Discord Token nur in einer lokalen `.env` Datei oder als Hosting-Variable ab. Der Token darf nicht in GitHub committed oder öffentlich geteilt werden.

Auch `shuffle.db` sollte normalerweise nicht committed werden, da die Datei Discord-IDs, Eventdaten und Gruppenzuweisungen enthalten kann.

## 📖 Weitere Anleitung

Eine ausführlichere Schritt-für-Schritt-Anleitung findest du in [ANLEITUNG.md](ANLEITUNG.md).

import os
import re
import discord
from discord import app_commands
from discord.ext import tasks
from datetime import datetime, timezone, timedelta

import pytz
from dotenv import load_dotenv

import database as db
import views as v
from views import make_signup_view
from shuffle import build_groups, can_build_group
from database import get_bench_ids_from_last_round, get_groups_for_round

load_dotenv()

TOKEN    = os.getenv("DISCORD_TOKEN")
TZ_NAME  = os.getenv("TIMEZONE", "Europe/Berlin")

try:
    GUILD_TZ = pytz.timezone(TZ_NAME)
except pytz.UnknownTimeZoneError:
    print(f"Unbekannte Zeitzone '{TZ_NAME}', verwende UTC.")
    GUILD_TZ = pytz.utc

v.set_timezone(GUILD_TZ)

# ---------------------------------------------------------------------------
# Bot-Setup
# ---------------------------------------------------------------------------

intents = discord.Intents.default()
intents.message_content = False

bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)


# ---------------------------------------------------------------------------
# Background Scheduler
# ---------------------------------------------------------------------------

@tasks.loop(seconds=30)
async def scheduler():
    """
    Läuft alle 30 Sekunden und verwaltet den Lebenszyklus aller Events:
    - Startet Runde 1 wenn scheduled_at <= now
    - Reshuffelt nach jeder Runde
    - Beendet das Event nach Runde 3
    """
    now_utc = datetime.now(tz=timezone.utc)
    active_events = await db.get_active_events()

    for event in active_events:
        channel = bot.get_channel(int(event["channel_id"]))
        if not channel:
            continue

        try:
            message = await channel.fetch_message(int(event["message_id"]))
        except (discord.NotFound, discord.HTTPException, TypeError):
            continue

        # --- Signup-Phase: prüfen ob Startzeit erreicht ---
        if event["status"] == "signup":
            scheduled = datetime.fromisoformat(event["scheduled_at"]).replace(tzinfo=timezone.utc)
            if now_utc >= scheduled:
                await _start_round(event, message, round_number=1, now_utc=now_utc)

        # --- Laufende Runde: prüfen ob Rundenende erreicht ---
        elif event["status"] == "running" and event.get("round_end_at"):
            round_end = datetime.fromisoformat(event["round_end_at"]).replace(tzinfo=timezone.utc)
            if now_utc >= round_end:
                current = event["current_round"]
                if current < 3:
                    await _start_round(event, message, round_number=current + 1, now_utc=now_utc)
                else:
                    await _finish_event(event, message)


async def _start_round(event: dict, message: discord.Message, round_number: int, now_utc: datetime):
    event_id = event["id"]
    signups = await db.get_signups(event_id)

    if not can_build_group(signups):
        await db.finish_event(event_id)
        embed = discord.Embed(
            title="❌ M+ Shuffle – Abgebrochen",
            description=(
                "Nicht genug Spieler für einen Run.\n"
                "Benötigt: mindestens **1 Tank, 1 Heiler, 3 DDs**"
            ),
            color=discord.Color.red()
        )
        await message.edit(embed=embed, view=discord.ui.View())
        return

    # Bei Runde 2 und 3: Bench-Spieler der letzten Runde bevorzugen
    prev_bench_ids = set()
    if round_number > 1:
        prev_bench_ids = await get_bench_ids_from_last_round(event_id, round_number - 1)

    groups, bench = build_groups(signups, prev_bench_ids)
    round_end_at = now_utc + timedelta(minutes=event["round_duration_minutes"])

    await db.save_group_assignments(event_id, round_number, groups, bench)
    await db.update_event_round(event_id, round_number, round_end_at)

    # Frisch aus DB laden damit round_end_at befüllt ist
    updated_event = await db.get_event(event_id)
    embeds, mentions = v.build_groups_embeds(updated_event, groups, bench)

    # Admin-Buttons (Tauschen + Reshuffle) an die Gruppen-Nachricht hängen
    admin_view = _make_groups_admin_view(event_id, round_number, message)
    await message.edit(content=mentions, embeds=embeds, view=admin_view)


def _make_groups_admin_view(event_id: int, round_number: int,
                            message: discord.Message) -> discord.ui.View:
    """Admin-Buttons: Spieler tauschen + manueller Reshuffle."""

    async def on_swap(interaction: discord.Interaction):
        groups, bench = await get_groups_for_round(event_id, round_number)
        await v.send_swap_menu(interaction, event_id, round_number, groups, bench)

    async def on_reshuffle(interaction: discord.Interaction):
        event = await db.get_event(event_id)
        if not event:
            await interaction.response.send_message("Event nicht gefunden.", ephemeral=True)
            return
        current = event["current_round"]
        if current >= 3:
            await interaction.response.send_message(
                "Runde 3 ist die letzte Runde – kein weiterer Reshuffle möglich.", ephemeral=True
            )
            return
        await interaction.response.send_message(
            f"🔀 Starte Runde {current + 1} jetzt...", ephemeral=True
        )
        await _start_round(event, message, round_number=current + 1,
                           now_utc=datetime.now(tz=timezone.utc))

    return v.make_groups_admin_view(event_id, round_number, on_swap, on_reshuffle)


async def _finish_event(event: dict, message: discord.Message):
    event_id = event["id"]
    await db.finish_event(event_id)
    signups = await db.get_signups(event_id)
    updated_event = await db.get_event(event_id)

    # Abschluss-Embed ins bestehende Event-Post
    embed = v.build_finished_embed(updated_event, signups)
    await message.edit(content=None, embed=embed, view=discord.ui.View())

    # Statistik als separate Nachricht im Channel posten
    stats = await db.get_player_stats(event_id)
    if stats:
        stats_embed = v.build_stats_embed(stats)
        await message.channel.send(embed=stats_embed)

    # Wiederkehrendes Event: neues Event anlegen wenn repeat_days gesetzt
    repeat_days = event.get("repeat_days")
    if repeat_days:
        old_scheduled = datetime.fromisoformat(event["scheduled_at"]).replace(tzinfo=timezone.utc)
        next_scheduled = old_scheduled + timedelta(days=repeat_days)

        channel = message.channel
        new_event_id = await db.create_event(
            guild_id=event["guild_id"],
            channel_id=event["channel_id"],
            scheduled_at=next_scheduled,
            round_duration_minutes=event["round_duration_minutes"],
            repeat_days=repeat_days
        )
        new_event = await db.get_event(new_event_id)
        view = make_signup_view(new_event_id)
        embed = v.build_signup_embed(new_event, [])
        new_msg = await channel.send(embed=embed, view=view)
        await db.set_event_message(new_event_id, str(new_msg.id))
        bot.add_view(view)


# ---------------------------------------------------------------------------
# Slash Commands
# ---------------------------------------------------------------------------

REPEAT_OPTIONS = {
    "täglich":      1,
    "wöchentlich":  7,
    "2-wöchentlich": 14,
    "monatlich":    30,
}

@tree.command(name="shuffle", description="M+ Shuffle Event verwalten")
@app_commands.describe(
    aktion="create = neues Event | stop = Wiederholung stoppen",
    datum="Datum im Format TT.MM.JJJJ (z.B. 15.04.2024)",
    uhrzeit="Uhrzeit im Format HH:MM (z.B. 20:00)",
    rundendauer="Dauer jeder Runde in Minuten (z.B. 45)",
    wiederholen="Optional: Event automatisch wiederholen"
)
@app_commands.choices(
    aktion=[
        app_commands.Choice(name="create", value="create"),
        app_commands.Choice(name="stop",   value="stop"),
    ],
    wiederholen=[
        app_commands.Choice(name="täglich",       value="täglich"),
        app_commands.Choice(name="wöchentlich",   value="wöchentlich"),
        app_commands.Choice(name="2-wöchentlich", value="2-wöchentlich"),
        app_commands.Choice(name="monatlich",     value="monatlich"),
    ]
)
async def shuffle_cmd(
    interaction: discord.Interaction,
    aktion: str,
    datum: str = None,
    uhrzeit: str = None,
    rundendauer: int = None,
    wiederholen: str = None
):
    if aktion == "create":
        await _cmd_create(interaction, datum, uhrzeit, rundendauer, wiederholen)
    elif aktion == "stop":
        await _cmd_stop(interaction)


async def _cmd_create(interaction: discord.Interaction, datum: str, uhrzeit: str,
                      rundendauer: int, wiederholen: str = None):
    if not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message(
            "Nur Admins können Shuffle-Events erstellen.", ephemeral=True
        )
        return

    # Pflichtfelder prüfen
    if not datum or not uhrzeit or not rundendauer:
        await interaction.response.send_message(
            "Bitte alle Parameter angeben:\n"
            "`/shuffle create datum:15.04.2024 uhrzeit:20:00 rundendauer:45`",
            ephemeral=True
        )
        return

    # Format prüfen
    if not re.fullmatch(r"\d{2}\.\d{2}\.\d{4}", datum):
        await interaction.response.send_message(
            "Ungültiges Datumsformat. Bitte verwende **TT.MM.JJJJ** (z.B. `15.04.2024`)",
            ephemeral=True
        )
        return
    if not re.fullmatch(r"\d{2}:\d{2}", uhrzeit):
        await interaction.response.send_message(
            "Ungültiges Uhrzeitformat. Bitte verwende **HH:MM** (z.B. `20:00`)",
            ephemeral=True
        )
        return
    if rundendauer < 1:
        await interaction.response.send_message(
            "Rundendauer muss mindestens 1 Minute sein.", ephemeral=True
        )
        return

    # Datum parsen
    try:
        tag, monat, jahr = datum.split(".")
        stunde, minute = uhrzeit.split(":")
        local_dt = GUILD_TZ.localize(datetime(
            int(jahr), int(monat), int(tag), int(stunde), int(minute)
        ))
        utc_dt = local_dt.astimezone(pytz.utc)
    except (ValueError, pytz.exceptions.AmbiguousTimeError):
        await interaction.response.send_message(
            "Ungültiges Datum oder Uhrzeit.", ephemeral=True
        )
        return

    if utc_dt <= datetime.now(tz=timezone.utc):
        await interaction.response.send_message(
            "Der Zeitpunkt liegt in der Vergangenheit. Bitte ein zukünftiges Datum wählen.",
            ephemeral=True
        )
        return

    # Prüfen ob bereits aktives Event im Channel
    existing = await db.get_active_event_for_channel(str(interaction.channel_id))
    if existing:
        await interaction.response.send_message(
            "Es läuft bereits ein aktives Shuffle-Event in diesem Channel.", ephemeral=True
        )
        return

    # Wiederholung auflösen
    repeat_days = REPEAT_OPTIONS.get(wiederholen) if wiederholen else None

    # Event in DB anlegen
    event_id = await db.create_event(
        guild_id=str(interaction.guild_id),
        channel_id=str(interaction.channel_id),
        scheduled_at=utc_dt,
        round_duration_minutes=rundendauer,
        repeat_days=repeat_days
    )
    event = await db.get_event(event_id)
    signups = []

    embed = v.build_signup_embed(event, signups)
    view = make_signup_view(event_id)

    await interaction.response.send_message(embed=embed, view=view)
    msg = await interaction.original_response()
    await db.set_event_message(event_id, str(msg.id))


async def _cmd_stop(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message(
            "Nur Admins können die Wiederholung stoppen.", ephemeral=True
        )
        return

    existing = await db.get_active_event_for_channel(str(interaction.channel_id))
    if not existing or not existing.get("repeat_days"):
        await interaction.response.send_message(
            "Kein aktives wiederkehrendes Event in diesem Channel.", ephemeral=True
        )
        return

    await db.cancel_recurring_for_channel(str(interaction.channel_id))
    await interaction.response.send_message(
        "Wiederholung gestoppt. Das aktuelle Event läuft noch zu Ende, danach gibt es keine automatische Fortsetzung mehr.",
        ephemeral=True
    )


# ---------------------------------------------------------------------------
# Bot Events
# ---------------------------------------------------------------------------

@bot.event
async def on_ready():
    await db.init_db()
    await tree.sync()

    # Persistente Views für aktive Events neu registrieren
    active_events = await db.get_active_events()
    for event in active_events:
        event_id = event["id"]
        if event["status"] == "signup":
            view = make_signup_view(event_id)
            bot.add_view(view)
        elif event["status"] == "running":
            # Admin-Buttons für laufende Runden wiederherstellen
            try:
                channel = bot.get_channel(int(event["channel_id"]))
                if channel and event.get("message_id"):
                    message = await channel.fetch_message(int(event["message_id"]))
                    round_number = event["current_round"]
                    admin_view = _make_groups_admin_view(event_id, round_number, message)
                    bot.add_view(admin_view)
            except Exception:
                pass

    scheduler.start()
    print(f"Bot gestartet als {bot.user} | Zeitzone: {TZ_NAME}")
    print(f"Aktive Events beim Start: {len(active_events)}")


# ---------------------------------------------------------------------------
# Start
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if not TOKEN:
        print("Fehler: DISCORD_TOKEN nicht in .env gesetzt!")
    else:
        bot.run(TOKEN)

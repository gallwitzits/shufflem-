import os
import re
import unicodedata
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
VOICE_CATEGORY_NAME = os.getenv("VOICE_CATEGORY_NAME", "Lobby")

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
intents.voice_states = True  # nötig, um verbundene Spieler in Gruppen-Channels zu verschieben

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
    - Beendet das Event nach Runde 4
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

        # --- Laufende Runde: prüfen ob Rundenende erreicht (nur wenn nicht pausiert) ---
        elif event["status"] == "running" and event.get("round_end_at") and not event.get("is_paused"):
            round_end = datetime.fromisoformat(event["round_end_at"]).replace(tzinfo=timezone.utc)
            if now_utc >= round_end:
                current = event["current_round"]
                if current < 4:
                    await _start_round(event, message, round_number=current + 1, now_utc=now_utc)
                else:
                    await _start_cooldown(event, message, now_utc)

        # --- Cooldown nach letzter Runde ---
        elif event["status"] == "cooldown" and event.get("round_end_at") and not event.get("is_paused"):
            cooldown_end = datetime.fromisoformat(event["round_end_at"]).replace(tzinfo=timezone.utc)
            if now_utc >= cooldown_end:
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

    # Wer war in bisherigen Runden schon mit wem zusammen? -> Wiederholungen vermeiden
    pair_counts = await db.get_pair_counts(event_id, round_number)
    groups, bench = build_groups(signups, prev_bench_ids, pair_counts)
    round_end_at = now_utc + timedelta(minutes=event["round_duration_minutes"])

    await db.save_group_assignments(event_id, round_number, groups, bench)
    await db.update_event_round(event_id, round_number, round_end_at)

    # Frisch aus DB laden damit round_end_at befüllt ist
    updated_event = await db.get_event(event_id)
    embeds, mentions = v.build_groups_embeds(updated_event, groups, bench)
    await _ensure_voice_channels_for_round(
        updated_event, message.channel, groups, reset_existing=False
    )
    # Verbundene Spieler automatisch in ihren Gruppen-Voice-Channel ziehen
    await _move_players_to_voice(updated_event, getattr(message.channel, "guild", None), groups)

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
        if current >= 4:
            await interaction.response.send_message(
                "Runde 4 ist die letzte Runde – kein weiterer Reshuffle möglich.", ephemeral=True
            )
            return
        await interaction.response.send_message(
            f"🔀 Starte Runde {current + 1} jetzt...", ephemeral=True
        )
        await _start_round(event, message, round_number=current + 1,
                           now_utc=datetime.now(tz=timezone.utc))

    async def on_remove(interaction: discord.Interaction):
        groups, bench = await get_groups_for_round(event_id, round_number)
        await v.send_remove_menu(interaction, event_id, round_number, groups, bench)

    async def on_pause(interaction: discord.Interaction):
        event = await db.get_event(event_id)
        if not event:
            await interaction.response.send_message("Event nicht gefunden.", ephemeral=True)
            return
        now_utc = datetime.now(tz=timezone.utc)
        if event.get("is_paused"):
            await db.resume_event(event_id, now_utc)
            await interaction.response.send_message("▶️ Timer fortgesetzt.", ephemeral=True)
        else:
            await db.pause_event(event_id, now_utc)
            await interaction.response.send_message("⏸️ Timer pausiert.", ephemeral=True)

        # Embed sofort aktualisieren damit Pause-Anzeige sichtbar wird
        updated_event = await db.get_event(event_id)
        groups, bench = await get_groups_for_round(event_id, round_number)
        embeds, _ = v.build_groups_embeds(updated_event, groups, bench)
        await message.edit(embeds=embeds)

    async def on_add(interaction: discord.Interaction):
        await _send_add_player_menu(interaction, event_id, round_number, message)

    return v.make_groups_admin_view(
        event_id, round_number, on_swap, on_reshuffle, on_remove, on_add, on_pause
    )


async def _start_cooldown(event: dict, message: discord.Message, now_utc: datetime):
    """10-Minuten Puffer nach der letzten Runde bevor das Event endet."""
    event_id = event["id"]
    cooldown_end = now_utc + timedelta(minutes=10)
    await db.start_cooldown(event_id, cooldown_end)

    updated_event = await db.get_event(event_id)
    groups, bench = await get_groups_for_round(event_id, event["current_round"])
    embeds, _ = v.build_groups_embeds(updated_event, groups, bench)

    admin_view = _make_groups_admin_view(event_id, event["current_round"], message)
    await message.edit(embeds=embeds, view=admin_view)


async def _finish_event(event: dict, message: discord.Message):
    event_id = event["id"]
    await db.finish_event(event_id)
    await _delete_voice_channels(event_id)
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

ROLE_ORDER = ["tank", "healer", "dps"]
ROLE_CHOICES = [
    app_commands.Choice(name="Tank", value="tank"),
    app_commands.Choice(name="Heiler", value="healer"),
    app_commands.Choice(name="DD", value="dps"),
    app_commands.Choice(name="Tank + Heiler", value="tank,healer"),
    app_commands.Choice(name="Tank + DD", value="tank,dps"),
    app_commands.Choice(name="Heiler + DD", value="healer,dps"),
    app_commands.Choice(name="Tank + Heiler + DD", value="tank,healer,dps"),
]


def _role_select_options() -> list[discord.SelectOption]:
    return [
        discord.SelectOption(label="Tank", value="tank", emoji="🛡️",
                             description="Kann tanken"),
        discord.SelectOption(label="Heiler", value="healer", emoji="💚",
                             description="Kann heilen"),
        discord.SelectOption(label="DD", value="dps", emoji="⚔️",
                             description="Kann Schaden machen"),
    ]


def _normalize_roles(values: list[str]) -> str:
    return ",".join(sorted(values, key=ROLE_ORDER.index))


def _role_label(role_str: str) -> str:
    parts = [r.strip() for r in role_str.split(",")]
    return " + ".join(
        f"{v.ROLE_EMOJI.get(role, '')} {v.ROLE_LABEL.get(role, role)}".strip()
        for role in parts
    )


def _player_name(player) -> str:
    return getattr(player, "display_name", None) or getattr(player, "name", str(player.id))


def _mentions_for_groups(groups: list[dict]) -> str:
    mentions = []
    for group in groups:
        players = [group.get("tank"), group.get("healer")] + group.get("dps", [])
        mentions.extend(f"<@{p['user_id']}>" for p in players if p)
    return " ".join(mentions)


def _plain_channel_name(name: str) -> str:
    return unicodedata.normalize("NFKC", name).casefold().strip()


async def _find_voice_category(guild) -> discord.CategoryChannel | None:
    target = _plain_channel_name(VOICE_CATEGORY_NAME)

    for category in getattr(guild, "categories", []):
        if _plain_channel_name(category.name) == target:
            return category

    try:
        channels = await guild.fetch_channels()
    except (discord.Forbidden, discord.HTTPException) as e:
        print(f"Kategorien konnten nicht geladen werden: {e}")
        return None

    for channel in channels:
        if isinstance(channel, discord.CategoryChannel) and _plain_channel_name(channel.name) == target:
            return channel

    print(f"Voice-Kategorie '{VOICE_CATEGORY_NAME}' wurde nicht gefunden.")
    return None


async def _delete_voice_channels(event_id: int, round_number: int | None = None):
    records = await db.get_voice_channels(event_id, round_number)
    for record in records:
        try:
            channel_id = int(record["channel_id"])
        except (TypeError, ValueError):
            continue

        channel = bot.get_channel(channel_id)
        if channel is None:
            try:
                channel = await bot.fetch_channel(channel_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                continue

        try:
            await channel.delete(reason=f"WoW Shuffle Event {event_id}: Gruppen-Voice aufräumen")
        except (discord.NotFound, discord.Forbidden, discord.HTTPException) as e:
            print(f"Voice-Channel {channel_id} konnte nicht gelöscht werden: {e}")

    await db.clear_voice_channels(event_id, round_number)


async def _ensure_voice_channels_for_round(event: dict, channel,
                                           groups: list[dict] | None = None,
                                           reset_existing: bool = False) -> list[discord.VoiceChannel]:
    event_id = event["id"]
    round_number = event["current_round"]
    if not round_number:
        return []

    if reset_existing:
        await _delete_voice_channels(event_id)

    if groups is None:
        groups, _ = await get_groups_for_round(event_id, round_number)
    if not groups:
        return []

    guild = getattr(channel, "guild", None)
    if not guild:
        return []

    category = await _find_voice_category(guild)
    if category is None:
        return []

    # Alle Channels des Events laden (round-übergreifend) um Wiederverwendung zu ermöglichen
    all_existing = await db.get_voice_channels(event_id)
    existing_by_group = {record["group_number"]: record for record in all_existing}
    created_records = []
    created_channels = []

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(
            view_channel=True,
            connect=True
        )
    }

    for group_number in range(1, len(groups) + 1):
        if group_number in existing_by_group:
            continue

        try:
            voice_channel = await guild.create_voice_channel(
                name=f"Gruppe {group_number}",
                category=category,
                overwrites=overwrites,
                reason=f"WoW Shuffle Event {event_id} Runde {round_number} Gruppe {group_number}"
            )
        except (discord.Forbidden, discord.HTTPException) as e:
            print(f"Voice-Channel für Gruppe {group_number} konnte nicht erstellt werden: {e}")
            continue

        created_channels.append(voice_channel)
        created_records.append({
            "group_number": group_number,
            "channel_id": str(voice_channel.id),
        })

    if created_records:
        await db.save_voice_channels(event_id, round_number, created_records)

    return created_channels


async def _move_players_to_voice(event: dict, guild, groups: list[dict]) -> None:
    """
    Zieht alle bereits verbundenen Gruppenmitglieder in ihren jeweiligen
    Gruppen-Voice-Channel ("Gruppe X").

    Hinweis: Discord erlaubt das Verschieben nur für Mitglieder, die bereits in
    IRGENDEINEM Voice-Channel sitzen. Wer gar nicht im Voice ist, kann nicht
    gezogen werden und wird nur geloggt. Der Bot braucht die Berechtigung
    "Mitglieder verschieben".
    """
    if not guild or not groups:
        return

    records = await db.get_voice_channels(event["id"])
    channel_by_group: dict[int, int] = {}
    for record in records:
        try:
            channel_by_group[record["group_number"]] = int(record["channel_id"])
        except (TypeError, ValueError):
            continue

    not_connected: list[str] = []

    for group_number, group in enumerate(groups, start=1):
        channel_id = channel_by_group.get(group_number)
        if not channel_id:
            continue

        target = guild.get_channel(channel_id)
        if target is None:
            try:
                target = await bot.fetch_channel(channel_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                continue
        if not isinstance(target, discord.VoiceChannel):
            continue

        members = [group.get("tank"), group.get("healer")] + group.get("dps", [])
        for player in members:
            if not player:
                continue
            try:
                user_id = int(player["user_id"])
            except (TypeError, ValueError):
                continue

            member = guild.get_member(user_id)
            if member is None:
                try:
                    member = await guild.fetch_member(user_id)
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    member = None

            # Nur bereits verbundene Mitglieder können verschoben werden
            if member is None or member.voice is None or member.voice.channel is None:
                if member is not None:
                    not_connected.append(member.display_name)
                continue
            if member.voice.channel.id == target.id:
                continue

            try:
                await member.move_to(
                    target, reason=f"WoW Shuffle Event {event['id']}: Gruppe {group_number}"
                )
            except (discord.Forbidden, discord.HTTPException) as e:
                print(f"Konnte {member.display_name} nicht in Gruppe {group_number} verschieben: {e}")

    if not_connected:
        print("Nicht verschoben (nicht im Voice): " + ", ".join(not_connected))


async def _fetch_event_message(event: dict, fallback_channel=None) -> discord.Message | None:
    if not event or not event.get("message_id"):
        return None

    try:
        channel_id = int(event["channel_id"])
        message_id = int(event["message_id"])
    except (TypeError, ValueError):
        return None

    channel = bot.get_channel(channel_id)
    if channel is None and fallback_channel and getattr(fallback_channel, "id", None) == channel_id:
        channel = fallback_channel
    if channel is None:
        try:
            channel = await bot.fetch_channel(channel_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return None

    try:
        return await channel.fetch_message(message_id)
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        return None


async def _build_extra_groups_from_bench(event_id: int, round_number: int) -> tuple[int, list[dict]]:
    groups, bench = await get_groups_for_round(event_id, round_number)
    if not bench:
        return 0, []

    bench_pool = [dict(player) for player in bench]
    prev_bench_ids = {player["user_id"] for player in bench_pool}
    pair_counts = await db.get_pair_counts(event_id, round_number)
    new_groups, new_bench = build_groups(bench_pool, prev_bench_ids, pair_counts)
    if not new_groups:
        return 0, []

    await db.replace_group_assignments(event_id, round_number, groups + new_groups, new_bench)
    return len(new_groups), new_groups


async def _refresh_running_message(event: dict, message: discord.Message | None = None) -> bool:
    event_id = event["id"]
    round_number = event["current_round"]
    message = message or await _fetch_event_message(event)
    if not message:
        return False

    groups, bench = await get_groups_for_round(event_id, round_number)
    updated_event = await db.get_event(event_id)
    await _ensure_voice_channels_for_round(updated_event, message, groups)
    embeds, _ = v.build_groups_embeds(updated_event, groups, bench)
    admin_view = _make_groups_admin_view(event_id, round_number, message)
    await message.edit(embeds=embeds, view=admin_view)
    return True


async def _add_player_to_event(interaction: discord.Interaction, player,
                               role_str: str, source_message: discord.Message | None = None):
    if not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message(
            "Nur Admins können Spieler hinzufügen.", ephemeral=True
        )
        return

    if not player or not role_str:
        await interaction.response.send_message(
            "Bitte Spieler und Rolle(n) auswählen.", ephemeral=True
        )
        return

    if getattr(player, "bot", False):
        await interaction.response.send_message(
            "Bots können nicht zum Shuffle hinzugefügt werden.", ephemeral=True
        )
        return

    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=True)

    event = await db.get_active_event_for_channel(str(interaction.channel_id))
    if not event:
        await interaction.edit_original_response(
            content="In diesem Channel gibt es kein aktives Shuffle-Event.", view=None
        )
        return

    event_id = event["id"]
    user_id = str(player.id)
    username = _player_name(player)
    role_label = _role_label(role_str)
    message = source_message or await _fetch_event_message(event, interaction.channel)

    if event["status"] == "signup":
        await db.add_signup(event_id, user_id, username, role_str)
        updated_event = await db.get_event(event_id)
        signups = await db.get_signups(event_id)
        refreshed = False
        if message:
            await message.edit(embed=v.build_signup_embed(updated_event, signups))
            refreshed = True

        suffix = "" if refreshed else "\nHinweis: Die Discord-Nachricht konnte nicht aktualisiert werden."
        await interaction.edit_original_response(
            content=f"{player.mention} ist als **{role_label}** angemeldet.{suffix}",
            view=None
        )
        return

    if event["status"] != "running":
        await interaction.edit_original_response(
            content="Das Event ist nicht mehr in der Anmelde- oder Laufphase.", view=None
        )
        return

    round_number = event["current_round"]
    assignment = await db.get_assignment_for_round(event_id, round_number, user_id)
    if assignment:
        place = "Bench" if assignment["group_number"] == 0 else f"Gruppe {assignment['group_number']}"
        await interaction.edit_original_response(
            content=f"{player.mention} ist in Runde {round_number} bereits in **{place}**.",
            view=None
        )
        return

    await db.add_signup(event_id, user_id, username, role_str)
    await db.add_player_to_round_bench(event_id, round_number, user_id, role_str)

    new_group_count, new_groups = await _build_extra_groups_from_bench(event_id, round_number)
    updated_event = await db.get_event(event_id)
    refreshed = await _refresh_running_message(updated_event, message)

    if new_group_count:
        channel = message.channel if message else interaction.channel
        if channel:
            group_word = "Gruppe" if new_group_count == 1 else "Gruppen"
            await channel.send(
                f"**Neue {group_word} aus der Bench:** {_mentions_for_groups(new_groups)}"
            )
        text = (
            f"{player.mention} wurde als **{role_label}** hinzugefügt. "
            f"Aus der Bench wurde **{new_group_count}** neue Gruppe gebaut."
        )
    else:
        text = (
            f"{player.mention} wurde als **{role_label}** zur Bench hinzugefügt. "
            "Für eine weitere Gruppe fehlen noch passende Bench-Spieler."
        )

    if not refreshed:
        text += "\nHinweis: Die Gruppen-Nachricht konnte nicht aktualisiert werden."

    await interaction.edit_original_response(content=text, view=None)


async def _remove_player_from_event(interaction: discord.Interaction, player,
                                    source_message: discord.Message | None = None):
    if not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message(
            "Nur Admins können Spieler entfernen.", ephemeral=True
        )
        return

    if not player:
        await interaction.response.send_message(
            "Bitte den Spieler angeben, der entfernt werden soll.", ephemeral=True
        )
        return

    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=True)

    event = await db.get_active_event_for_channel(str(interaction.channel_id))
    if not event:
        await interaction.edit_original_response(
            content="In diesem Channel gibt es kein aktives Shuffle-Event.", view=None
        )
        return

    event_id = event["id"]
    user_id = str(player.id)
    message = source_message or await _fetch_event_message(event, interaction.channel)
    signups = await db.get_signups(event_id)
    was_signed_up = any(s["user_id"] == user_id for s in signups)

    if event["status"] == "signup":
        if not was_signed_up:
            await interaction.edit_original_response(
                content=f"{player.mention} war für dieses Event nicht angemeldet.",
                view=None
            )
            return

        await db.remove_signup(event_id, user_id)
        updated_event = await db.get_event(event_id)
        updated_signups = await db.get_signups(event_id)
        refreshed = False
        if message:
            await message.edit(embed=v.build_signup_embed(updated_event, updated_signups))
            refreshed = True

        suffix = "" if refreshed else "\nHinweis: Die Discord-Nachricht konnte nicht aktualisiert werden."
        await interaction.edit_original_response(
            content=f"{player.mention} wurde aus der Anmeldung entfernt.{suffix}",
            view=None
        )
        return

    if event["status"] != "running":
        await interaction.edit_original_response(
            content="Das Event ist nicht mehr in der Anmelde- oder Laufphase.", view=None
        )
        return

    assignment = await db.get_assignment_for_round(event_id, event["current_round"], user_id)
    if not was_signed_up and not assignment:
        await interaction.edit_original_response(
            content=f"{player.mention} ist in diesem Event nicht eingetragen.", view=None
        )
        return

    await db.remove_player_from_event(event_id, user_id)
    refreshed = await _refresh_running_message(await db.get_event(event_id), message)
    suffix = "" if refreshed else "\nHinweis: Die Gruppen-Nachricht konnte nicht aktualisiert werden."
    await interaction.edit_original_response(
        content=f"{player.mention} wurde aus dem Event entfernt.{suffix}",
        view=None
    )


async def _send_add_player_menu(interaction: discord.Interaction, event_id: int,
                                round_number: int, message: discord.Message):
    class AddPlayerView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=120)
            self.player = None
            self.roles: list[str] = []

        @discord.ui.select(cls=discord.ui.UserSelect, placeholder="Spieler auswählen",
                           min_values=1, max_values=1, custom_id="add_player_user")
        async def select_player(self_, interaction: discord.Interaction,
                                select: discord.ui.UserSelect):
            self_.player = select.values[0]
            await interaction.response.defer()

        @discord.ui.select(placeholder="Rolle(n) auswählen", min_values=1, max_values=3,
                           options=_role_select_options(), custom_id="add_player_roles")
        async def select_roles(self_, interaction: discord.Interaction, select: discord.ui.Select):
            self_.roles = interaction.data["values"]
            await interaction.response.defer()

        @discord.ui.button(label="✅ Hinzufügen", style=discord.ButtonStyle.success,
                           custom_id="add_player_confirm", row=2)
        async def confirm(self_, interaction: discord.Interaction, button: discord.ui.Button):
            if not self_.player or not self_.roles:
                await interaction.response.edit_message(
                    content="⚠️ Bitte Spieler und Rolle(n) auswählen.", view=self_
                )
                return

            role_str = _normalize_roles(self_.roles)
            await _add_player_to_event(interaction, self_.player, role_str, message)

    await interaction.response.send_message(
        "Wähle den Spieler und seine mögliche(n) Rolle(n):",
        view=AddPlayerView(),
        ephemeral=True
    )


@tree.command(name="shuffle", description="M+ Shuffle Event verwalten")
@app_commands.describe(
    aktion="create = neues Event | stop = Wiederholung stoppen | add/remove = Spieler verwalten",
    datum="Datum im Format TT.MM.JJJJ (z.B. 15.04.2024)",
    uhrzeit="Uhrzeit im Format HH:MM (z.B. 20:00)",
    rundendauer="Dauer jeder Runde in Minuten (z.B. 45)",
    wiederholen="Optional: Event automatisch wiederholen",
    spieler="Spieler der hinzugefügt oder entfernt werden soll",
    rollen="Rolle(n) des Spielers beim Hinzufügen"
)
@app_commands.choices(
    aktion=[
        app_commands.Choice(name="create", value="create"),
        app_commands.Choice(name="stop",   value="stop"),
        app_commands.Choice(name="add",    value="add"),
        app_commands.Choice(name="remove", value="remove"),
    ],
    wiederholen=[
        app_commands.Choice(name="täglich",       value="täglich"),
        app_commands.Choice(name="wöchentlich",   value="wöchentlich"),
        app_commands.Choice(name="2-wöchentlich", value="2-wöchentlich"),
        app_commands.Choice(name="monatlich",     value="monatlich"),
    ],
    rollen=ROLE_CHOICES
)
async def shuffle_cmd(
    interaction: discord.Interaction,
    aktion: str,
    datum: str = None,
    uhrzeit: str = None,
    rundendauer: int = None,
    wiederholen: str = None,
    spieler: discord.Member = None,
    rollen: str = None
):
    if aktion == "create":
        await _cmd_create(interaction, datum, uhrzeit, rundendauer, wiederholen)
    elif aktion == "stop":
        await _cmd_stop(interaction)
    elif aktion == "add":
        await _add_player_to_event(interaction, spieler, rollen)
    elif aktion == "remove":
        await _remove_player_from_event(interaction, spieler)


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
            # Admin-Buttons für laufende Runden wiederherstellen + zur Nachricht hinzufügen
            try:
                channel = bot.get_channel(int(event["channel_id"]))
                if channel and event.get("message_id"):
                    message = await channel.fetch_message(int(event["message_id"]))
                    round_number = event["current_round"]
                    admin_view = _make_groups_admin_view(event_id, round_number, message)
                    bot.add_view(admin_view)
                    await _ensure_voice_channels_for_round(event, message)
                    await message.edit(view=admin_view)
            except Exception as e:
                print(f"Fehler beim Wiederherstellen der Admin-Buttons für Event {event_id}: {e}")

    if not scheduler.is_running():
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

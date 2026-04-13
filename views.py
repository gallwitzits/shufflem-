import discord
from datetime import datetime, timezone
import pytz

from database import (
    add_signup, remove_signup, get_signups, get_event, finish_event
)

ROLE_EMOJI = {"tank": "🛡️", "healer": "💚", "dps": "⚔️"}
ROLE_LABEL = {"tank": "Tank", "healer": "Heiler", "dps": "DD"}

# Wird in bot.py gesetzt
_tz = None

def set_timezone(tz: pytz.BaseTzInfo):
    global _tz
    _tz = tz


def _now_local() -> datetime:
    return datetime.now(tz=_tz) if _tz else datetime.now(tz=timezone.utc)


def _fmt_local(dt_str: str) -> str:
    """ISO-Zeitstring (UTC) → lokale Uhrzeit als lesbarer String."""
    if not dt_str:
        return "?"
    dt = datetime.fromisoformat(dt_str).replace(tzinfo=timezone.utc)
    if _tz:
        dt = dt.astimezone(_tz)
    return dt.strftime("%d.%m.%Y %H:%M Uhr")


def _discord_timestamp(dt_str: str) -> str:
    """Gibt einen Discord-Timestamp zurück der sich im Client live aktualisiert.
    Format <t:unix:R> zeigt z.B. 'in 28 Minuten' und aktualisiert sich automatisch.
    Format <t:unix:F> zeigt das vollständige Datum + Uhrzeit.
    """
    dt = datetime.fromisoformat(dt_str).replace(tzinfo=timezone.utc)
    unix = int(dt.timestamp())
    return f"<t:{unix}:F> (<t:{unix}:R>)"


# ---------------------------------------------------------------------------
# Embed-Builder
# ---------------------------------------------------------------------------

def build_signup_embed(event: dict, signups: list[dict]) -> discord.Embed:
    tanks   = [s for s in signups if s["role"] == "tank"]
    healers = [s for s in signups if s["role"] == "healer"]
    dps     = [s for s in signups if s["role"] == "dps"]

    num_groups = min(len(tanks), len(healers), len(dps) // 3)

    embed = discord.Embed(
        title="🎲 M+ Shuffle – Anmeldung offen",
        color=discord.Color.gold()
    )
    embed.add_field(
        name="📅 Geplanter Start",
        value=_discord_timestamp(event["scheduled_at"]),
        inline=False
    )
    embed.add_field(
        name="⏱️ Rundendauer",
        value=f"{event['round_duration_minutes']} Min",
        inline=True
    )

    embed.add_field(
        name=f"🛡️ Tanks ({len(tanks)})",
        value=", ".join(s["username"] for s in tanks) or "–",
        inline=False
    )
    embed.add_field(
        name=f"💚 Heiler ({len(healers)})",
        value=", ".join(s["username"] for s in healers) or "–",
        inline=False
    )
    embed.add_field(
        name=f"⚔️ DDs ({len(dps)})",
        value=", ".join(s["username"] for s in dps) or "–",
        inline=False
    )

    bench_tanks   = max(0, len(tanks)   - num_groups)
    bench_healers = max(0, len(healers) - num_groups)
    bench_dps     = max(0, len(dps)     - num_groups * 3)
    bench_parts = []
    if bench_tanks:   bench_parts.append(f"{bench_tanks} Tank(s)")
    if bench_healers: bench_parts.append(f"{bench_healers} Heiler")
    if bench_dps:     bench_parts.append(f"{bench_dps} DDs")

    embed.set_footer(text=(
        f"✅ Mögliche Gruppen: {num_groups}  |  "
        f"🪑 Bench: {', '.join(bench_parts) if bench_parts else '–'}"
    ))
    return embed


GROUP_COLORS = [
    discord.Color.blue(),
    discord.Color.purple(),
    discord.Color.orange(),
    discord.Color.teal(),
    discord.Color.red(),
]


def build_groups_embeds(event: dict, groups: list[dict],
                        bench: list[dict]) -> tuple[list[discord.Embed], str]:
    """
    Gibt (embeds, mentions_content) zurück.
    - embeds: ein Header-Embed + ein Embed pro Gruppe
    - mentions_content: alle Spieler als @-Mention damit sie eine Benachrichtigung kriegen
    """
    round_num = event["current_round"]

    # --- Header-Embed ---
    header = discord.Embed(
        title=f"🎲 M+ Shuffle – Runde {round_num} / 3",
        color=discord.Color.gold()
    )
    if event.get("round_end_at"):
        header.description = f"⏰ Nächster Shuffle: {_discord_timestamp(event['round_end_at'])}"

    if bench:
        bench_str = "  ".join(
            f"{ROLE_EMOJI[p['role']]} {p['username']}" for p in bench
        )
        header.add_field(name="🪑 Bench – spielt nächste Runde", value=bench_str, inline=False)
    else:
        header.add_field(name="🪑 Bench", value="–", inline=False)

    # --- Ein Embed pro Gruppe ---
    group_embeds = []
    all_mentions = []

    for i, group in enumerate(groups, start=1):
        color = GROUP_COLORS[(i - 1) % len(GROUP_COLORS)]
        embed = discord.Embed(
            title=f"📦 Gruppe {i}",
            color=color
        )

        tank = group["tank"]
        healer = group["healer"]

        embed.add_field(
            name="🛡️ Tank",
            value=f"<@{tank['user_id']}>\n{tank['username']}",
            inline=True
        )
        embed.add_field(
            name="💚 Heiler",
            value=f"<@{healer['user_id']}>\n{healer['username']}",
            inline=True
        )
        embed.add_field(name="\u200b", value="\u200b", inline=True)  # Leerzeile

        dps_value = "\n".join(
            f"<@{p['user_id']}> {p['username']}" for p in group["dps"]
        )
        embed.add_field(name="⚔️ DDs", value=dps_value, inline=False)

        group_embeds.append(embed)

        # Mentions sammeln
        all_mentions.append(f"<@{tank['user_id']}>")
        all_mentions.append(f"<@{healer['user_id']}>")
        for p in group["dps"]:
            all_mentions.append(f"<@{p['user_id']}>")

    mentions_content = "**Runde " + str(round_num) + " startet!** " + " ".join(all_mentions)

    return [header] + group_embeds, mentions_content


def build_finished_embed(event: dict, signups: list[dict]) -> discord.Embed:
    embed = discord.Embed(
        title="🏁 M+ Shuffle – Beendet",
        description=(
            f"**3 Runden** gespielt  |  **{len(signups)} Teilnehmer**\n"
            "Danke fürs Mitspielen! 🎉"
        ),
        color=discord.Color.green()
    )
    return embed


def build_stats_embed(stats: list[dict]) -> discord.Embed:
    """
    Statistik-Embed das nach dem Event gepostet wird.
    Zeigt pro Spieler: Rolle, gespielte Runden, Bench-Runden.
    """
    embed = discord.Embed(
        title="📊 Shuffle Statistik",
        color=discord.Color.blurple()
    )

    # Nach Rolle gruppieren
    tanks   = [p for p in stats if p["role"] == "tank"]
    healers = [p for p in stats if p["role"] == "healer"]
    dps     = [p for p in stats if p["role"] == "dps"]

    def fmt_player(p: dict) -> str:
        played = p["rounds_played"]
        bench  = p["rounds_bench"]
        bar = "🟩" * played + "⬜" * bench
        bench_note = f" *(1x Bench)*" if bench == 1 else (f" *(2x Bench)*" if bench >= 2 else "")
        return f"{bar} **{p['username']}**{bench_note}"

    if tanks:
        embed.add_field(
            name="🛡️ Tanks",
            value="\n".join(fmt_player(p) for p in tanks),
            inline=False
        )
    if healers:
        embed.add_field(
            name="💚 Heiler",
            value="\n".join(fmt_player(p) for p in healers),
            inline=False
        )
    if dps:
        embed.add_field(
            name="⚔️ DDs",
            value="\n".join(fmt_player(p) for p in dps),
            inline=False
        )

    embed.set_footer(text="🟩 = mitgespielt  ⬜ = Bench")
    return embed


def build_cancelled_embed() -> discord.Embed:
    return discord.Embed(
        title="❌ M+ Shuffle – Abgebrochen",
        description="Das Event wurde vom Admin abgebrochen.",
        color=discord.Color.red()
    )


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------

class SignupView(discord.ui.View):
    def __init__(self, event_id: int):
        super().__init__(timeout=None)
        self.event_id = event_id
        # Buttons bekommen stabile custom_ids mit event_id
        self._set_custom_ids()

    def _set_custom_ids(self):
        for child in self.children:
            if hasattr(child, "custom_id") and child.custom_id.startswith("PLACEHOLDER_"):
                suffix = child.custom_id.replace("PLACEHOLDER_", "")
                child.custom_id = f"{suffix}_{self.event_id}"

    @discord.ui.button(label="🛡️ Tank", style=discord.ButtonStyle.primary,
                       custom_id="PLACEHOLDER_signup_tank")
    async def btn_tank(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_signup(interaction, "tank")

    @discord.ui.button(label="💚 Heiler", style=discord.ButtonStyle.success,
                       custom_id="PLACEHOLDER_signup_healer")
    async def btn_healer(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_signup(interaction, "healer")

    @discord.ui.button(label="⚔️ DD", style=discord.ButtonStyle.secondary,
                       custom_id="PLACEHOLDER_signup_dps")
    async def btn_dps(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._handle_signup(interaction, "dps")

    @discord.ui.button(label="❌ Abmelden", style=discord.ButtonStyle.danger,
                       custom_id="PLACEHOLDER_signup_remove")
    async def btn_remove(self, interaction: discord.Interaction, button: discord.ui.Button):
        await remove_signup(self.event_id, str(interaction.user.id))
        await self._refresh_embed(interaction)
        await interaction.response.send_message("Du wurdest abgemeldet.", ephemeral=True)

    @discord.ui.button(label="🏁 Abbrechen", style=discord.ButtonStyle.danger,
                       custom_id="PLACEHOLDER_signup_cancel", row=1)
    async def btn_cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message(
                "Nur Admins können das Event abbrechen.", ephemeral=True
            )
            return
        await finish_event(self.event_id)
        embed = build_cancelled_embed()
        self.disable_all()
        await interaction.message.edit(embed=embed, view=self)
        await interaction.response.send_message("Event abgebrochen.", ephemeral=True)

    async def _handle_signup(self, interaction: discord.Interaction, role: str):
        await add_signup(
            self.event_id,
            str(interaction.user.id),
            interaction.user.display_name,
            role
        )
        await self._refresh_embed(interaction)
        await interaction.response.send_message(
            f"Du bist als **{ROLE_LABEL[role]}** angemeldet.", ephemeral=True
        )

    async def _refresh_embed(self, interaction: discord.Interaction):
        event = await get_event(self.event_id)
        if not event:
            return
        signups = await get_signups(self.event_id)
        embed = build_signup_embed(event, signups)
        await interaction.message.edit(embed=embed)

    def disable_all(self):
        for child in self.children:
            child.disabled = True


class PersistentSignupView(discord.ui.View):
    """
    Persistente View für Bot-Neustart.
    Liest event_id aus den custom_ids der Buttons.
    """
    def __init__(self):
        super().__init__(timeout=None)

    @staticmethod
    def _event_id_from(interaction: discord.Interaction) -> int:
        for component in interaction.message.components:
            for child in component.children:
                if child.custom_id and child.custom_id.startswith("signup_tank_"):
                    return int(child.custom_id.split("_")[-1])
        raise ValueError("event_id nicht gefunden")

    @discord.ui.button(label="🛡️ Tank", style=discord.ButtonStyle.primary,
                       custom_id="signup_tank_persistent")
    async def btn_tank(self, interaction: discord.Interaction, button: discord.ui.Button):
        event_id = self._event_id_from(interaction)
        await add_signup(event_id, str(interaction.user.id), interaction.user.display_name, "tank")
        await _refresh_signup_message(interaction, event_id)
        await interaction.response.send_message("Du bist als **Tank** angemeldet.", ephemeral=True)

    @discord.ui.button(label="💚 Heiler", style=discord.ButtonStyle.success,
                       custom_id="signup_healer_persistent")
    async def btn_heiler(self, interaction: discord.Interaction, button: discord.ui.Button):
        event_id = self._event_id_from(interaction)
        await add_signup(event_id, str(interaction.user.id), interaction.user.display_name, "healer")
        await _refresh_signup_message(interaction, event_id)
        await interaction.response.send_message("Du bist als **Heiler** angemeldet.", ephemeral=True)

    @discord.ui.button(label="⚔️ DD", style=discord.ButtonStyle.secondary,
                       custom_id="signup_dps_persistent")
    async def btn_dps(self, interaction: discord.Interaction, button: discord.ui.Button):
        event_id = self._event_id_from(interaction)
        await add_signup(event_id, str(interaction.user.id), interaction.user.display_name, "dps")
        await _refresh_signup_message(interaction, event_id)
        await interaction.response.send_message("Du bist als **DD** angemeldet.", ephemeral=True)

    @discord.ui.button(label="❌ Abmelden", style=discord.ButtonStyle.danger,
                       custom_id="signup_remove_persistent")
    async def btn_remove(self, interaction: discord.Interaction, button: discord.ui.Button):
        event_id = self._event_id_from(interaction)
        await remove_signup(event_id, str(interaction.user.id))
        await _refresh_signup_message(interaction, event_id)
        await interaction.response.send_message("Du wurdest abgemeldet.", ephemeral=True)

    @discord.ui.button(label="🏁 Abbrechen", style=discord.ButtonStyle.danger,
                       custom_id="signup_cancel_persistent", row=1)
    async def btn_cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("Nur Admins können das Event abbrechen.", ephemeral=True)
            return
        event_id = self._event_id_from(interaction)
        await finish_event(event_id)
        embed = build_cancelled_embed()
        view = discord.ui.View()
        await interaction.message.edit(embed=embed, view=view)
        await interaction.response.send_message("Event abgebrochen.", ephemeral=True)


async def _refresh_signup_message(interaction: discord.Interaction, event_id: int):
    event = await get_event(event_id)
    if not event:
        return
    signups = await get_signups(event_id)
    embed = build_signup_embed(event, signups)
    await interaction.message.edit(embed=embed)

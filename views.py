import discord
from datetime import datetime, timezone
import pytz

from database import (
    add_signup, remove_signup, get_signups, get_event, finish_event
)

ROLE_EMOJI = {"tank": "🛡️", "healer": "💚", "dps": "⚔️"}
ROLE_LABEL = {"tank": "Tank", "healer": "Heiler", "dps": "DD"}

_tz = None

def set_timezone(tz: pytz.BaseTzInfo):
    global _tz
    _tz = tz


def _discord_timestamp(dt_str: str) -> str:
    dt = datetime.fromisoformat(dt_str).replace(tzinfo=timezone.utc)
    unix = int(dt.timestamp())
    return f"<t:{unix}:F> (<t:{unix}:R>)"


def _role_display(role_str: str) -> str:
    """Komma-getrennte Rollen → lesbares Label, z.B. 'tank,dps' → '🛡️+⚔️'"""
    parts = [r.strip() for r in role_str.split(",")]
    return "+".join(ROLE_EMOJI.get(r, r) for r in parts)


# ---------------------------------------------------------------------------
# Embed-Builder
# ---------------------------------------------------------------------------

def build_signup_embed(event: dict, signups: list[dict]) -> discord.Embed:
    from shuffle import count_possible_groups

    def roles_of(s):
        return [r.strip() for r in s["role"].split(",")]

    pure_tanks   = [s for s in signups if roles_of(s) == ["tank"]]
    pure_healers = [s for s in signups if roles_of(s) == ["healer"]]
    pure_dps     = [s for s in signups if roles_of(s) == ["dps"]]
    flex         = [s for s in signups if len(roles_of(s)) > 1]

    num_groups = count_possible_groups(signups) if signups else 0

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
    embed.add_field(name="\u200b", value="\u200b", inline=True)

    embed.add_field(
        name=f"🛡️ Tanks ({len(pure_tanks)})",
        value=", ".join(s["username"] for s in pure_tanks) or "–",
        inline=False
    )
    embed.add_field(
        name=f"💚 Heiler ({len(pure_healers)})",
        value=", ".join(s["username"] for s in pure_healers) or "–",
        inline=False
    )
    embed.add_field(
        name=f"⚔️ DDs ({len(pure_dps)})",
        value=", ".join(s["username"] for s in pure_dps) or "–",
        inline=False
    )
    if flex:
        embed.add_field(
            name=f"🔄 Flexibel ({len(flex)})",
            value="\n".join(f"{s['username']} ({_role_display(s['role'])})" for s in flex),
            inline=False
        )

    embed.set_footer(text=f"✅ Mögliche Gruppen: {num_groups}  |  Anmelden: Dropdown unten nutzen")
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
    round_num = event["current_round"]

    header = discord.Embed(
        title=f"🎲 M+ Shuffle – Runde {round_num} / 3",
        color=discord.Color.gold()
    )
    if event.get("round_end_at"):
        header.description = f"⏰ Nächster Shuffle: {_discord_timestamp(event['round_end_at'])}"

    if bench:
        bench_str = "  ".join(
            f"{ROLE_EMOJI.get(p.get('assigned_role', p['role']), '❓')} {p['username']}"
            for p in bench
        )
        header.add_field(name="🪑 Bench – spielt nächste Runde", value=bench_str, inline=False)
    else:
        header.add_field(name="🪑 Bench", value="–", inline=False)

    group_embeds = []
    all_mentions = []

    for i, group in enumerate(groups, start=1):
        color = GROUP_COLORS[(i - 1) % len(GROUP_COLORS)]
        embed = discord.Embed(title=f"📦 Gruppe {i}", color=color)

        tank   = group["tank"]
        healer = group["healer"]

        # Flex-Hinweis wenn Spieler eigentlich eine andere Haupt-Rolle hat
        def flex_note(player, assigned):
            roles = [r.strip() for r in player["role"].split(",")]
            if roles != [assigned]:
                return f" *({_role_display(player['role'])})*"
            return ""

        embed.add_field(
            name="🛡️ Tank",
            value=f"<@{tank['user_id']}>\n{tank['username']}{flex_note(tank, 'tank')}",
            inline=True
        )
        embed.add_field(
            name="💚 Heiler",
            value=f"<@{healer['user_id']}>\n{healer['username']}{flex_note(healer, 'healer')}",
            inline=True
        )
        embed.add_field(name="\u200b", value="\u200b", inline=True)

        dps_value = "\n".join(
            f"<@{p['user_id']}> {p['username']}{flex_note(p, 'dps')}"
            for p in group["dps"]
        )
        embed.add_field(name="⚔️ DDs", value=dps_value, inline=False)

        group_embeds.append(embed)

        all_mentions += [f"<@{tank['user_id']}>", f"<@{healer['user_id']}>"]
        all_mentions += [f"<@{p['user_id']}>" for p in group["dps"]]

    mentions_content = f"**Runde {round_num} startet!** " + " ".join(all_mentions)
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
    embed = discord.Embed(title="📊 Shuffle Statistik", color=discord.Color.blurple())

    tanks   = [p for p in stats if p["role"] == "tank"]
    healers = [p for p in stats if p["role"] == "healer"]
    dps     = [p for p in stats if p["role"] == "dps"]
    # Flex-Spieler erscheinen unter ihrer angemeldeten Rolle (Signup-Rolle)
    flex    = [p for p in stats if "," in p["role"]]
    # Aus den reinen Listen entfernen falls dort doppelt
    pure_tank_ids    = {p["username"] for p in tanks if "," not in p["role"]}
    pure_healer_ids  = {p["username"] for p in healers if "," not in p["role"]}
    pure_dps_ids     = {p["username"] for p in dps if "," not in p["role"]}

    def fmt(p: dict) -> str:
        bar = "🟩" * p["rounds_played"] + "⬜" * p["rounds_bench"]
        note = ""
        if p["rounds_bench"] == 1:
            note = " *(1× Bench)*"
        elif p["rounds_bench"] >= 2:
            note = f" *({p['rounds_bench']}× Bench)*"
        return f"{bar} **{p['username']}**{note}"

    pure_tanks   = [p for p in stats if p["role"] == "tank"   and "," not in p["role"]]
    pure_healers = [p for p in stats if p["role"] == "healer" and "," not in p["role"]]
    pure_dps     = [p for p in stats if p["role"] == "dps"    and "," not in p["role"]]
    flex_players = [p for p in stats if "," in p["role"]]

    if pure_tanks:
        embed.add_field(name="🛡️ Tanks", value="\n".join(fmt(p) for p in pure_tanks), inline=False)
    if pure_healers:
        embed.add_field(name="💚 Heiler", value="\n".join(fmt(p) for p in pure_healers), inline=False)
    if pure_dps:
        embed.add_field(name="⚔️ DDs", value="\n".join(fmt(p) for p in pure_dps), inline=False)
    if flex_players:
        embed.add_field(
            name="🔄 Flex-Spieler",
            value="\n".join(
                f"{fmt(p)}  *({_role_display(p['role'])})*" for p in flex_players
            ),
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

async def _refresh_signup(interaction: discord.Interaction, event_id: int):
    event = await get_event(event_id)
    if not event:
        return
    signups = await get_signups(event_id)
    embed = build_signup_embed(event, signups)
    await interaction.message.edit(embed=embed)


def make_signup_view(event_id: int) -> discord.ui.View:
    """
    Erzeugt eine persistente View mit Select-Menü (Mehrfachauswahl) + Abmelden/Abbrechen.
    custom_ids enthalten event_id für Persistenz nach Bot-Neustart.
    """

    class DynamicSignupView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=None)

        @discord.ui.select(
            placeholder="🎮 Rolle(n) auswählen – Mehrfachauswahl möglich",
            min_values=1,
            max_values=3,
            options=[
                discord.SelectOption(label="Tank",   value="tank",   emoji="🛡️",
                                     description="Ich tanke"),
                discord.SelectOption(label="Heiler", value="healer", emoji="💚",
                                     description="Ich heile"),
                discord.SelectOption(label="DD",     value="dps",    emoji="⚔️",
                                     description="Ich mache Schaden"),
            ],
            custom_id=f"signup_select_{event_id}"
        )
        async def role_select(self_, interaction: discord.Interaction,
                              select: discord.ui.Select):
            chosen = sorted(interaction.data["values"],
                            key=lambda r: ["tank", "healer", "dps"].index(r))
            role_str = ",".join(chosen)
            await add_signup(event_id, str(interaction.user.id),
                             interaction.user.display_name, role_str)
            await _refresh_signup(interaction, event_id)
            label = " + ".join(ROLE_EMOJI[r] + " " + ROLE_LABEL[r] for r in chosen)
            await interaction.response.send_message(
                f"Du bist als **{label}** angemeldet.", ephemeral=True
            )

        @discord.ui.button(label="❌ Abmelden", style=discord.ButtonStyle.danger,
                           custom_id=f"signup_remove_{event_id}", row=1)
        async def btn_remove(self_, interaction: discord.Interaction,
                             button: discord.ui.Button):
            await remove_signup(event_id, str(interaction.user.id))
            await _refresh_signup(interaction, event_id)
            await interaction.response.send_message("Du wurdest abgemeldet.", ephemeral=True)

    return DynamicSignupView()

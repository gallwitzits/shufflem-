import aiosqlite
from datetime import datetime
from typing import Optional

DB_PATH = "shuffle.db"


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                message_id TEXT,
                status TEXT DEFAULT 'signup',
                current_round INTEGER DEFAULT 0,
                scheduled_at TEXT NOT NULL,
                round_duration_minutes INTEGER NOT NULL,
                round_end_at TEXT,
                repeat_days INTEGER,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        # Spalte nachträglich hinzufügen falls DB schon existiert (Migration)
        try:
            await db.execute("ALTER TABLE events ADD COLUMN repeat_days INTEGER")
        except Exception:
            pass
        await db.execute("""
            CREATE TABLE IF NOT EXISTS signups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id INTEGER NOT NULL,
                user_id TEXT NOT NULL,
                username TEXT NOT NULL,
                role TEXT NOT NULL,
                UNIQUE(event_id, user_id),
                FOREIGN KEY (event_id) REFERENCES events(id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS group_assignments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id INTEGER NOT NULL,
                round_number INTEGER NOT NULL,
                group_number INTEGER NOT NULL,
                user_id TEXT NOT NULL,
                role TEXT NOT NULL,
                FOREIGN KEY (event_id) REFERENCES events(id)
            )
        """)
        await db.commit()


async def create_event(guild_id: str, channel_id: str, scheduled_at: datetime,
                       round_duration_minutes: int,
                       repeat_days: int | None = None) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO events (guild_id, channel_id, scheduled_at, round_duration_minutes, repeat_days) "
            "VALUES (?, ?, ?, ?, ?)",
            (guild_id, channel_id, scheduled_at.isoformat(), round_duration_minutes, repeat_days)
        )
        await db.commit()
        return cursor.lastrowid


async def cancel_recurring_for_channel(channel_id: str):
    """Setzt repeat_days = NULL für alle aktiven Events im Channel (stoppt Wiederholung)."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE events SET repeat_days = NULL "
            "WHERE channel_id = ? AND status IN ('signup', 'running')",
            (channel_id,)
        )
        await db.commit()


async def set_event_message(event_id: int, message_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE events SET message_id = ? WHERE id = ?",
            (message_id, event_id)
        )
        await db.commit()


async def get_active_events() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM events WHERE status IN ('signup', 'running')"
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def get_event(event_id: int) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM events WHERE id = ?", (event_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_active_event_for_channel(channel_id: str) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM events WHERE channel_id = ? AND status IN ('signup', 'running') LIMIT 1",
            (channel_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def add_signup(event_id: int, user_id: str, username: str, role: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO signups (event_id, user_id, username, role) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(event_id, user_id) DO UPDATE SET role = excluded.role, username = excluded.username",
            (event_id, user_id, username, role)
        )
        await db.commit()


async def remove_signup(event_id: int, user_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM signups WHERE event_id = ? AND user_id = ?",
            (event_id, user_id)
        )
        await db.commit()


async def remove_player_from_event(event_id: int, user_id: str):
    """Entfernt einen Spieler komplett: aus Signups und allen Gruppenassignments."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM signups WHERE event_id = ? AND user_id = ?",
            (event_id, user_id)
        )
        await db.execute(
            "DELETE FROM group_assignments WHERE event_id = ? AND user_id = ?",
            (event_id, user_id)
        )
        await db.commit()


async def get_signups(event_id: int) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM signups WHERE event_id = ? ORDER BY id",
            (event_id,)
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def save_group_assignments(event_id: int, round_number: int,
                                  groups: list[dict], bench: list[dict]):
    async with aiosqlite.connect(DB_PATH) as db:
        # Gruppen speichern (group_number >= 1)
        for g_num, group in enumerate(groups, start=1):
            await db.execute(
                "INSERT INTO group_assignments (event_id, round_number, group_number, user_id, role) "
                "VALUES (?, ?, ?, ?, ?)",
                (event_id, round_number, g_num, group["tank"]["user_id"], "tank")
            )
            await db.execute(
                "INSERT INTO group_assignments (event_id, round_number, group_number, user_id, role) "
                "VALUES (?, ?, ?, ?, ?)",
                (event_id, round_number, g_num, group["healer"]["user_id"], "healer")
            )
            for dps in group["dps"]:
                await db.execute(
                    "INSERT INTO group_assignments (event_id, round_number, group_number, user_id, role) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (event_id, round_number, g_num, dps["user_id"], "dps")
                )
        # Bench speichern (group_number = 0) für faire Rotation in der nächsten Runde
        for player in bench:
            await db.execute(
                "INSERT INTO group_assignments (event_id, round_number, group_number, user_id, role) "
                "VALUES (?, ?, 0, ?, ?)",
                (event_id, round_number, player["user_id"], player["role"])
            )
        await db.commit()


async def get_player_stats(event_id: int) -> list[dict]:
    """
    Gibt Statistiken pro Spieler zurück:
    - username, role, rounds_played, rounds_bench
    Sortiert nach rounds_played absteigend.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        # Alle Assignments für dieses Event
        cursor = await db.execute(
            "SELECT ga.user_id, s.username, s.role, ga.round_number, ga.group_number "
            "FROM group_assignments ga "
            "JOIN signups s ON s.event_id = ga.event_id AND s.user_id = ga.user_id "
            "WHERE ga.event_id = ?",
            (event_id,)
        )
        rows = await cursor.fetchall()

    stats: dict[str, dict] = {}
    for user_id, username, role, round_number, group_number in rows:
        if user_id not in stats:
            stats[user_id] = {
                "username": username,
                "role": role,
                "rounds_played": 0,
                "rounds_bench": 0,
            }
        if group_number == 0:
            stats[user_id]["rounds_bench"] += 1
        else:
            stats[user_id]["rounds_played"] += 1

    return sorted(stats.values(), key=lambda x: (-x["rounds_played"], x["username"]))


async def get_bench_ids_from_last_round(event_id: int, round_number: int) -> set[str]:
    """Gibt die user_ids zurück die in der angegebenen Runde auf der Bench waren."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT user_id FROM group_assignments "
            "WHERE event_id = ? AND round_number = ? AND group_number = 0",
            (event_id, round_number)
        )
        rows = await cursor.fetchall()
        return {row[0] for row in rows}


async def get_groups_for_round(event_id: int, round_number: int) -> tuple[list[dict], list[dict]]:
    """Lädt die aktuellen Gruppen und Bench aus der DB für eine Runde."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT ga.user_id, s.username, s.role AS signup_role, ga.role AS assigned_role, ga.group_number "
            "FROM group_assignments ga "
            "JOIN signups s ON s.event_id = ga.event_id AND s.user_id = ga.user_id "
            "WHERE ga.event_id = ? AND ga.round_number = ? "
            "ORDER BY ga.group_number, ga.role",
            (event_id, round_number)
        )
        rows = await cursor.fetchall()

    groups_dict: dict[int, dict] = {}
    bench: list[dict] = []

    for row in rows:
        player = {
            "user_id":       row["user_id"],
            "username":      row["username"],
            "role":          row["signup_role"],
            "assigned_role": row["assigned_role"],
        }
        gnum = row["group_number"]
        if gnum == 0:
            bench.append(player)
        else:
            if gnum not in groups_dict:
                groups_dict[gnum] = {"tank": None, "healer": None, "dps": []}
            ar = row["assigned_role"]
            if ar == "tank":
                groups_dict[gnum]["tank"] = player
            elif ar == "healer":
                groups_dict[gnum]["healer"] = player
            else:
                groups_dict[gnum]["dps"].append(player)

    groups = [groups_dict[k] for k in sorted(groups_dict)]
    return groups, bench


async def swap_players(event_id: int, round_number: int,
                       user_id_a: str, user_id_b: str) -> bool:
    """
    Tauscht zwei Spieler in der aktuellen Runde.
    Swapped group_number UND assigned_role damit die Gruppenstruktur korrekt bleibt.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT user_id, group_number, role FROM group_assignments "
            "WHERE event_id = ? AND round_number = ? AND user_id IN (?, ?)",
            (event_id, round_number, user_id_a, user_id_b)
        )
        rows = await cursor.fetchall()
        if len(rows) != 2:
            return False

        data = {r[0]: {"group_number": r[1], "role": r[2]} for r in rows}
        a, b = data[user_id_a], data[user_id_b]

        await db.execute(
            "UPDATE group_assignments SET group_number = ?, role = ? "
            "WHERE event_id = ? AND round_number = ? AND user_id = ?",
            (b["group_number"], b["role"], event_id, round_number, user_id_a)
        )
        await db.execute(
            "UPDATE group_assignments SET group_number = ?, role = ? "
            "WHERE event_id = ? AND round_number = ? AND user_id = ?",
            (a["group_number"], a["role"], event_id, round_number, user_id_b)
        )
        await db.commit()
        return True


async def update_event_round(event_id: int, round_number: int, round_end_at: datetime):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE events SET status = 'running', current_round = ?, round_end_at = ? WHERE id = ?",
            (round_number, round_end_at.isoformat(), event_id)
        )
        await db.commit()


async def finish_event(event_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE events SET status = 'finished', round_end_at = NULL WHERE id = ?",
            (event_id,)
        )
        await db.commit()

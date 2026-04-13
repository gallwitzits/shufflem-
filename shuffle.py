import random


def build_groups(signups: list[dict],
                 prev_bench_ids: set[str] | None = None) -> tuple[list[dict], list[dict]]:
    """
    Bildet möglichst viele vollständige M+ Gruppen.
    Vollständige Gruppe = 1 Tank + 1 Heiler + 3 DDs

    Args:
        signups:       Liste von dicts mit Schlüsseln: user_id, username, role
        prev_bench_ids: user_ids die in der letzten Runde auf der Bench waren –
                        diese bekommen Vorrang damit alle fair rotieren

    Returns:
        (groups, bench)
        groups: Liste von {'tank': ..., 'healer': ..., 'dps': [...]}
        bench:  Liste von nicht zugeteilten Spieler-dicts
    """
    if prev_bench_ids is None:
        prev_bench_ids = set()

    tanks   = [s for s in signups if s["role"] == "tank"]
    healers = [s for s in signups if s["role"] == "healer"]
    dps     = [s for s in signups if s["role"] == "dps"]

    def sort_key(p: dict) -> tuple:
        # Bench-Spieler vom letzten Run kommen zuerst, Rest zufällig
        was_bench = p["user_id"] in prev_bench_ids
        return (0 if was_bench else 1, random.random())

    tanks.sort(key=sort_key)
    healers.sort(key=sort_key)
    dps.sort(key=sort_key)

    num_groups = min(len(tanks), len(healers), len(dps) // 3)

    groups = []
    for i in range(num_groups):
        groups.append({
            "tank":   tanks[i],
            "healer": healers[i],
            "dps":    dps[i * 3: i * 3 + 3],
        })

    bench = (
        tanks[num_groups:]
        + healers[num_groups:]
        + dps[num_groups * 3:]
    )
    return groups, bench


def can_build_group(signups: list[dict]) -> bool:
    """Prüft ob mindestens eine vollständige Gruppe gebildet werden kann."""
    tanks   = sum(1 for s in signups if s["role"] == "tank")
    healers = sum(1 for s in signups if s["role"] == "healer")
    dps     = sum(1 for s in signups if s["role"] == "dps")
    return tanks >= 1 and healers >= 1 and dps >= 3

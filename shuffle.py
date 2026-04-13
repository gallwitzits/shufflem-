import random


def _ordered_candidates(players: list[dict], role: str, prev_bench_ids: set[str]) -> list[dict]:
    """
    Sortiert Kandidaten für eine Rolle in 4 Prioritäts-Buckets:
      1. Bench + nur diese Rolle  (höchste Priorität)
      2. Bench + Flex-Spieler
      3. Aktiv + nur diese Rolle
      4. Aktiv + Flex-Spieler
    Innerhalb jedes Buckets wird zufällig gemischt (echter Random).
    """
    bp, bf, ap, af = [], [], [], []
    for p in players:
        on_bench  = p["user_id"] in prev_bench_ids
        pure_role = p.get("roles", [p["role"]]) == [role]
        if on_bench and pure_role:
            bp.append(p)
        elif on_bench:
            bf.append(p)
        elif pure_role:
            ap.append(p)
        else:
            af.append(p)
    for bucket in (bp, bf, ap, af):
        random.shuffle(bucket)
    return bp + bf + ap + af


def build_groups(signups: list[dict],
                 prev_bench_ids: set[str] | None = None) -> tuple[list[dict], list[dict]]:
    """
    Bildet möglichst viele vollständige M+ Gruppen.
    Vollständige Gruppe = 1 Tank + 1 Heiler + 3 DDs.

    Unterstützt Flex-Spieler: signups[i]["role"] kann komma-getrennte Rollen
    enthalten, z.B. "tank,dps" oder "healer,dps".

    Priorität beim Zuweisen:
      - Bench-Spieler aus der letzten Runde kommen zuerst
      - Innerhalb gleicher Bench-Priorität: reine Rollenspieler vor Flex-Spielern
    """
    if prev_bench_ids is None:
        prev_bench_ids = set()

    # Rollen-Liste pro Spieler aufbauen
    for s in signups:
        if "roles" not in s:
            s["roles"] = [r.strip() for r in s["role"].split(",")]

    assigned: set[str] = set()

    def pick(role: str, n: int) -> list[dict]:
        candidates = [p for p in signups
                      if role in p["roles"] and p["user_id"] not in assigned]
        ordered = _ordered_candidates(candidates, role, prev_bench_ids)
        picked = ordered[:n]
        for p in picked:
            assigned.add(p["user_id"])
        return picked

    groups = []
    while True:
        tanks = pick("tank", 1)
        if not tanks:
            break
        healers = pick("healer", 1)
        if not healers:
            assigned.discard(tanks[0]["user_id"])
            break
        dps_list = pick("dps", 3)
        if len(dps_list) < 3:
            assigned.discard(tanks[0]["user_id"])
            assigned.discard(healers[0]["user_id"])
            for p in dps_list:
                assigned.discard(p["user_id"])
            break

        groups.append({
            "tank":   {**tanks[0],   "assigned_role": "tank"},
            "healer": {**healers[0], "assigned_role": "healer"},
            "dps":    [{**p, "assigned_role": "dps"} for p in dps_list],
        })

    bench = [p for p in signups if p["user_id"] not in assigned]
    return groups, bench


def can_build_group(signups: list[dict]) -> bool:
    """Prüft ob mindestens eine vollständige Gruppe gebildet werden kann."""
    for s in signups:
        if "roles" not in s:
            s["roles"] = [r.strip() for r in s["role"].split(",")]

    tank_capable   = sum(1 for s in signups if "tank"   in s["roles"])
    healer_capable = sum(1 for s in signups if "healer" in s["roles"])
    dps_capable    = sum(1 for s in signups if "dps"    in s["roles"])
    return tank_capable >= 1 and healer_capable >= 1 and dps_capable >= 3


def count_possible_groups(signups: list[dict]) -> int:
    """Schätzt die maximale Gruppenanzahl (für Embed-Anzeige)."""
    groups, _ = build_groups(signups)
    return len(groups)

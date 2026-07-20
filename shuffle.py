import random


def _bucket(p: dict, role: str, prev_bench_ids: set[str]) -> int:
    """
    Fairness-Bucket eines Kandidaten (kleiner = höhere Priorität):
      0. Bench + nur diese Rolle
      1. Bench + Flex-Spieler
      2. Aktiv + nur diese Rolle
      3. Aktiv + Flex-Spieler
    """
    on_bench  = p["user_id"] in prev_bench_ids
    pure_role = p.get("roles", [p["role"]]) == [role]
    if on_bench and pure_role:
        return 0
    if on_bench:
        return 1
    if pure_role:
        return 2
    return 3


def _pair_score(user_id: str, group_ids: list[str],
                pair_counts: dict[tuple[str, str], int] | None) -> int:
    """
    Wie oft war dieser Spieler in vergangenen Runden schon mit den bereits
    zugewiesenen Mitgliedern der Gruppe zusammen? (0 = komplett frische Paarung)
    """
    if not pair_counts or not group_ids:
        return 0
    total = 0
    for other in group_ids:
        total += pair_counts.get(tuple(sorted((user_id, other))), 0)
    return total


def _greedy_assign(signups: list[dict],
                   prev_bench_ids: set[str]) -> tuple[list[dict], list[dict]]:
    """
    PHASE 1 – Fairness: entscheidet, WER spielt und in welcher Rolle.

    Bildet möglichst viele vollständige Gruppen (1 Tank + 1 Heiler + 3 DDs).
    Bench-Spieler der letzten Runde werden bevorzugt eingeteilt, reine
    Rollenspieler vor Flex-Spielern. Innerhalb gleicher Priorität: Zufall.
    Die konkrete Gruppen-Zusammenstellung ist hier noch egal – die optimiert
    Phase 2 (_distribute).
    """
    assigned: set[str] = set()

    def pick(role: str, n: int) -> list[dict]:
        candidates = [p for p in signups
                      if role in p["roles"] and p["user_id"] not in assigned]
        candidates.sort(key=lambda p: (_bucket(p, role, prev_bench_ids), random.random()))
        picked = candidates[:n]
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
            for p in tanks + healers + dps_list:
                assigned.discard(p["user_id"])
            break

        groups.append({
            "tank":   {**tanks[0],   "assigned_role": "tank"},
            "healer": {**healers[0], "assigned_role": "healer"},
            "dps":    [{**p, "assigned_role": "dps"} for p in dps_list],
        })

    bench = [p for p in signups if p["user_id"] not in assigned]
    return groups, bench


def _distribute(groups_raw: list[dict],
                pair_counts: dict[tuple[str, str], int]) -> list[dict]:
    """
    PHASE 2 – Abwechslung: verteilt die schon feststehenden Spieler (gleiche
    Personen, gleiche Rollen wie aus Phase 1) so auf die Gruppen, dass Spieler,
    die zuletzt oft zusammen waren, möglichst NICHT wieder zusammenkommen.

    Fairness bleibt dabei komplett erhalten – es spielt niemand mehr oder
    weniger, nur die Zusammenstellung der Gruppen ändert sich.
    """
    g = len(groups_raw)
    if g <= 1:
        return groups_raw

    tanks   = [grp["tank"] for grp in groups_raw]
    healers = [grp["healer"] for grp in groups_raw]
    dps     = [d for grp in groups_raw for d in grp["dps"]]

    random.shuffle(tanks)
    random.shuffle(healers)
    random.shuffle(dps)

    result   = [{"tank": None, "healer": None, "dps": []} for _ in range(g)]
    members  = [[] for _ in range(g)]  # user_ids je Gruppe (für pair_score)

    # Tanks: je einer pro Gruppe (untereinander gleichwertig -> Reihenfolge zufällig)
    for i, tank in enumerate(tanks):
        result[i]["tank"] = tank
        members[i].append(tank["user_id"])

    # Heiler: jeweils in die Gruppe, mit deren Tank er zuletzt am seltensten war
    for healer in healers:
        best = min(
            (i for i in range(g) if result[i]["healer"] is None),
            key=lambda i: (_pair_score(healer["user_id"], members[i], pair_counts),
                           random.random()),
        )
        result[best]["healer"] = healer
        members[best].append(healer["user_id"])

    # DDs: einzeln in die noch offene Gruppe mit den wenigsten Wiederholungen
    for d in dps:
        best = min(
            (i for i in range(g) if len(result[i]["dps"]) < 3),
            key=lambda i: (_pair_score(d["user_id"], members[i], pair_counts),
                           random.random()),
        )
        result[best]["dps"].append(d)
        members[best].append(d["user_id"])

    return result


def build_groups(signups: list[dict],
                 prev_bench_ids: set[str] | None = None,
                 pair_counts: dict[tuple[str, str], int] | None = None
                 ) -> tuple[list[dict], list[dict]]:
    """
    Bildet möglichst viele vollständige M+ Gruppen (1 Tank + 1 Heiler + 3 DDs).

    Unterstützt Flex-Spieler: signups[i]["role"] kann komma-getrennte Rollen
    enthalten, z.B. "tank,dps" oder "healer,dps".

    Zwei Phasen:
      1. Fairness  – wer spielt / wer ist Bench (Bench-Rotation, _greedy_assign)
      2. Abwechslung – wie die Spieler auf die Gruppen verteilt werden, damit
         nicht immer die gleichen Leute zusammen sind (_distribute)

    pair_counts: {tuple(sorted((user_a, user_b))): anzahl_gemeinsamer_runden}.
    Ohne pair_counts entfällt Phase 2 (Verhalten wie zuvor: Fairness + Zufall).
    """
    if prev_bench_ids is None:
        prev_bench_ids = set()

    # Rollen-Liste pro Spieler aufbauen
    for s in signups:
        if "roles" not in s:
            s["roles"] = [r.strip() for r in s["role"].split(",")]

    groups, bench = _greedy_assign(signups, prev_bench_ids)

    if pair_counts and len(groups) > 1:
        groups = _distribute(groups, pair_counts)

    return groups, bench


def can_build_group(signups: list[dict]) -> bool:
    """Prüft ob mindestens eine vollständige Gruppe gebildet werden kann."""
    groups, _ = build_groups([dict(s) for s in signups])
    return bool(groups)


def count_possible_groups(signups: list[dict]) -> int:
    """Schätzt die maximale Gruppenanzahl (für Embed-Anzeige)."""
    groups, _ = build_groups(signups)
    return len(groups)

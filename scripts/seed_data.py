"""
Seed database with realistic CS2 team data, players, and match history.
Includes player ratings, AWPer roles, roster stability, map strengths.
"""

import sys
import os
import random
import logging
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.database import init_db, get_connection
from models.rating_systems import recalculate_all_ratings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# (name, ranking, strength, roster_age_days, roster_changes, country)
TOP_TEAMS = [
    ("Natus Vincere", 1, 0.92, 200, 0, "UA"),
    ("FaZe Clan", 2, 0.90, 180, 0, "EU"),
    ("G2 Esports", 3, 0.89, 150, 1, "EU"),
    ("Team Vitality", 4, 0.88, 220, 0, "FR"),
    ("MOUZ", 5, 0.87, 160, 0, "EU"),
    ("Team Spirit", 6, 0.86, 190, 0, "RU"),
    ("Heroic", 7, 0.84, 120, 1, "DK"),
    ("Virtus.pro", 8, 0.83, 140, 0, "RU"),
    ("Team Liquid", 9, 0.82, 100, 1, "US"),
    ("Complexity Gaming", 10, 0.81, 130, 0, "US"),
    ("Eternal Fire", 11, 0.80, 170, 0, "TR"),
    ("FURIA Esports", 12, 0.79, 200, 0, "BR"),
    ("paiN Gaming", 13, 0.78, 90, 1, "BR"),
    ("3DMAX", 14, 0.77, 110, 0, "FR"),
    ("BIG", 15, 0.76, 80, 2, "DE"),
    ("SAW", 16, 0.75, 150, 0, "PT"),
    ("GamerLegion", 17, 0.74, 60, 1, "EU"),
    ("Monte", 18, 0.73, 70, 1, "UA"),
    ("Cloud9", 19, 0.72, 50, 2, "EU"),
    ("fnatic", 20, 0.71, 40, 2, "EU"),
    ("Astralis", 21, 0.70, 90, 1, "DK"),
    ("9 Pandas", 22, 0.69, 100, 0, "RU"),
    ("Imperial Esports", 23, 0.68, 130, 0, "BR"),
    ("ECSTATIC", 24, 0.67, 110, 1, "DK"),
    ("Wildcard", 25, 0.66, 80, 0, "AU"),
    ("TheMongolz", 26, 0.70, 200, 0, "MN"),
    ("Lynn Vision", 27, 0.65, 120, 0, "CN"),
    ("Passion UA", 28, 0.64, 60, 2, "UA"),
    ("B8", 29, 0.63, 50, 1, "EU"),
    ("MIBR", 30, 0.62, 40, 3, "BR"),
]

# (nickname, rating, adr, kast, kd, hs%, is_awper)
TEAM_PLAYERS = {
    "Natus Vincere": [
        ("s1mple", 1.30, 87, 0.75, 1.35, 0.42, 1),
        ("b1t", 1.12, 78, 0.72, 1.15, 0.52, 0),
        ("jL", 1.08, 75, 0.70, 1.10, 0.50, 0),
        ("Aleksib", 0.98, 65, 0.68, 0.95, 0.45, 0),
        ("iM", 1.05, 72, 0.69, 1.05, 0.48, 0),
    ],
    "FaZe Clan": [
        ("broky", 1.18, 80, 0.73, 1.22, 0.38, 1),
        ("ropz", 1.15, 78, 0.74, 1.18, 0.55, 0),
        ("rain", 1.05, 74, 0.70, 1.08, 0.47, 0),
        ("karrigan", 0.92, 60, 0.66, 0.88, 0.43, 0),
        ("frozen", 1.10, 76, 0.71, 1.12, 0.52, 0),
    ],
    "G2 Esports": [
        ("NiKo", 1.22, 82, 0.74, 1.25, 0.56, 0),
        ("m0NESY", 1.25, 85, 0.72, 1.28, 0.40, 1),
        ("huNter-", 1.08, 74, 0.70, 1.10, 0.48, 0),
        ("nexa", 1.00, 68, 0.69, 1.02, 0.46, 0),
        ("HooXi", 0.85, 55, 0.64, 0.82, 0.42, 0),
    ],
    "Team Vitality": [
        ("ZywOo", 1.28, 86, 0.76, 1.32, 0.42, 1),
        ("flameZ", 1.10, 76, 0.71, 1.12, 0.50, 0),
        ("apEX", 0.95, 65, 0.67, 0.92, 0.45, 0),
        ("Spinx", 1.08, 74, 0.70, 1.08, 0.49, 0),
        ("mezii", 1.02, 70, 0.69, 1.00, 0.47, 0),
    ],
    "MOUZ": [
        ("torzsi", 1.12, 77, 0.72, 1.15, 0.40, 1),
        ("xertioN", 1.08, 75, 0.70, 1.10, 0.52, 0),
        ("Jimpphat", 1.05, 73, 0.69, 1.06, 0.50, 0),
        ("siuhy", 0.95, 64, 0.67, 0.92, 0.44, 0),
        ("Brollan", 1.10, 76, 0.71, 1.12, 0.53, 0),
    ],
}

MAPS = ["Mirage", "Inferno", "Nuke", "Overpass", "Ancient", "Anubis", "Dust2"]

MAP_STRENGTHS = {
    "Natus Vincere": {"Inferno": 0.15, "Nuke": 0.10, "Dust2": -0.10},
    "FaZe Clan": {"Mirage": 0.12, "Overpass": 0.10, "Ancient": -0.08},
    "G2 Esports": {"Nuke": 0.15, "Inferno": 0.08, "Anubis": -0.10},
    "Team Vitality": {"Overpass": 0.12, "Ancient": 0.10, "Mirage": -0.05},
    "MOUZ": {"Anubis": 0.12, "Dust2": 0.08, "Nuke": -0.10},
}

# (event_name, is_lan, event_tier, is_playoff)
EVENTS = [
    ("PGL Major Copenhagen", True, 5, True),
    ("BLAST Premier World Final", True, 4, True),
    ("IEM Katowice", True, 4, True),
    ("IEM Cologne", True, 4, True),
    ("ESL Pro League S20", True, 4, False),
    ("BLAST Premier Spring Finals", True, 4, True),
    ("Thunderpick World Championship", True, 3, False),
    ("CCT Online Finals", False, 2, False),
    ("ESL Challenger", False, 2, False),
    ("BetBoom Dacha", True, 3, False),
    ("BLAST Bounty Spring", False, 2, False),
    ("Skyesports Masters", True, 2, False),
]


def seed_teams(conn):
    for name, ranking, _, roster_age, roster_changes, country in TOP_TEAMS:
        conn.execute("""
            INSERT OR IGNORE INTO teams (name, world_ranking, roster_age_days,
                                         roster_changes_6m, country, updated_at)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (name, ranking, roster_age, roster_changes, country))
    conn.commit()
    logger.info("Seeded %d teams", len(TOP_TEAMS))


def seed_players(conn):
    count = 0
    for team_name, players in TEAM_PLAYERS.items():
        row = conn.execute("SELECT id FROM teams WHERE name = ?", (team_name,)).fetchone()
        if not row:
            continue
        tid = row["id"]
        for nick, rating, adr, kast, kd, hs, is_awp in players:
            conn.execute("""
                INSERT OR IGNORE INTO players
                    (name, nickname, team_id, rating_2_1, adr, kast, kd_ratio,
                     headshot_pct, is_awper)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (nick, nick, tid, rating, adr, kast, kd, hs, is_awp))
            count += 1
    for name, _, strength, *_ in TOP_TEAMS:
        if name in TEAM_PLAYERS:
            continue
        row = conn.execute("SELECT id FROM teams WHERE name = ?", (name,)).fetchone()
        if not row:
            continue
        tid = row["id"]
        base = 0.85 + strength * 0.3
        for i in range(5):
            r = base + random.gauss(0, 0.08)
            conn.execute("""
                INSERT OR IGNORE INTO players
                    (name, nickname, team_id, rating_2_1, adr, kast, kd_ratio,
                     headshot_pct, is_awper)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (f"Player{i+1}", f"p{i+1}_{name[:3]}", tid,
                  round(r, 2), round(60 + r * 15, 1), round(0.60 + r * 0.08, 2),
                  round(0.85 + r * 0.2, 2), round(0.40 + random.random() * 0.15, 2),
                  1 if i == 0 else 0))
            count += 1
    conn.commit()
    logger.info("Seeded %d players", count)


def generate_matches(conn, num_matches=800):
    teams = conn.execute("SELECT id, name FROM teams").fetchall()
    team_ids = [t["id"] for t in teams]
    team_names = {t["id"]: t["name"] for t in teams}

    strength_map = {}
    for name, _, strength, *_ in TOP_TEAMS:
        row = conn.execute("SELECT id FROM teams WHERE name = ?", (name,)).fetchone()
        if row:
            strength_map[row["id"]] = strength

    start_date = datetime.utcnow() - timedelta(days=365)

    for i in range(num_matches):
        t1_id, t2_id = random.sample(team_ids, 2)
        s1 = strength_map.get(t1_id, 0.5)
        s2 = strength_map.get(t2_id, 0.5)
        map_name = random.choice(MAPS)
        t1_name = team_names.get(t1_id, "")
        t2_name = team_names.get(t2_id, "")
        map_adj1 = MAP_STRENGTHS.get(t1_name, {}).get(map_name, 0)
        map_adj2 = MAP_STRENGTHS.get(t2_name, {}).get(map_name, 0)
        effective_s1 = s1 + map_adj1 + random.gauss(0, 0.10)
        effective_s2 = s2 + map_adj2 + random.gauss(0, 0.10)
        team1_wins = effective_s1 > effective_s2
        winner_id = t1_id if team1_wins else t2_id

        event_name, is_lan, event_tier, is_playoff = random.choice(EVENTS)
        best_of = random.choice([1, 1, 1, 3, 3, 5])
        overtime = 0

        if best_of == 1:
            w_rounds = random.randint(13, 16)
            l_rounds = random.randint(5, min(15, w_rounds - 1))
            if w_rounds == 13 and l_rounds >= 12:
                overtime = 1
            if team1_wins:
                t1_score, t2_score = w_rounds, l_rounds
            else:
                t1_score, t2_score = l_rounds, w_rounds
        elif best_of == 3:
            t1_score = 2 if team1_wins else random.choice([0, 1])
            t2_score = random.choice([0, 1]) if team1_wins else 2
        else:
            t1_score = 3 if team1_wins else random.choice([0, 1, 2])
            t2_score = random.choice([0, 1, 2]) if team1_wins else 3

        match_date = start_date + timedelta(
            days=int(i * 365 / num_matches), hours=random.randint(10, 22),
        )
        conn.execute("""
            INSERT INTO matches
                (team1_id, team2_id, team1_score, team2_score, winner_id,
                 best_of, event_name, event_tier, is_lan, is_playoff,
                 map_name, match_date, overtime,
                 team1_first_kills, team2_first_kills,
                 team1_pistol_wins, team2_pistol_wins)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (t1_id, t2_id, t1_score, t2_score, winner_id,
              best_of, event_name, event_tier, 1 if is_lan else 0,
              1 if is_playoff else 0, map_name, match_date.isoformat(),
              overtime, random.randint(3, 8), random.randint(3, 8),
              random.randint(0, 2), random.randint(0, 2)))

    conn.commit()
    logger.info("Generated %d matches over 12 months", num_matches)


def seed_map_stats(conn):
    teams = conn.execute("SELECT id FROM teams").fetchall()
    for team in teams:
        tid = team["id"]
        for map_name in MAPS:
            wins = conn.execute(
                "SELECT COUNT(*) as c FROM matches WHERE winner_id = ? AND map_name = ?",
                (tid, map_name)).fetchone()["c"]
            total = conn.execute(
                "SELECT COUNT(*) as c FROM matches WHERE (team1_id = ? OR team2_id = ?) AND map_name = ?",
                (tid, tid, map_name)).fetchone()["c"]
            if total > 0:
                wr = wins / total
                conn.execute("""
                    INSERT OR REPLACE INTO team_map_ratings
                        (team_id, map_name, rating, matches_played, wins,
                         ct_wr, t_wr, avg_rounds_won, pistol_wr, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """, (tid, map_name, 1500 + (wr - 0.5) * 400, total, wins,
                      round(0.48 + random.random() * 0.10, 3),
                      round(0.45 + random.random() * 0.10, 3),
                      round(7 + wr * 4, 1),
                      round(0.40 + random.random() * 0.20, 3)))
    conn.commit()
    logger.info("Seeded map stats")


def run_seed():
    init_db()
    conn = get_connection()
    count = conn.execute("SELECT COUNT(*) as c FROM teams").fetchone()["c"]
    if count > 0:
        logger.info("Re-seeding database...")
        for table in ["predictions", "team_map_ratings", "team_ratings",
                       "map_stats", "matches", "players", "teams"]:
            conn.execute(f"DELETE FROM {table}")
        conn.commit()

    seed_teams(conn)
    seed_players(conn)
    generate_matches(conn, num_matches=800)
    seed_map_stats(conn)
    conn.close()

    n = recalculate_all_ratings()
    logger.info("Recalculated ratings from %d matches", n)
    logger.info("Seed complete!")


if __name__ == "__main__":
    run_seed()

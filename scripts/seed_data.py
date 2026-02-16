"""
Seed database with realistic CS2 team data and historical match results.
Uses well-known CS2 professional teams and generates realistic match history
for initial model training.
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

# Top CS2 teams with approximate strength ratings (for realistic seed generation)
# Format: (name, world_ranking, approximate_strength)
TOP_TEAMS = [
    ("Natus Vincere", 1, 0.92),
    ("FaZe Clan", 2, 0.90),
    ("G2 Esports", 3, 0.89),
    ("Team Vitality", 4, 0.88),
    ("MOUZ", 5, 0.87),
    ("Team Spirit", 6, 0.86),
    ("Heroic", 7, 0.84),
    ("Virtus.pro", 8, 0.83),
    ("Team Liquid", 9, 0.82),
    ("Complexity Gaming", 10, 0.81),
    ("Eternal Fire", 11, 0.80),
    ("FURIA Esports", 12, 0.79),
    ("paiN Gaming", 13, 0.78),
    ("3DMAX", 14, 0.77),
    ("BIG", 15, 0.76),
    ("SAW", 16, 0.75),
    ("GamerLegion", 17, 0.74),
    ("Monte", 18, 0.73),
    ("Cloud9", 19, 0.72),
    ("fnatic", 20, 0.71),
    ("Astralis", 21, 0.70),
    ("9 Pandas", 22, 0.69),
    ("Imperial Esports", 23, 0.68),
    ("ECSTATIC", 24, 0.67),
    ("Wildcard", 25, 0.66),
    ("TheMongolz", 26, 0.70),
    ("Lynn Vision", 27, 0.65),
    ("Passion UA", 28, 0.64),
    ("B8", 29, 0.63),
    ("MIBR", 30, 0.62),
]

MAPS = ["Mirage", "Inferno", "Nuke", "Overpass", "Ancient", "Anubis", "Dust2"]

EVENTS = [
    ("PGL Major", True),
    ("BLAST Premier", True),
    ("IEM Katowice", True),
    ("IEM Cologne", True),
    ("ESL Pro League", True),
    ("BLAST Premier Spring", True),
    ("Thunderpick World Championship", True),
    ("CCT Online Finals", False),
    ("ESL Challenger", False),
    ("BetBoom Dacha", True),
    ("BLAST Bounty", False),
    ("Skyesports Masters", True),
]


def seed_teams(conn):
    """Insert top teams into the database."""
    for name, ranking, _ in TOP_TEAMS:
        conn.execute("""
            INSERT OR IGNORE INTO teams (name, world_ranking, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
        """, (name, ranking))
    conn.commit()
    logger.info("Seeded %d teams", len(TOP_TEAMS))


def generate_matches(conn, num_matches=500):
    """Generate realistic historical match results."""
    teams = conn.execute("SELECT id, name FROM teams").fetchall()
    team_ids = [t["id"] for t in teams]
    team_map = {t["id"]: t["name"] for t in teams}

    # Build strength map
    strength_map = {}
    for name, _, strength in TOP_TEAMS:
        row = conn.execute("SELECT id FROM teams WHERE name = ?", (name,)).fetchone()
        if row:
            strength_map[row["id"]] = strength

    start_date = datetime.utcnow() - timedelta(days=180)
    matches_created = 0

    for i in range(num_matches):
        # Pick two different teams
        t1_id, t2_id = random.sample(team_ids, 2)
        s1 = strength_map.get(t1_id, 0.5)
        s2 = strength_map.get(t2_id, 0.5)

        # Add some randomness (upsets happen ~20-30% of the time)
        noise1 = random.gauss(0, 0.12)
        noise2 = random.gauss(0, 0.12)
        effective_s1 = s1 + noise1
        effective_s2 = s2 + noise2

        # Determine winner based on effective strength
        team1_wins = effective_s1 > effective_s2
        winner_id = t1_id if team1_wins else t2_id

        # Generate scores
        best_of = random.choice([1, 1, 1, 3, 3, 5])
        if best_of == 1:
            w_rounds = random.randint(13, 16)
            l_rounds = random.randint(5, min(15, w_rounds - 1))
            if team1_wins:
                t1_score, t2_score = w_rounds, l_rounds
            else:
                t1_score, t2_score = l_rounds, w_rounds
        elif best_of == 3:
            if team1_wins:
                t1_score = 2
                t2_score = random.choice([0, 1])
            else:
                t2_score = 2
                t1_score = random.choice([0, 1])
        else:  # bo5
            if team1_wins:
                t1_score = 3
                t2_score = random.choice([0, 1, 2])
            else:
                t2_score = 3
                t1_score = random.choice([0, 1, 2])

        # Random date within the last 6 months
        match_date = start_date + timedelta(
            days=random.randint(0, 180),
            hours=random.randint(8, 22),
        )

        # Random event
        event_name, is_lan = random.choice(EVENTS)
        map_name = random.choice(MAPS)

        conn.execute("""
            INSERT INTO matches
                (team1_id, team2_id, team1_score, team2_score, winner_id,
                 best_of, event_name, is_lan, map_name, match_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (t1_id, t2_id, t1_score, t2_score, winner_id,
              best_of, event_name, 1 if is_lan else 0, map_name,
              match_date.isoformat()))
        matches_created += 1

    conn.commit()
    logger.info("Generated %d matches", matches_created)
    return matches_created


def seed_map_stats(conn):
    """Generate map stats from match data."""
    teams = conn.execute("SELECT id FROM teams").fetchall()
    for team in teams:
        tid = team["id"]
        for map_name in MAPS:
            wins = conn.execute("""
                SELECT COUNT(*) as c FROM matches
                WHERE winner_id = ? AND map_name = ?
            """, (tid, map_name)).fetchone()["c"]
            total = conn.execute("""
                SELECT COUNT(*) as c FROM matches
                WHERE (team1_id = ? OR team2_id = ?) AND map_name = ?
            """, (tid, tid, map_name)).fetchone()["c"]
            if total > 0:
                rating = 1500 + (wins / total - 0.5) * 400
                conn.execute("""
                    INSERT OR REPLACE INTO team_map_ratings
                        (team_id, map_name, rating, matches_played, wins, updated_at)
                    VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """, (tid, map_name, rating, total, wins))
    conn.commit()
    logger.info("Seeded map stats for all teams")


def run_seed():
    """Run full seed process."""
    init_db()
    conn = get_connection()

    # Check if already seeded
    count = conn.execute("SELECT COUNT(*) as c FROM teams").fetchone()["c"]
    if count > 0:
        logger.info("Database already has %d teams. Skipping seed.", count)
        conn.close()
        return

    seed_teams(conn)
    generate_matches(conn, num_matches=500)
    seed_map_stats(conn)
    conn.close()

    # Calculate ratings from match history
    n = recalculate_all_ratings()
    logger.info("Recalculated ratings from %d matches", n)

    logger.info("Seed complete!")


if __name__ == "__main__":
    run_seed()

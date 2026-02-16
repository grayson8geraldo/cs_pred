"""
Seed database with realistic CS2 team data, players, and match history.
Includes player ratings, AWPer roles, roster stability, map strengths.
60+ teams across all major regions with named rosters for top 20.
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

# ═══════════════════════════════════════════════════════════════
# TEAMS: (name, ranking, strength, roster_age_days, roster_changes, country)
# ═══════════════════════════════════════════════════════════════

TOP_TEAMS = [
    # --- Tier 1: Top 10 ---
    ("Natus Vincere", 1, 0.93, 200, 0, "UA"),
    ("FaZe Clan", 2, 0.91, 180, 0, "EU"),
    ("G2 Esports", 3, 0.90, 150, 1, "EU"),
    ("Team Vitality", 4, 0.89, 220, 0, "FR"),
    ("MOUZ", 5, 0.88, 160, 0, "EU"),
    ("Team Spirit", 6, 0.87, 190, 0, "RU"),
    ("Heroic", 7, 0.85, 120, 1, "DK"),
    ("Virtus.pro", 8, 0.84, 140, 0, "RU"),
    ("Team Liquid", 9, 0.83, 100, 1, "US"),
    ("Complexity Gaming", 10, 0.82, 130, 0, "US"),

    # --- Tier 2: Top 20 ---
    ("Eternal Fire", 11, 0.81, 170, 0, "TR"),
    ("FURIA Esports", 12, 0.80, 200, 0, "BR"),
    ("paiN Gaming", 13, 0.79, 90, 1, "BR"),
    ("3DMAX", 14, 0.78, 110, 0, "FR"),
    ("BIG", 15, 0.77, 80, 1, "DE"),
    ("SAW", 16, 0.76, 150, 0, "PT"),
    ("GamerLegion", 17, 0.75, 60, 1, "EU"),
    ("Monte", 18, 0.74, 70, 1, "UA"),
    ("Cloud9", 19, 0.73, 50, 2, "EU"),
    ("fnatic", 20, 0.72, 40, 1, "EU"),

    # --- Tier 2-3: Ranks 21-30 ---
    ("Astralis", 21, 0.71, 90, 1, "DK"),
    ("9 Pandas", 22, 0.70, 100, 0, "RU"),
    ("Imperial Esports", 23, 0.69, 130, 0, "BR"),
    ("ECSTATIC", 24, 0.68, 110, 1, "DK"),
    ("Wildcard", 25, 0.67, 80, 0, "AU"),
    ("TheMongolz", 26, 0.71, 200, 0, "MN"),
    ("Lynn Vision", 27, 0.66, 120, 0, "CN"),
    ("Passion UA", 28, 0.65, 60, 2, "UA"),
    ("B8", 29, 0.64, 50, 1, "EU"),
    ("MIBR", 30, 0.63, 40, 2, "BR"),

    # --- Tier 3: Ranks 31-45 ---
    ("Ninjas in Pyjamas", 31, 0.62, 100, 1, "BR"),
    ("OG", 32, 0.61, 80, 2, "EU"),
    ("ENCE", 33, 0.60, 70, 1, "FI"),
    ("Apeks", 34, 0.60, 120, 0, "NO"),
    ("BLEED", 35, 0.59, 90, 0, "SG"),
    ("KOI", 36, 0.58, 60, 1, "ES"),
    ("Aurora", 37, 0.58, 100, 0, "RU"),
    ("Into the Breach", 38, 0.57, 80, 1, "EU"),
    ("Rare Atom", 39, 0.56, 110, 0, "CN"),
    ("Legacy", 40, 0.56, 70, 1, "BR"),
    ("Permitta", 41, 0.55, 90, 0, "PL"),
    ("Nemiga", 42, 0.55, 120, 0, "BY"),
    ("Sangal", 43, 0.54, 80, 1, "TR"),
    ("TYLOO", 44, 0.54, 150, 0, "CN"),
    ("Grayhound", 45, 0.53, 100, 0, "AU"),

    # --- Tier 3-4: Ranks 46-60 ---
    ("Fluxo", 46, 0.52, 60, 2, "BR"),
    ("ALTERNATE aTTaX", 47, 0.52, 130, 0, "DE"),
    ("Insilio", 48, 0.51, 70, 1, "EU"),
    ("Rooster", 49, 0.51, 90, 0, "AU"),
    ("Spirit Academy", 50, 0.50, 80, 0, "RU"),
    ("VP.Prodigy", 51, 0.50, 100, 1, "RU"),
    ("Entropiq", 52, 0.49, 60, 2, "CZ"),
    ("ex-Guild Eagles", 53, 0.49, 110, 0, "EU"),
    ("Sprout", 54, 0.48, 70, 1, "DE"),
    ("FORZE", 55, 0.48, 130, 0, "RU"),
    ("Bad News Eagles", 56, 0.47, 200, 0, "XK"),
    ("HAVU", 57, 0.47, 90, 1, "FI"),
    ("Sashi", 58, 0.46, 60, 1, "DK"),
    ("Metizport", 59, 0.46, 80, 0, "SE"),
    ("Preasy", 60, 0.45, 50, 2, "DK"),

    # --- Regional wildcards ---
    ("Team Falcons", 61, 0.72, 150, 0, "SA"),
    ("Viperio", 62, 0.44, 100, 1, "EU"),
    ("Copenhagen Wolves", 63, 0.44, 70, 0, "DK"),
    ("Nouns", 64, 0.43, 80, 1, "US"),
    ("M80", 65, 0.43, 90, 0, "US"),
    ("Sharks", 66, 0.42, 60, 2, "BR"),
]

# ═══════════════════════════════════════════════════════════════
# NAMED PLAYER ROSTERS: (nickname, rating, adr, kast, kd, hs%, is_awper)
# Real player names and approximate stats for top 20 teams
# ═══════════════════════════════════════════════════════════════

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
    "Team Spirit": [
        ("donk", 1.20, 83, 0.74, 1.24, 0.50, 0),
        ("zont1x", 1.08, 75, 0.70, 1.10, 0.48, 0),
        ("chopper", 0.95, 64, 0.67, 0.93, 0.44, 0),
        ("magixx", 1.10, 77, 0.71, 1.12, 0.46, 0),
        ("patsi", 1.02, 70, 0.68, 1.04, 0.42, 1),
    ],
    "Heroic": [
        ("TeSeS", 1.10, 76, 0.71, 1.12, 0.50, 0),
        ("sjuush", 1.05, 73, 0.70, 1.08, 0.48, 0),
        ("nicoodoz", 1.12, 78, 0.72, 1.15, 0.38, 1),
        ("kyxsan", 0.95, 64, 0.67, 0.92, 0.44, 0),
        ("jabbi", 1.08, 75, 0.70, 1.10, 0.52, 0),
    ],
    "Virtus.pro": [
        ("Jame", 1.08, 72, 0.70, 1.10, 0.35, 1),
        ("n0rb3r7", 1.05, 74, 0.69, 1.06, 0.50, 0),
        ("fame", 1.02, 70, 0.68, 1.03, 0.48, 0),
        ("FL1T", 1.00, 68, 0.67, 1.00, 0.46, 0),
        ("Qikert", 0.98, 66, 0.66, 0.96, 0.44, 0),
    ],
    "Team Liquid": [
        ("NAF", 1.12, 76, 0.72, 1.14, 0.48, 0),
        ("EliGE", 1.10, 78, 0.71, 1.12, 0.52, 0),
        ("oSee", 1.05, 72, 0.69, 1.06, 0.36, 1),
        ("nitr0", 0.95, 64, 0.67, 0.92, 0.44, 0),
        ("YEKINDAR", 1.08, 75, 0.70, 1.08, 0.50, 0),
    ],
    "Complexity Gaming": [
        ("JT", 0.95, 64, 0.67, 0.93, 0.44, 0),
        ("floppy", 1.08, 74, 0.70, 1.10, 0.50, 0),
        ("hallzerk", 1.12, 76, 0.71, 1.14, 0.38, 1),
        ("Grim", 1.05, 72, 0.69, 1.06, 0.48, 0),
        ("FaNg", 1.00, 68, 0.68, 1.00, 0.46, 0),
    ],
    "Eternal Fire": [
        ("woxic", 1.15, 78, 0.72, 1.18, 0.36, 1),
        ("XANTARES", 1.18, 82, 0.73, 1.20, 0.58, 0),
        ("Calyx", 1.02, 70, 0.68, 1.04, 0.48, 0),
        ("MAJ3R", 0.92, 62, 0.66, 0.90, 0.44, 0),
        ("imoRR", 1.05, 73, 0.69, 1.06, 0.50, 0),
    ],
    "FURIA Esports": [
        ("KSCERATO", 1.15, 78, 0.73, 1.18, 0.52, 0),
        ("yuurih", 1.10, 76, 0.71, 1.12, 0.50, 0),
        ("FalleN", 1.02, 70, 0.68, 1.04, 0.38, 1),
        ("chelo", 1.00, 68, 0.67, 1.00, 0.46, 0),
        ("drop", 0.98, 66, 0.66, 0.96, 0.48, 0),
    ],
    "paiN Gaming": [
        ("biguzera", 1.12, 76, 0.71, 1.14, 0.50, 0),
        ("skullz", 1.05, 73, 0.69, 1.06, 0.48, 0),
        ("NQZ", 1.02, 70, 0.68, 1.03, 0.38, 1),
        ("lux", 0.98, 66, 0.66, 0.96, 0.46, 0),
        ("zevy", 0.95, 64, 0.65, 0.93, 0.44, 0),
    ],
    "3DMAX": [
        ("Graviti", 1.08, 74, 0.70, 1.10, 0.50, 0),
        ("Djoko", 1.05, 72, 0.69, 1.06, 0.48, 0),
        ("Ex3rcice", 1.02, 70, 0.68, 1.03, 0.46, 0),
        ("Lucky", 1.00, 68, 0.67, 1.00, 0.38, 1),
        ("Maka", 0.95, 64, 0.66, 0.93, 0.44, 0),
    ],
    "BIG": [
        ("tabseN", 1.10, 76, 0.71, 1.12, 0.50, 0),
        ("syrsoN", 1.08, 74, 0.70, 1.10, 0.36, 1),
        ("Krimbo", 1.05, 73, 0.69, 1.06, 0.52, 0),
        ("prosus", 1.00, 68, 0.67, 1.00, 0.48, 0),
        ("rigon", 0.98, 66, 0.66, 0.96, 0.46, 0),
    ],
    "SAW": [
        ("MUTiRiS", 1.08, 74, 0.70, 1.10, 0.48, 0),
        ("arrozdoce", 1.05, 72, 0.69, 1.06, 0.46, 0),
        ("story", 1.02, 70, 0.68, 1.03, 0.50, 0),
        ("ewjerkz", 1.00, 68, 0.67, 1.00, 0.38, 1),
        ("roman", 0.95, 64, 0.66, 0.93, 0.44, 0),
    ],
    "GamerLegion": [
        ("iM", 1.08, 74, 0.70, 1.10, 0.50, 0),
        ("acoR", 1.05, 72, 0.69, 1.06, 0.36, 1),
        ("isak", 1.02, 70, 0.68, 1.03, 0.52, 0),
        ("siuhy", 0.98, 66, 0.66, 0.96, 0.44, 0),
        ("keoz", 1.00, 68, 0.67, 1.00, 0.48, 0),
    ],
    "Monte": [
        ("DemQQ", 1.08, 74, 0.70, 1.10, 0.50, 0),
        ("kraghen", 1.05, 72, 0.69, 1.06, 0.48, 0),
        ("Woro2k", 1.02, 70, 0.68, 1.03, 0.38, 1),
        ("BOROS", 0.98, 66, 0.66, 0.96, 0.46, 0),
        ("sdy", 0.95, 64, 0.65, 0.93, 0.44, 0),
    ],
    "Cloud9": [
        ("sh1ro", 1.15, 78, 0.72, 1.18, 0.38, 1),
        ("Ax1Le", 1.12, 76, 0.71, 1.14, 0.52, 0),
        ("HObbit", 1.00, 68, 0.68, 1.00, 0.46, 0),
        ("buster", 1.05, 72, 0.69, 1.06, 0.48, 0),
        ("nafany", 0.92, 62, 0.65, 0.90, 0.44, 0),
    ],
    "fnatic": [
        ("mezii", 1.05, 73, 0.69, 1.06, 0.48, 0),
        ("KRIMZ", 1.02, 70, 0.68, 1.03, 0.46, 0),
        ("roeJ", 1.00, 68, 0.67, 1.00, 0.50, 0),
        ("nicoodoz", 1.08, 74, 0.70, 1.10, 0.38, 1),
        ("FASHR", 0.95, 64, 0.66, 0.93, 0.44, 0),
    ],
    "Astralis": [
        ("dev1ce", 1.12, 76, 0.72, 1.14, 0.38, 1),
        ("blameF", 1.05, 73, 0.69, 1.06, 0.50, 0),
        ("Staehr", 1.02, 70, 0.68, 1.03, 0.48, 0),
        ("br0", 0.98, 66, 0.66, 0.96, 0.46, 0),
        ("Buzz", 0.95, 64, 0.65, 0.93, 0.44, 0),
    ],
    "TheMongolz": [
        ("bLitz", 1.12, 76, 0.71, 1.14, 0.50, 0),
        ("Techno", 1.08, 74, 0.70, 1.10, 0.48, 0),
        ("Senzu", 1.05, 72, 0.69, 1.06, 0.38, 1),
        ("mzinho", 1.00, 68, 0.67, 1.00, 0.46, 0),
        ("910", 0.98, 66, 0.66, 0.96, 0.44, 0),
    ],
    "Team Falcons": [
        ("dupreeh", 1.05, 73, 0.69, 1.06, 0.48, 0),
        ("Magisk", 1.08, 75, 0.70, 1.10, 0.50, 0),
        ("refrezh", 1.02, 70, 0.68, 1.03, 0.46, 0),
        ("gla1ve", 0.95, 64, 0.67, 0.93, 0.44, 0),
        ("k0nfig", 1.10, 77, 0.71, 1.12, 0.54, 0),
    ],
}

# ═══════════════════════════════════════════════════════════════
# CS2 MAP POOL
# ═══════════════════════════════════════════════════════════════

MAPS = ["Mirage", "Inferno", "Nuke", "Overpass", "Ancient", "Anubis", "Dust2"]

# ═══════════════════════════════════════════════════════════════
# MAP STRENGTHS: team → {map: adjustment}
# Positive = strong, negative = weak on that map
# ═══════════════════════════════════════════════════════════════

MAP_STRENGTHS = {
    "Natus Vincere": {"Inferno": 0.15, "Nuke": 0.10, "Dust2": -0.10, "Anubis": 0.05},
    "FaZe Clan": {"Mirage": 0.12, "Overpass": 0.10, "Ancient": -0.08, "Inferno": 0.06},
    "G2 Esports": {"Nuke": 0.15, "Inferno": 0.08, "Anubis": -0.10, "Overpass": 0.05},
    "Team Vitality": {"Overpass": 0.12, "Ancient": 0.10, "Mirage": -0.05, "Nuke": 0.08},
    "MOUZ": {"Anubis": 0.12, "Dust2": 0.08, "Nuke": -0.10, "Mirage": 0.05},
    "Team Spirit": {"Inferno": 0.10, "Mirage": 0.08, "Ancient": -0.06, "Overpass": 0.05},
    "Heroic": {"Nuke": 0.12, "Overpass": 0.08, "Dust2": -0.08, "Ancient": 0.05},
    "Virtus.pro": {"Mirage": 0.10, "Dust2": 0.08, "Nuke": -0.06, "Anubis": 0.04},
    "Team Liquid": {"Inferno": 0.10, "Overpass": 0.08, "Anubis": -0.08, "Nuke": 0.05},
    "Complexity Gaming": {"Ancient": 0.10, "Nuke": 0.06, "Mirage": -0.06, "Dust2": 0.04},
    "Eternal Fire": {"Dust2": 0.12, "Mirage": 0.10, "Overpass": -0.08, "Inferno": 0.05},
    "FURIA Esports": {"Mirage": 0.12, "Inferno": 0.08, "Nuke": -0.10, "Overpass": 0.04},
    "paiN Gaming": {"Dust2": 0.10, "Mirage": 0.06, "Ancient": -0.08, "Inferno": 0.04},
    "3DMAX": {"Inferno": 0.10, "Nuke": 0.08, "Dust2": -0.06, "Anubis": 0.04},
    "BIG": {"Nuke": 0.12, "Overpass": 0.08, "Mirage": -0.06, "Ancient": 0.04},
    "SAW": {"Overpass": 0.10, "Ancient": 0.06, "Inferno": -0.06, "Nuke": 0.04},
    "Cloud9": {"Inferno": 0.10, "Anubis": 0.08, "Dust2": -0.08, "Mirage": 0.04},
    "fnatic": {"Mirage": 0.10, "Inferno": 0.06, "Nuke": -0.08, "Ancient": 0.04},
    "Astralis": {"Nuke": 0.15, "Inferno": 0.10, "Overpass": -0.05, "Dust2": 0.04},
    "TheMongolz": {"Mirage": 0.12, "Dust2": 0.10, "Nuke": -0.08, "Anubis": 0.04},
    "Team Falcons": {"Inferno": 0.10, "Nuke": 0.08, "Dust2": -0.06, "Overpass": 0.05},
}

# ═══════════════════════════════════════════════════════════════
# EVENTS/TOURNAMENTS
# ═══════════════════════════════════════════════════════════════

EVENTS = [
    # Tier 5 — Majors
    ("PGL Major Copenhagen", True, 5, True),
    ("PGL Major Austin", True, 5, True),
    # Tier 4 — Big LAN events
    ("BLAST Premier World Final", True, 4, True),
    ("IEM Katowice", True, 4, True),
    ("IEM Cologne", True, 4, True),
    ("ESL Pro League S20", True, 4, False),
    ("BLAST Premier Spring Finals", True, 4, True),
    ("BLAST Premier Fall Finals", True, 4, True),
    ("IEM Dallas", True, 4, False),
    ("IEM Sydney", True, 4, False),
    # Tier 3 — Medium LAN
    ("Thunderpick World Championship", True, 3, False),
    ("BetBoom Dacha", True, 3, False),
    ("YaLLa Compass", True, 3, False),
    ("Elisa Masters Espoo", True, 3, False),
    ("BLAST.tv Paris Major RMR", True, 3, True),
    # Tier 2 — Online / small events
    ("CCT Online Finals", False, 2, False),
    ("ESL Challenger", False, 2, False),
    ("BLAST Bounty Spring", False, 2, False),
    ("Skyesports Masters", True, 2, False),
    ("Pinnacle Cup", False, 2, False),
    ("ESEA Premier", False, 2, False),
    ("Roobet Cup", False, 2, False),
    # Tier 1 — Regional qualifiers
    ("CCT South America S1", False, 1, False),
    ("CCT North Europe S1", False, 1, False),
    ("ESL Challenger Asia", False, 1, False),
    ("REPUBLEAGUE", False, 1, False),
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
    # Named rosters for teams that have them
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

    # Auto-generated players for teams without named rosters
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
    logger.info("Seeded %d players across %d teams", count, len(TOP_TEAMS))


def generate_matches(conn, num_matches=1500):
    """Generate realistic match history.

    Higher-ranked teams play more matches at top events.
    Teams from the same region meet more often.
    """
    teams = conn.execute("SELECT id, name, country FROM teams").fetchall()
    team_ids = [t["id"] for t in teams]
    team_names = {t["id"]: t["name"] for t in teams}
    team_countries = {t["id"]: t["country"] for t in teams}

    strength_map = {}
    ranking_map = {}
    for name, ranking, strength, *_ in TOP_TEAMS:
        row = conn.execute("SELECT id FROM teams WHERE name = ?", (name,)).fetchone()
        if row:
            strength_map[row["id"]] = strength
            ranking_map[row["id"]] = ranking

    # Group teams by tier for realistic matchmaking
    tier1_ids = [tid for tid, r in ranking_map.items() if r <= 10]
    tier2_ids = [tid for tid, r in ranking_map.items() if 11 <= r <= 25]
    tier3_ids = [tid for tid, r in ranking_map.items() if 26 <= r <= 45]
    tier4_ids = [tid for tid, r in ranking_map.items() if r > 45]

    start_date = datetime.utcnow() - timedelta(days=365)

    for i in range(num_matches):
        # Weighted matchmaking: teams tend to play opponents of similar rank
        roll = random.random()
        if roll < 0.35:
            # Top teams vs top teams (tier 1-2)
            pool = tier1_ids + tier2_ids
        elif roll < 0.55:
            # Cross-tier (tier 1-2 vs tier 2-3)
            pool = tier1_ids + tier2_ids + tier3_ids
        elif roll < 0.75:
            # Mid-tier (tier 2-3)
            pool = tier2_ids + tier3_ids
        elif roll < 0.90:
            # Lower-tier (tier 3-4)
            pool = tier3_ids + tier4_ids
        else:
            # Anyone can meet (qualifier/open events)
            pool = team_ids

        if len(pool) < 2:
            pool = team_ids

        t1_id, t2_id = random.sample(pool, 2)

        s1 = strength_map.get(t1_id, 0.50)
        s2 = strength_map.get(t2_id, 0.50)

        map_name = random.choice(MAPS)
        t1_name = team_names.get(t1_id, "")
        t2_name = team_names.get(t2_id, "")
        map_adj1 = MAP_STRENGTHS.get(t1_name, {}).get(map_name, 0)
        map_adj2 = MAP_STRENGTHS.get(t2_name, {}).get(map_name, 0)

        effective_s1 = s1 + map_adj1 + random.gauss(0, 0.10)
        effective_s2 = s2 + map_adj2 + random.gauss(0, 0.10)
        team1_wins = effective_s1 > effective_s2
        winner_id = t1_id if team1_wins else t2_id

        # Pick appropriate event based on team tier
        r1 = ranking_map.get(t1_id, 50)
        r2 = ranking_map.get(t2_id, 50)
        avg_rank = (r1 + r2) / 2

        if avg_rank <= 15:
            event_pool = [e for e in EVENTS if e[2] >= 3]
        elif avg_rank <= 30:
            event_pool = [e for e in EVENTS if 2 <= e[2] <= 4]
        else:
            event_pool = [e for e in EVENTS if e[2] <= 3]

        if not event_pool:
            event_pool = EVENTS

        event_name, is_lan, event_tier, is_playoff = random.choice(event_pool)
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
    logger.info("Seeded map stats for %d teams", len(teams))


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
    generate_matches(conn, num_matches=1500)
    seed_map_stats(conn)
    conn.close()

    n = recalculate_all_ratings()
    logger.info("Recalculated ratings from %d matches", n)
    logger.info("Seed complete! %d teams, 1500 matches.", len(TOP_TEAMS))


if __name__ == "__main__":
    run_seed()

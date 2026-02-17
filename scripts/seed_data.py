"""
Seed database with realistic CS2 team data, players, and match history.
Includes player ratings, AWPer roles, roster stability, map strengths.
60+ teams across all major regions with named rosters for top 30.

Data sourced from HLTV rankings as of February 2026.
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
# Rankings based on HLTV World Ranking — February 16, 2026
# ═══════════════════════════════════════════════════════════════

TOP_TEAMS = [
    # --- Tier 1: Top 10 ---
    ("Team Vitality", 1, 0.95, 200, 1, "FR"),         # Won both 2025 Majors, IEM Krakow 2026
    ("FURIA Esports", 2, 0.91, 300, 2, "BR"),          # International roster now (YEKINDAR, molodoy)
    ("Team Falcons", 3, 0.88, 400, 1, "SA"),            # NiKo + m0NESY superteam
    ("MOUZ", 4, 0.87, 180, 1, "EU"),                    # Spinx replaced siuhy
    ("Team Spirit", 5, 0.86, 90, 2, "RU"),              # Rebuilt: chopper/zweih out, magixx IGL
    ("PARIVISION", 6, 0.83, 180, 2, "RU"),              # Ex-VP Jame + former Spirit zweih
    ("FaZe Clan", 7, 0.82, 150, 3, "EU"),               # Twistzz in, rain/ropz/EliGE out
    ("Natus Vincere", 8, 0.81, 220, 1, "UA"),           # No s1mple since 2023; makazze from academy
    ("G2 Esports", 9, 0.80, 120, 4, "EU"),              # Completely new roster, NiKo/m0NESY gone
    ("The MongolZ", 10, 0.79, 250, 1, "MN"),            # cobrazera replaced Senzu

    # --- Tier 2: 11-20 ---
    ("Aurora", 11, 0.78, 300, 1, "RS"),                  # Former Eternal Fire core (XANTARES, woxic)
    ("Astralis", 12, 0.75, 60, 3, "DK"),                # First intl signings: phzy, ryu; dev1ce left
    ("3DMAX", 13, 0.74, 200, 0, "FR"),                   # Stable French roster
    ("FUT Esports", 14, 0.73, 150, 1, "TR"),             # Intl roster (ex-NaVi Junior core)
    ("Team Liquid", 15, 0.72, 200, 3, "US"),             # siuhy IGL, NertZ, ultimate joined
    ("B8", 16, 0.70, 180, 0, "UA"),                      # Ukrainian roster
    ("Passion UA", 17, 0.70, 120, 2, "UA"),              # Zinchenko org; JT, Grim, Senzu loan
    ("paiN Gaming", 18, 0.69, 100, 2, "BR"),             # All-Brazilian, vsm + piriajr joined
    ("NRG Esports", 19, 0.68, 200, 1, "US"),             # nitr0 IGL, oSee AWP
    ("GamerLegion", 20, 0.67, 120, 2, "EU"),             # Snax IGL return, REZ joined

    # --- Tier 2-3: 21-30 ---
    ("Ninjas in Pyjamas", 21, 0.66, 150, 2, "EU"),      # Snappi IGL, sjuush from HEROIC
    ("HEROIC", 22, 0.65, 90, 4, "NO"),                   # Completely rebuilt after Falcons exodus
    ("Imperial Esports", 23, 0.64, 130, 1, "BR"),        # Brazilian roster
    ("M80", 24, 0.63, 180, 1, "US"),                     # North American team
    ("Legacy", 25, 0.62, 200, 0, "BR"),                  # arT IGL, stable BR roster
    ("BC.Game Esports", 26, 0.66, 200, 0, "PT"),         # s1mple + electroNic + ex-SAW trio
    ("Gentle Mates", 27, 0.60, 150, 1, "FR"),            # French roster
    ("MIBR", 28, 0.59, 100, 2, "BR"),                    # Brazilian org
    ("FlyQuest", 29, 0.58, 120, 1, "AU"),                # jks + INS, Australian
    ("TYLOO", 30, 0.57, 200, 0, "CN"),                   # Chinese roster

    # --- Tier 3: 31-45 ---
    ("100 Thieves", 31, 0.65, 60, 5, "AU"),              # New: rain IGL, dev1ce AWP, gla1ve coach
    ("BIG", 32, 0.61, 100, 2, "DE"),                     # blameF from fnatic, faveN joined
    ("fnatic", 33, 0.60, 130, 2, "EU"),                  # Lost blameF, added maden
    ("ENCE", 34, 0.59, 150, 1, "FI"),                    # Finnish core
    ("Apeks", 35, 0.58, 120, 0, "NO"),                   # Norwegian org
    ("BLEED", 36, 0.57, 90, 0, "SG"),                    # Southeast Asian team
    ("KOI", 37, 0.56, 60, 1, "ES"),                      # Spanish org
    ("Into the Breach", 38, 0.55, 80, 1, "EU"),          # European mix
    ("Rare Atom", 39, 0.55, 110, 0, "CN"),               # Chinese team
    ("Lynn Vision", 40, 0.54, 120, 0, "CN"),             # Chinese team
    ("Permitta", 41, 0.53, 90, 0, "PL"),                 # Polish team
    ("Sprout", 42, 0.52, 70, 1, "DE"),                   # German team
    ("HAVU", 43, 0.52, 90, 1, "FI"),                     # Finnish team
    ("Sangal", 44, 0.51, 80, 1, "TR"),                   # Turkish team
    ("Grayhound", 45, 0.51, 100, 0, "AU"),               # Australian team

    # --- Tier 3-4: 46-60 ---
    ("Fluxo", 46, 0.50, 60, 2, "BR"),
    ("ALTERNATE aTTaX", 47, 0.50, 130, 0, "DE"),
    ("Spirit Academy", 48, 0.49, 80, 1, "RU"),
    ("FORZE", 49, 0.49, 130, 0, "RU"),
    ("Bad News Eagles", 50, 0.48, 200, 0, "XK"),
    ("Sashi", 51, 0.48, 60, 1, "DK"),
    ("Metizport", 52, 0.47, 80, 0, "SE"),
    ("Preasy", 53, 0.47, 50, 2, "DK"),
    ("Wildcard", 54, 0.46, 80, 0, "AU"),
    ("Rooster", 55, 0.46, 90, 0, "AU"),
    ("Sharks", 56, 0.45, 60, 2, "BR"),
    ("Nouns", 57, 0.45, 80, 1, "US"),
    ("Insilio", 58, 0.44, 70, 1, "EU"),
    ("Nemiga", 59, 0.44, 120, 0, "BY"),
    ("Entropiq", 60, 0.43, 60, 2, "CZ"),
]

# ═══════════════════════════════════════════════════════════════
# NAMED PLAYER ROSTERS: (nickname, rating, adr, kast, kd, hs%, is_awper)
# Real player names and approximate stats — February 2026
# ═══════════════════════════════════════════════════════════════

TEAM_PLAYERS = {
    "Team Vitality": [
        ("ZywOo", 1.28, 86, 0.76, 1.32, 0.42, 1),
        ("ropz", 1.15, 78, 0.74, 1.18, 0.55, 0),
        ("flameZ", 1.10, 76, 0.71, 1.12, 0.50, 0),
        ("mezii", 1.02, 70, 0.69, 1.00, 0.47, 0),
        ("apEX", 0.95, 65, 0.67, 0.92, 0.45, 0),
    ],
    "FURIA Esports": [
        ("KSCERATO", 1.15, 78, 0.73, 1.18, 0.52, 0),
        ("yuurih", 1.10, 76, 0.71, 1.12, 0.50, 0),
        ("YEKINDAR", 1.08, 75, 0.70, 1.08, 0.50, 0),
        ("molodoy", 1.05, 72, 0.69, 1.06, 0.38, 1),
        ("FalleN", 1.00, 68, 0.68, 1.00, 0.40, 0),
    ],
    "Team Falcons": [
        ("NiKo", 1.22, 82, 0.74, 1.25, 0.56, 0),
        ("m0NESY", 1.25, 85, 0.73, 1.28, 0.40, 1),
        ("TeSeS", 1.08, 75, 0.71, 1.10, 0.50, 0),
        ("kyxsan", 0.95, 64, 0.67, 0.92, 0.44, 0),
        ("kyousuke", 1.05, 73, 0.69, 1.06, 0.48, 0),
    ],
    "MOUZ": [
        ("torzsi", 1.12, 77, 0.72, 1.15, 0.40, 1),
        ("Brollan", 1.10, 76, 0.71, 1.12, 0.53, 0),
        ("Spinx", 1.08, 74, 0.70, 1.08, 0.49, 0),
        ("Jimpphat", 1.05, 73, 0.69, 1.06, 0.50, 0),
        ("xertioN", 1.02, 71, 0.68, 1.03, 0.52, 0),
    ],
    "Team Spirit": [
        ("donk", 1.20, 83, 0.74, 1.24, 0.50, 0),
        ("sh1ro", 1.15, 78, 0.72, 1.18, 0.38, 1),
        ("magixx", 1.05, 72, 0.69, 1.06, 0.46, 0),
        ("zont1x", 1.08, 75, 0.70, 1.10, 0.48, 0),
        ("tN1R", 0.98, 66, 0.66, 0.96, 0.44, 0),
    ],
    "PARIVISION": [
        ("Jame", 1.08, 72, 0.70, 1.10, 0.35, 1),
        ("zweih", 1.05, 73, 0.69, 1.06, 0.48, 0),
        ("BELCHONOKK", 1.02, 70, 0.68, 1.03, 0.46, 0),
        ("xiELO", 1.00, 68, 0.67, 1.00, 0.50, 0),
        ("nota", 0.98, 66, 0.66, 0.96, 0.44, 0),
    ],
    "FaZe Clan": [
        ("broky", 1.12, 78, 0.72, 1.15, 0.38, 1),
        ("Twistzz", 1.12, 77, 0.72, 1.14, 0.54, 0),
        ("frozen", 1.08, 75, 0.70, 1.10, 0.52, 0),
        ("karrigan", 0.92, 60, 0.66, 0.88, 0.43, 0),
        ("jcobbb", 1.00, 68, 0.68, 1.00, 0.48, 0),
    ],
    "Natus Vincere": [
        ("b1t", 1.12, 78, 0.72, 1.15, 0.52, 0),
        ("w0nderful", 1.10, 76, 0.71, 1.12, 0.38, 1),
        ("iM", 1.05, 72, 0.69, 1.05, 0.48, 0),
        ("Aleksib", 0.98, 65, 0.68, 0.95, 0.45, 0),
        ("makazze", 1.00, 68, 0.67, 1.00, 0.46, 0),
    ],
    "G2 Esports": [
        ("SunPayus", 1.08, 74, 0.70, 1.10, 0.38, 1),
        ("HeavyGod", 1.05, 73, 0.69, 1.06, 0.50, 0),
        ("huNter-", 1.05, 72, 0.69, 1.06, 0.48, 0),
        ("malbsMd", 1.00, 68, 0.67, 1.00, 0.46, 0),
        ("MATYS", 0.98, 66, 0.66, 0.96, 0.50, 0),
    ],
    "The MongolZ": [
        ("bLitz", 1.12, 76, 0.71, 1.14, 0.50, 0),
        ("Techno4K", 1.08, 74, 0.70, 1.10, 0.48, 0),
        ("mzinho", 1.05, 72, 0.69, 1.06, 0.46, 0),
        ("910", 1.00, 68, 0.67, 1.00, 0.44, 0),
        ("cobrazera", 1.02, 70, 0.68, 1.03, 0.42, 0),
    ],
    "Aurora": [
        ("XANTARES", 1.18, 82, 0.73, 1.20, 0.58, 0),
        ("woxic", 1.12, 77, 0.71, 1.14, 0.36, 1),
        ("Wicadia", 1.05, 73, 0.69, 1.06, 0.50, 0),
        ("MAJ3R", 0.92, 62, 0.66, 0.90, 0.44, 0),
        ("soulfly", 1.00, 68, 0.67, 1.00, 0.48, 0),
    ],
    "Astralis": [
        ("jabbi", 1.08, 75, 0.70, 1.10, 0.52, 0),
        ("Staehr", 1.05, 73, 0.69, 1.06, 0.48, 0),
        ("phzy", 1.05, 72, 0.69, 1.06, 0.38, 1),
        ("HooXi", 0.90, 58, 0.65, 0.86, 0.42, 0),
        ("ryu", 1.00, 68, 0.67, 1.00, 0.46, 0),
    ],
    "3DMAX": [
        ("Graviti", 1.08, 74, 0.70, 1.10, 0.50, 0),
        ("Ex3rcice", 1.05, 72, 0.69, 1.06, 0.46, 0),
        ("bodyy", 1.02, 70, 0.68, 1.03, 0.48, 0),
        ("Lucky", 1.00, 68, 0.67, 1.00, 0.38, 1),
        ("Maka", 0.95, 64, 0.66, 0.93, 0.44, 0),
    ],
    "FUT Esports": [
        ("dem0n", 1.05, 73, 0.69, 1.06, 0.48, 0),
        ("lauNX", 1.02, 70, 0.68, 1.03, 0.46, 0),
        ("Krabeni", 1.00, 68, 0.67, 1.00, 0.50, 0),
        ("cmtry", 0.98, 66, 0.66, 0.96, 0.44, 0),
        ("dziugss", 0.95, 64, 0.65, 0.93, 0.42, 0),
    ],
    "Team Liquid": [
        ("EliGE", 1.10, 78, 0.71, 1.12, 0.52, 0),
        ("NAF", 1.08, 75, 0.70, 1.10, 0.48, 0),
        ("NertZ", 1.05, 73, 0.69, 1.06, 0.50, 0),
        ("siuhy", 0.95, 64, 0.67, 0.92, 0.44, 0),
        ("ultimate", 1.00, 68, 0.67, 1.00, 0.46, 0),
    ],
    "B8": [
        ("alex666", 1.05, 73, 0.69, 1.06, 0.48, 0),
        ("npl", 1.02, 70, 0.68, 1.03, 0.46, 0),
        ("kensizor", 1.00, 68, 0.67, 1.00, 0.38, 1),
        ("esenthial", 0.98, 66, 0.66, 0.96, 0.44, 0),
        ("s1zzi", 0.95, 64, 0.65, 0.93, 0.42, 0),
    ],
    "Passion UA": [
        ("JT", 0.95, 64, 0.67, 0.93, 0.44, 0),
        ("Grim", 1.05, 72, 0.69, 1.06, 0.48, 0),
        ("nicx", 1.02, 70, 0.68, 1.03, 0.46, 0),
        ("Senzu", 1.05, 72, 0.69, 1.06, 0.38, 1),
        ("Kvem", 0.98, 66, 0.66, 0.96, 0.44, 0),
    ],
    "paiN Gaming": [
        ("biguzera", 1.10, 76, 0.71, 1.12, 0.50, 0),
        ("skullz", 1.05, 73, 0.69, 1.06, 0.48, 0),
        ("NQZ", 1.02, 70, 0.68, 1.03, 0.38, 1),
        ("vsm", 0.98, 66, 0.66, 0.96, 0.46, 0),
        ("piriajr", 0.95, 64, 0.65, 0.93, 0.44, 0),
    ],
    "NRG Esports": [
        ("oSee", 1.05, 72, 0.69, 1.06, 0.36, 1),
        ("Sonic", 1.02, 70, 0.68, 1.03, 0.50, 0),
        ("br0", 1.00, 68, 0.67, 1.00, 0.48, 0),
        ("nitr0", 0.95, 64, 0.67, 0.92, 0.44, 0),
        ("Jeorge", 0.98, 66, 0.66, 0.96, 0.46, 0),
    ],
    "GamerLegion": [
        ("REZ", 1.05, 73, 0.69, 1.06, 0.52, 0),
        ("Tauson", 1.02, 70, 0.68, 1.03, 0.48, 0),
        ("Snax", 0.95, 64, 0.67, 0.93, 0.44, 0),
        ("hypex", 1.00, 68, 0.67, 1.00, 0.46, 0),
        ("PR", 0.98, 66, 0.66, 0.96, 0.50, 0),
    ],
    "Ninjas in Pyjamas": [
        ("sjuush", 1.05, 73, 0.70, 1.08, 0.48, 0),
        ("r1nkle", 1.02, 70, 0.68, 1.03, 0.46, 0),
        ("xKacpersky", 1.00, 68, 0.67, 1.00, 0.38, 1),
        ("Snappi", 0.92, 62, 0.66, 0.90, 0.44, 0),
        ("cairne", 0.98, 66, 0.66, 0.96, 0.42, 0),
    ],
    "HEROIC": [
        ("xfl0ud", 1.05, 73, 0.69, 1.06, 0.50, 0),
        ("nilo", 1.02, 70, 0.68, 1.03, 0.38, 1),
        ("susp", 1.00, 68, 0.67, 1.00, 0.48, 0),
        ("Chr1zN", 0.98, 66, 0.66, 0.96, 0.46, 0),
        ("alkarenn", 0.95, 64, 0.65, 0.93, 0.44, 0),
    ],
    "Imperial Esports": [
        ("chelo", 1.05, 73, 0.69, 1.06, 0.48, 0),
        ("VINI", 1.02, 70, 0.68, 1.03, 0.46, 0),
        ("skullz", 1.00, 68, 0.67, 1.00, 0.50, 0),
        ("noway", 0.98, 66, 0.66, 0.96, 0.44, 0),
        ("try", 0.95, 64, 0.65, 0.93, 0.42, 0),
    ],
    "M80": [
        ("slaxz-", 1.05, 73, 0.69, 1.06, 0.50, 0),
        ("Swisher", 1.02, 70, 0.68, 1.03, 0.48, 0),
        ("s1n", 1.00, 68, 0.67, 1.00, 0.38, 1),
        ("JBa", 0.98, 66, 0.66, 0.96, 0.46, 0),
        ("Lake", 0.95, 64, 0.65, 0.93, 0.44, 0),
    ],
    "Legacy": [
        ("arT", 1.02, 71, 0.68, 1.03, 0.46, 0),
        ("dumau", 1.05, 73, 0.69, 1.06, 0.48, 0),
        ("latto", 1.00, 68, 0.67, 1.00, 0.38, 1),
        ("n1ssim", 0.98, 66, 0.66, 0.96, 0.44, 0),
        ("saadzin", 0.95, 64, 0.65, 0.93, 0.42, 0),
    ],
    "BC.Game Esports": [
        ("s1mple", 1.18, 80, 0.73, 1.20, 0.42, 1),
        ("electroNic", 1.10, 76, 0.71, 1.12, 0.50, 0),
        ("MUTiRiS", 1.05, 73, 0.69, 1.06, 0.48, 0),
        ("aragornN", 0.98, 66, 0.66, 0.96, 0.44, 0),
        ("krazy", 0.95, 64, 0.65, 0.93, 0.42, 0),
    ],
    "FlyQuest": [
        ("jks", 1.08, 75, 0.70, 1.10, 0.50, 0),
        ("INS", 1.05, 72, 0.69, 1.06, 0.36, 1),
        ("Vexite", 1.00, 68, 0.67, 1.00, 0.48, 0),
        ("nettik", 0.98, 66, 0.66, 0.96, 0.46, 0),
        ("story", 0.95, 64, 0.65, 0.93, 0.44, 0),
    ],
    "TYLOO": [
        ("JamYoung", 1.02, 70, 0.68, 1.03, 0.48, 0),
        ("Jee", 1.00, 68, 0.67, 1.00, 0.46, 0),
        ("Mercury", 0.98, 66, 0.66, 0.96, 0.38, 1),
        ("Moseyuh", 0.95, 64, 0.65, 0.93, 0.44, 0),
        ("Zero", 0.92, 62, 0.64, 0.90, 0.42, 0),
    ],
    "100 Thieves": [
        ("dev1ce", 1.12, 76, 0.72, 1.14, 0.38, 1),
        ("rain", 1.02, 70, 0.68, 1.03, 0.47, 0),
        ("Ag1l", 1.00, 68, 0.67, 1.00, 0.50, 0),
        ("sirah", 0.98, 66, 0.66, 0.96, 0.46, 0),
        ("poiii", 0.95, 64, 0.65, 0.93, 0.44, 0),
    ],
}

# ═══════════════════════════════════════════════════════════════
# CS2 MAP POOL
# ═══════════════════════════════════════════════════════════════

MAPS = ["Mirage", "Inferno", "Nuke", "Ancient", "Anubis", "Dust2", "Overpass", "Vertigo", "Train"]

# ═══════════════════════════════════════════════════════════════
# MAP STRENGTHS: team → {map: adjustment}
# Positive = strong, negative = weak on that map
# ═══════════════════════════════════════════════════════════════

MAP_STRENGTHS = {
    "Team Vitality": {"Overpass": 0.12, "Ancient": 0.10, "Mirage": -0.05, "Nuke": 0.08},
    "FURIA Esports": {"Mirage": 0.12, "Inferno": 0.08, "Nuke": -0.10, "Overpass": 0.04},
    "Team Falcons": {"Nuke": 0.12, "Inferno": 0.10, "Anubis": -0.06, "Dust2": 0.05},
    "MOUZ": {"Anubis": 0.12, "Dust2": 0.08, "Nuke": -0.10, "Mirage": 0.05},
    "Team Spirit": {"Inferno": 0.12, "Mirage": 0.10, "Ancient": -0.06, "Overpass": 0.05},
    "PARIVISION": {"Mirage": 0.10, "Dust2": 0.08, "Nuke": -0.06, "Anubis": 0.04},
    "FaZe Clan": {"Mirage": 0.12, "Overpass": 0.10, "Ancient": -0.08, "Inferno": 0.06},
    "Natus Vincere": {"Inferno": 0.12, "Nuke": 0.08, "Dust2": -0.08, "Anubis": 0.05},
    "G2 Esports": {"Nuke": 0.10, "Inferno": 0.08, "Anubis": -0.08, "Overpass": 0.05},
    "The MongolZ": {"Mirage": 0.12, "Dust2": 0.10, "Nuke": -0.08, "Anubis": 0.04},
    "Aurora": {"Dust2": 0.12, "Mirage": 0.10, "Overpass": -0.08, "Inferno": 0.05},
    "Astralis": {"Nuke": 0.15, "Inferno": 0.10, "Overpass": -0.05, "Dust2": 0.04},
    "3DMAX": {"Inferno": 0.10, "Nuke": 0.08, "Dust2": -0.06, "Anubis": 0.04},
    "Team Liquid": {"Inferno": 0.10, "Overpass": 0.08, "Anubis": -0.08, "Nuke": 0.05},
    "BC.Game Esports": {"Inferno": 0.10, "Nuke": 0.08, "Mirage": -0.06, "Overpass": 0.04},
    "100 Thieves": {"Nuke": 0.12, "Inferno": 0.08, "Dust2": -0.06, "Ancient": 0.04},
    "paiN Gaming": {"Dust2": 0.10, "Mirage": 0.06, "Ancient": -0.08, "Inferno": 0.04},
    "NRG Esports": {"Ancient": 0.08, "Nuke": 0.06, "Mirage": -0.06, "Dust2": 0.04},
    "FlyQuest": {"Mirage": 0.10, "Inferno": 0.06, "Nuke": -0.08, "Ancient": 0.04},
}

# ═══════════════════════════════════════════════════════════════
# EVENTS/TOURNAMENTS
# ═══════════════════════════════════════════════════════════════

EVENTS = [
    # Tier 5 — Majors
    ("PGL Major Copenhagen 2025", True, 5, True),
    ("PGL Major Austin 2025", True, 5, True),
    ("PGL Major Cluj-Napoca 2026", True, 5, True),
    # Tier 4 — Big LAN events
    ("BLAST Premier World Final 2025", True, 4, True),
    ("IEM Katowice 2025", True, 4, True),
    ("IEM Cologne 2025", True, 4, True),
    ("IEM Krakow 2026", True, 4, True),
    ("ESL Pro League S21", True, 4, False),
    ("BLAST Premier Spring Finals 2025", True, 4, True),
    ("BLAST Premier Fall Finals 2025", True, 4, True),
    ("IEM Dallas 2025", True, 4, False),
    ("PGL Masters Bucharest 2025", True, 4, True),
    # Tier 3 — Medium LAN
    ("Thunderpick World Championship", True, 3, False),
    ("BetBoom Dacha", True, 3, False),
    ("YaLLa Compass", True, 3, False),
    ("Elisa Masters Espoo", True, 3, False),
    ("BLAST Bounty Winter 2026", True, 3, False),
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

"""Feature engineering for CS2 match prediction."""

import math
from datetime import datetime, timedelta
from data.database import get_connection
from models.rating_systems import get_team_elo, get_team_glicko2
from config.settings import ELO_DEFAULT_RATING, GLICKO2_DEFAULT_RATING, CS2_MAPS


def compute_features(team1_id, team2_id, map_name=None, is_lan=False):
    """
    Compute feature vector for a match between team1 and team2.

    Features (all relative: team1 perspective minus team2 perspective):
        1. elo_diff               - Elo rating differential
        2. glicko2_diff           - Glicko-2 rating differential
        3. glicko2_rd_diff        - Glicko-2 RD differential (uncertainty)
        4. ranking_diff           - HLTV world ranking differential (inverted: lower = better)
        5. win_rate_diff          - Overall win rate differential (last 3 months)
        6. recent_form_diff       - Recent form: wins in last 10 matches differential
        7. h2h_advantage          - Head-to-head advantage (win rate of team1 vs team2)
        8. map_wr_diff            - Map-specific win rate differential (if map known)
        9. avg_rounds_diff        - Average rounds won per map differential
        10. is_lan                - LAN flag (1 = LAN, 0 = online)
        11. matches_played_diff   - Total matches played differential (experience)
        12. streak_diff           - Win streak differential
    """
    conn = get_connection()

    features = {}

    # 1. Elo differential
    elo1 = get_team_elo(team1_id)
    elo2 = get_team_elo(team2_id)
    features["elo_diff"] = elo1 - elo2

    # 2-3. Glicko-2 differential
    g1_r, g1_rd, _ = get_team_glicko2(team1_id)
    g2_r, g2_rd, _ = get_team_glicko2(team2_id)
    features["glicko2_diff"] = g1_r - g2_r
    features["glicko2_rd_diff"] = g1_rd - g2_rd

    # 4. World ranking differential (lower rank = better, so invert)
    rank1 = _get_ranking(conn, team1_id)
    rank2 = _get_ranking(conn, team2_id)
    features["ranking_diff"] = rank2 - rank1  # positive = team1 ranked higher

    # 5. Win rate (last 3 months)
    three_months_ago = (datetime.utcnow() - timedelta(days=90)).isoformat()
    wr1 = _get_win_rate(conn, team1_id, since=three_months_ago)
    wr2 = _get_win_rate(conn, team2_id, since=three_months_ago)
    features["win_rate_diff"] = wr1 - wr2

    # 6. Recent form: wins in last 10 matches
    form1 = _get_recent_form(conn, team1_id, n=10)
    form2 = _get_recent_form(conn, team2_id, n=10)
    features["recent_form_diff"] = form1 - form2

    # 7. Head-to-head advantage
    features["h2h_advantage"] = _get_h2h_advantage(conn, team1_id, team2_id)

    # 8. Map-specific win rate
    if map_name:
        mwr1 = _get_map_win_rate(conn, team1_id, map_name)
        mwr2 = _get_map_win_rate(conn, team2_id, map_name)
        features["map_wr_diff"] = mwr1 - mwr2
    else:
        features["map_wr_diff"] = 0.0

    # 9. Average rounds won per map
    avg_r1 = _get_avg_rounds(conn, team1_id)
    avg_r2 = _get_avg_rounds(conn, team2_id)
    features["avg_rounds_diff"] = avg_r1 - avg_r2

    # 10. LAN flag
    features["is_lan"] = 1.0 if is_lan else 0.0

    # 11. Matches played (experience)
    mp1 = _count_matches(conn, team1_id)
    mp2 = _count_matches(conn, team2_id)
    features["matches_played_diff"] = mp1 - mp2

    # 12. Win streak
    streak1 = _get_win_streak(conn, team1_id)
    streak2 = _get_win_streak(conn, team2_id)
    features["streak_diff"] = streak1 - streak2

    conn.close()
    return features


def get_feature_names():
    """Return ordered list of feature names."""
    return [
        "elo_diff", "glicko2_diff", "glicko2_rd_diff", "ranking_diff",
        "win_rate_diff", "recent_form_diff", "h2h_advantage", "map_wr_diff",
        "avg_rounds_diff", "is_lan", "matches_played_diff", "streak_diff",
    ]


# ──────────────────────── Helpers ────────────────────────

def _get_ranking(conn, team_id):
    row = conn.execute(
        "SELECT world_ranking FROM teams WHERE id = ?", (team_id,)
    ).fetchone()
    return row["world_ranking"] if row and row["world_ranking"] else 100


def _get_win_rate(conn, team_id, since=None):
    if since:
        wins = conn.execute(
            "SELECT COUNT(*) as c FROM matches WHERE winner_id = ? AND match_date >= ?",
            (team_id, since),
        ).fetchone()["c"]
        total = conn.execute(
            "SELECT COUNT(*) as c FROM matches WHERE (team1_id = ? OR team2_id = ?) AND match_date >= ?",
            (team_id, team_id, since),
        ).fetchone()["c"]
    else:
        wins = conn.execute(
            "SELECT COUNT(*) as c FROM matches WHERE winner_id = ?", (team_id,)
        ).fetchone()["c"]
        total = conn.execute(
            "SELECT COUNT(*) as c FROM matches WHERE team1_id = ? OR team2_id = ?",
            (team_id, team_id),
        ).fetchone()["c"]
    return wins / total if total > 0 else 0.5


def _get_recent_form(conn, team_id, n=10):
    rows = conn.execute("""
        SELECT winner_id FROM matches
        WHERE team1_id = ? OR team2_id = ?
        ORDER BY match_date DESC LIMIT ?
    """, (team_id, team_id, n)).fetchall()
    if not rows:
        return 0.5
    wins = sum(1 for r in rows if r["winner_id"] == team_id)
    return wins / len(rows)


def _get_h2h_advantage(conn, team1_id, team2_id):
    rows = conn.execute("""
        SELECT winner_id FROM matches
        WHERE (team1_id = ? AND team2_id = ?) OR (team1_id = ? AND team2_id = ?)
    """, (team1_id, team2_id, team2_id, team1_id)).fetchall()
    if not rows:
        return 0.5
    wins = sum(1 for r in rows if r["winner_id"] == team1_id)
    return wins / len(rows)


def _get_map_win_rate(conn, team_id, map_name):
    row = conn.execute(
        "SELECT wins, matches_played FROM team_map_ratings WHERE team_id = ? AND map_name = ?",
        (team_id, map_name),
    ).fetchone()
    if row and row["matches_played"] > 0:
        return row["wins"] / row["matches_played"]
    return 0.5


def _get_avg_rounds(conn, team_id):
    row = conn.execute("""
        SELECT AVG(
            CASE WHEN team1_id = ? THEN team1_score
                 WHEN team2_id = ? THEN team2_score
                 ELSE 0 END
        ) as avg_r
        FROM matches WHERE team1_id = ? OR team2_id = ?
    """, (team_id, team_id, team_id, team_id)).fetchone()
    return row["avg_r"] if row and row["avg_r"] else 8.0


def _count_matches(conn, team_id):
    row = conn.execute(
        "SELECT COUNT(*) as c FROM matches WHERE team1_id = ? OR team2_id = ?",
        (team_id, team_id),
    ).fetchone()
    return row["c"]


def _get_win_streak(conn, team_id):
    rows = conn.execute("""
        SELECT winner_id FROM matches
        WHERE team1_id = ? OR team2_id = ?
        ORDER BY match_date DESC LIMIT 20
    """, (team_id, team_id)).fetchall()
    streak = 0
    for r in rows:
        if r["winner_id"] == team_id:
            streak += 1
        else:
            break
    return streak

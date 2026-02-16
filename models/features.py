"""
Advanced feature engineering for CS2 match prediction.
32 features covering ratings, form, maps, players, context, and momentum.
"""

import math
from datetime import datetime, timedelta
from data.database import get_connection
from models.rating_systems import get_team_elo, get_team_glicko2
from config.settings import (
    ELO_DEFAULT_RATING, GLICKO2_DEFAULT_RATING, CS2_MAPS, EVENT_TIERS,
)


def compute_features(team1_id, team2_id, map_name=None, is_lan=False,
                     best_of=1, event_name="", is_playoff=False):
    """
    Compute 32-feature vector for a match.
    All diff features: positive = advantage for team1.
    """
    conn = get_connection()
    f = {}
    now = datetime.utcnow()

    # ═══════════════ BLOCK 1: RATING SYSTEMS (4) ═══════════════
    elo1, elo2 = get_team_elo(team1_id), get_team_elo(team2_id)
    f["elo_diff"] = elo1 - elo2

    g1_r, g1_rd, _ = get_team_glicko2(team1_id)
    g2_r, g2_rd, _ = get_team_glicko2(team2_id)
    f["glicko2_diff"] = g1_r - g2_r
    f["glicko2_rd_diff"] = g1_rd - g2_rd

    f["elo_win_prob"] = 1.0 / (1.0 + 10 ** ((elo2 - elo1) / 400))

    # ═══════════════ BLOCK 2: RANKINGS & TIER (3) ═══════════════
    rank1 = _get_ranking(conn, team1_id)
    rank2 = _get_ranking(conn, team2_id)
    f["ranking_diff"] = rank2 - rank1
    f["log_ranking_ratio"] = math.log((rank2 + 1) / (rank1 + 1))

    tier = _get_event_tier(event_name)
    f["event_tier"] = tier / 5.0

    # ═══════════════ BLOCK 3: WIN RATES — MULTI-WINDOW (5) ═══════════════
    d30 = (now - timedelta(days=30)).isoformat()
    d90 = (now - timedelta(days=90)).isoformat()

    wr1_30 = _get_win_rate(conn, team1_id, since=d30)
    wr2_30 = _get_win_rate(conn, team2_id, since=d30)
    f["win_rate_30d_diff"] = wr1_30 - wr2_30

    wr1_90 = _get_win_rate(conn, team1_id, since=d90)
    wr2_90 = _get_win_rate(conn, team2_id, since=d90)
    f["win_rate_90d_diff"] = wr1_90 - wr2_90

    f["form_trend_diff"] = (wr1_30 - wr1_90) - (wr2_30 - wr2_90)

    form5_1 = _get_weighted_form(conn, team1_id, n=5)
    form5_2 = _get_weighted_form(conn, team2_id, n=5)
    f["recent_form_5_diff"] = form5_1 - form5_2

    form10_1 = _get_weighted_form(conn, team1_id, n=10)
    form10_2 = _get_weighted_form(conn, team2_id, n=10)
    f["recent_form_10_diff"] = form10_1 - form10_2

    # ═══════════════ BLOCK 4: HEAD-TO-HEAD (3) ═══════════════
    h2h_wr, h2h_count = _get_h2h_detailed(conn, team1_id, team2_id)
    f["h2h_advantage"] = h2h_wr
    f["h2h_matches"] = min(h2h_count / 10.0, 1.0)
    f["h2h_recent"] = _get_h2h_recent(conn, team1_id, team2_id, n=5)

    # ═══════════════ BLOCK 5: MAP ANALYSIS (5) ═══════════════
    if map_name:
        mwr1 = _get_map_win_rate(conn, team1_id, map_name)
        mwr2 = _get_map_win_rate(conn, team2_id, map_name)
        f["map_wr_diff"] = mwr1 - mwr2
        mp1 = _get_map_matches(conn, team1_id, map_name)
        mp2 = _get_map_matches(conn, team2_id, map_name)
        f["map_experience_diff"] = (mp1 - mp2) / max(mp1 + mp2, 1)
    else:
        f["map_wr_diff"] = 0.0
        f["map_experience_diff"] = 0.0

    depth1 = _get_map_pool_depth(conn, team1_id)
    depth2 = _get_map_pool_depth(conn, team2_id)
    f["map_pool_depth_diff"] = depth1 - depth2

    avg_r1 = _get_avg_rounds(conn, team1_id)
    avg_r2 = _get_avg_rounds(conn, team2_id)
    f["avg_rounds_diff"] = avg_r1 - avg_r2

    close1 = _get_close_map_rate(conn, team1_id)
    close2 = _get_close_map_rate(conn, team2_id)
    f["close_map_resilience_diff"] = close1 - close2

    # ═══════════════ BLOCK 6: PLAYER METRICS (4) ═══════════════
    pr1 = _get_team_avg_player_rating(conn, team1_id)
    pr2 = _get_team_avg_player_rating(conn, team2_id)
    f["player_rating_diff"] = pr1 - pr2

    star1 = _get_star_player_rating(conn, team1_id)
    star2 = _get_star_player_rating(conn, team2_id)
    f["star_player_diff"] = star1 - star2

    awp1 = _has_dedicated_awper(conn, team1_id)
    awp2 = _has_dedicated_awper(conn, team2_id)
    f["awp_advantage"] = awp1 - awp2

    rstab1 = _get_roster_stability(conn, team1_id)
    rstab2 = _get_roster_stability(conn, team2_id)
    f["roster_stability_diff"] = rstab1 - rstab2

    # ═══════════════ BLOCK 7: CONTEXT (4) ═══════════════
    f["is_lan"] = 1.0 if is_lan else 0.0
    f["is_playoff"] = 1.0 if is_playoff else 0.0
    f["best_of"] = best_of / 5.0

    rest1 = _days_since_last_match(conn, team1_id)
    rest2 = _days_since_last_match(conn, team2_id)
    f["rest_diff"] = _rest_factor(rest1) - _rest_factor(rest2)

    # ═══════════════ BLOCK 8: MOMENTUM (4) ═══════════════
    streak1 = _get_win_streak(conn, team1_id)
    streak2 = _get_win_streak(conn, team2_id)
    f["streak_diff"] = streak1 - streak2

    mp_all1 = _count_matches(conn, team1_id)
    mp_all2 = _count_matches(conn, team2_id)
    f["experience_diff"] = math.log((mp_all1 + 1) / (mp_all2 + 1))

    vt1 = _get_win_rate_vs_top(conn, team1_id, top_n=10)
    vt2 = _get_win_rate_vs_top(conn, team2_id, top_n=10)
    f["vs_top10_diff"] = vt1 - vt2

    upset1 = _get_upset_rate(conn, team1_id)
    upset2 = _get_upset_rate(conn, team2_id)
    f["upset_factor_diff"] = upset1 - upset2

    conn.close()
    return f


def get_feature_names():
    """Return ordered list of all 32 feature names."""
    return [
        "elo_diff", "glicko2_diff", "glicko2_rd_diff", "elo_win_prob",
        "ranking_diff", "log_ranking_ratio", "event_tier",
        "win_rate_30d_diff", "win_rate_90d_diff", "form_trend_diff",
        "recent_form_5_diff", "recent_form_10_diff",
        "h2h_advantage", "h2h_matches", "h2h_recent",
        "map_wr_diff", "map_experience_diff", "map_pool_depth_diff",
        "avg_rounds_diff", "close_map_resilience_diff",
        "player_rating_diff", "star_player_diff", "awp_advantage",
        "roster_stability_diff",
        "is_lan", "is_playoff", "best_of", "rest_diff",
        "streak_diff", "experience_diff", "vs_top10_diff", "upset_factor_diff",
    ]


# ══════════════════════════════════════════════════════════════
#  HELPER FUNCTIONS
# ══════════════════════════════════════════════════════════════

def _get_ranking(conn, team_id):
    row = conn.execute(
        "SELECT world_ranking FROM teams WHERE id = ?", (team_id,)
    ).fetchone()
    return row["world_ranking"] if row and row["world_ranking"] else 100


def _get_event_tier(event_name):
    if not event_name:
        return 1
    name_lower = event_name.lower()
    for keyword, tier in EVENT_TIERS.items():
        if keyword in name_lower:
            return tier
    return EVENT_TIERS["default"]


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


def _get_weighted_form(conn, team_id, n=10):
    rows = conn.execute("""
        SELECT winner_id FROM matches
        WHERE team1_id = ? OR team2_id = ?
        ORDER BY match_date DESC LIMIT ?
    """, (team_id, team_id, n)).fetchall()
    if not rows:
        return 0.5
    total_weight = 0
    weighted_wins = 0
    for i, r in enumerate(rows):
        weight = n - i
        total_weight += weight
        if r["winner_id"] == team_id:
            weighted_wins += weight
    return weighted_wins / total_weight


def _get_h2h_detailed(conn, team1_id, team2_id):
    rows = conn.execute("""
        SELECT winner_id FROM matches
        WHERE (team1_id = ? AND team2_id = ?) OR (team1_id = ? AND team2_id = ?)
    """, (team1_id, team2_id, team2_id, team1_id)).fetchall()
    if not rows:
        return 0.5, 0
    wins = sum(1 for r in rows if r["winner_id"] == team1_id)
    return wins / len(rows), len(rows)


def _get_h2h_recent(conn, team1_id, team2_id, n=5):
    rows = conn.execute("""
        SELECT winner_id FROM matches
        WHERE (team1_id = ? AND team2_id = ?) OR (team1_id = ? AND team2_id = ?)
        ORDER BY match_date DESC LIMIT ?
    """, (team1_id, team2_id, team2_id, team1_id, n)).fetchall()
    if not rows:
        return 0.5
    total_weight = 0
    weighted_wins = 0
    for i, r in enumerate(rows):
        weight = n - i
        total_weight += weight
        if r["winner_id"] == team1_id:
            weighted_wins += weight
    return weighted_wins / total_weight


def _get_map_win_rate(conn, team_id, map_name):
    row = conn.execute(
        "SELECT wins, matches_played FROM team_map_ratings WHERE team_id = ? AND map_name = ?",
        (team_id, map_name),
    ).fetchone()
    if row and row["matches_played"] > 0:
        return row["wins"] / row["matches_played"]
    return 0.5


def _get_map_matches(conn, team_id, map_name):
    row = conn.execute(
        "SELECT matches_played FROM team_map_ratings WHERE team_id = ? AND map_name = ?",
        (team_id, map_name),
    ).fetchone()
    return row["matches_played"] if row else 0


def _get_map_pool_depth(conn, team_id):
    rows = conn.execute("""
        SELECT wins, matches_played FROM team_map_ratings
        WHERE team_id = ? AND matches_played >= 3
    """, (team_id,)).fetchall()
    return sum(1 for r in rows if r["wins"] / r["matches_played"] > 0.5)


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


def _get_close_map_rate(conn, team_id):
    close_wins = conn.execute("""
        SELECT COUNT(*) as c FROM matches
        WHERE winner_id = ? AND (
            ABS(team1_score - team2_score) <= 3
            OR overtime > 0
        )
    """, (team_id,)).fetchone()["c"]
    close_total = conn.execute("""
        SELECT COUNT(*) as c FROM matches
        WHERE (team1_id = ? OR team2_id = ?) AND (
            ABS(team1_score - team2_score) <= 3
            OR overtime > 0
        )
    """, (team_id, team_id)).fetchone()["c"]
    return close_wins / close_total if close_total > 0 else 0.5


def _get_team_avg_player_rating(conn, team_id):
    row = conn.execute(
        "SELECT AVG(rating_2_1) as avg_r FROM players WHERE team_id = ?",
        (team_id,),
    ).fetchone()
    return row["avg_r"] if row and row["avg_r"] else 1.0


def _get_star_player_rating(conn, team_id):
    row = conn.execute(
        "SELECT MAX(rating_2_1) as max_r FROM players WHERE team_id = ?",
        (team_id,),
    ).fetchone()
    return row["max_r"] if row and row["max_r"] else 1.0


def _has_dedicated_awper(conn, team_id):
    row = conn.execute(
        "SELECT COUNT(*) as c FROM players WHERE team_id = ? AND is_awper = 1",
        (team_id,),
    ).fetchone()
    return 1.0 if row["c"] > 0 else 0.0


def _get_roster_stability(conn, team_id):
    row = conn.execute(
        "SELECT roster_age_days, roster_changes_6m FROM teams WHERE id = ?",
        (team_id,),
    ).fetchone()
    if not row:
        return 0.5
    age = row["roster_age_days"] or 90
    changes = row["roster_changes_6m"] or 0
    age_score = min(age / 180.0, 1.0)
    change_penalty = max(0, 1.0 - changes * 0.3)
    return age_score * change_penalty


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


def _days_since_last_match(conn, team_id):
    row = conn.execute("""
        SELECT MAX(match_date) as last_date FROM matches
        WHERE team1_id = ? OR team2_id = ?
    """, (team_id, team_id)).fetchone()
    if row and row["last_date"]:
        try:
            last = datetime.fromisoformat(str(row["last_date"]))
            return (datetime.utcnow() - last).days
        except (ValueError, TypeError):
            pass
    return 30


def _rest_factor(days):
    if days <= 1:
        return -0.3
    elif days <= 5:
        return 0.2
    elif days <= 14:
        return 0.0
    elif days <= 30:
        return -0.2
    else:
        return -0.4


def _get_win_rate_vs_top(conn, team_id, top_n=10):
    rows = conn.execute("""
        SELECT m.winner_id FROM matches m
        JOIN teams t1 ON m.team1_id = t1.id
        JOIN teams t2 ON m.team2_id = t2.id
        WHERE (m.team1_id = ? OR m.team2_id = ?)
          AND (
            (m.team1_id = ? AND t2.world_ranking IS NOT NULL AND t2.world_ranking <= ?)
            OR
            (m.team2_id = ? AND t1.world_ranking IS NOT NULL AND t1.world_ranking <= ?)
          )
    """, (team_id, team_id, team_id, top_n, team_id, top_n)).fetchall()
    if not rows:
        return 0.3
    wins = sum(1 for r in rows if r["winner_id"] == team_id)
    return wins / len(rows)


def _get_upset_rate(conn, team_id):
    upsets = conn.execute("""
        SELECT COUNT(*) as c FROM matches m
        JOIN teams t1 ON m.team1_id = t1.id
        JOIN teams t2 ON m.team2_id = t2.id
        WHERE m.winner_id = ? AND (
            (m.team1_id = ? AND t1.world_ranking > t2.world_ranking)
            OR
            (m.team2_id = ? AND t2.world_ranking > t1.world_ranking)
        )
    """, (team_id, team_id, team_id)).fetchone()["c"]
    underdog_matches = conn.execute("""
        SELECT COUNT(*) as c FROM matches m
        JOIN teams t1 ON m.team1_id = t1.id
        JOIN teams t2 ON m.team2_id = t2.id
        WHERE (
            (m.team1_id = ? AND t1.world_ranking IS NOT NULL AND t2.world_ranking IS NOT NULL
             AND t1.world_ranking > t2.world_ranking)
            OR
            (m.team2_id = ? AND t1.world_ranking IS NOT NULL AND t2.world_ranking IS NOT NULL
             AND t2.world_ranking > t1.world_ranking)
        )
    """, (team_id, team_id)).fetchone()["c"]
    return upsets / underdog_matches if underdog_matches > 0 else 0.3

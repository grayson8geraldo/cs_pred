"""Elo and Glicko-2 rating systems for CS2 teams with time-decay."""

import math
from datetime import datetime, timedelta
from data.database import get_connection
from config.settings import (
    ELO_K_FACTOR, ELO_K_FACTOR_RECENT, ELO_K_FACTOR_MID, ELO_K_FACTOR_OLD,
    ELO_DEFAULT_RATING,
    GLICKO2_DEFAULT_RATING, GLICKO2_DEFAULT_RD, GLICKO2_DEFAULT_VOL,
)


# ──────────────────────── Elo ────────────────────────

def elo_expected(rating_a, rating_b):
    """Expected score for player A."""
    return 1.0 / (1.0 + 10 ** ((rating_b - rating_a) / 400))


def elo_update(rating, expected, actual, k=ELO_K_FACTOR):
    """Update Elo rating."""
    return rating + k * (actual - expected)


def _get_time_decay_k(match_date=None):
    """Get K-factor based on match recency.
    More recent matches have higher K → bigger rating swings.
    """
    if match_date is None:
        return ELO_K_FACTOR_RECENT
    now = datetime.utcnow()
    if isinstance(match_date, str):
        try:
            match_date = datetime.fromisoformat(match_date)
        except (ValueError, TypeError):
            return ELO_K_FACTOR
    age_days = (now - match_date).days
    if age_days <= 30:
        return ELO_K_FACTOR_RECENT
    elif age_days <= 90:
        return ELO_K_FACTOR_MID
    else:
        return ELO_K_FACTOR_OLD


def update_elo_after_match(team1_id, team2_id, winner_id, match_date=None):
    """Update Elo ratings after a match result with time-decay K-factor."""
    conn = get_connection()

    r1 = _get_rating(conn, team1_id, "elo", ELO_DEFAULT_RATING)
    r2 = _get_rating(conn, team2_id, "elo", ELO_DEFAULT_RATING)

    e1 = elo_expected(r1, r2)
    e2 = elo_expected(r2, r1)

    s1 = 1.0 if winner_id == team1_id else 0.0
    s2 = 1.0 - s1

    k = _get_time_decay_k(match_date)
    new_r1 = elo_update(r1, e1, s1, k=k)
    new_r2 = elo_update(r2, e2, s2, k=k)

    _set_rating(conn, team1_id, "elo", new_r1)
    _set_rating(conn, team2_id, "elo", new_r2)

    conn.commit()
    conn.close()
    return new_r1, new_r2


# ──────────────────────── Glicko-2 ────────────────────────

def glicko2_update(rating, rd, vol, opponent_rating, opponent_rd, score):
    """
    Single-game Glicko-2 update.
    rating, rd, vol: current player params (Glicko-2 scale)
    opponent_rating, opponent_rd: opponent params
    score: 1.0 for win, 0.0 for loss, 0.5 for draw
    Returns (new_rating, new_rd, new_vol)
    """
    TAU = 0.5
    EPSILON = 0.000001

    # Step 1: Convert to Glicko-2 scale
    mu = (rating - 1500) / 173.7178
    phi = rd / 173.7178
    mu_j = (opponent_rating - 1500) / 173.7178
    phi_j = opponent_rd / 173.7178

    # Step 2: Compute g and E
    def g(phi_val):
        return 1.0 / math.sqrt(1 + 3 * phi_val ** 2 / (math.pi ** 2))

    def E(mu_val, mu_j_val, phi_j_val):
        return 1.0 / (1 + math.exp(-g(phi_j_val) * (mu_val - mu_j_val)))

    g_j = g(phi_j)
    e_j = E(mu, mu_j, phi_j)

    # Step 3: Estimated variance
    v = 1.0 / (g_j ** 2 * e_j * (1 - e_j))

    # Step 4: Estimated improvement
    delta = v * g_j * (score - e_j)

    # Step 5: Determine new volatility (simplified iteration)
    a = math.log(vol ** 2)

    def f(x):
        ex = math.exp(x)
        d2 = delta ** 2
        p2 = phi ** 2
        return (ex * (d2 - p2 - v - ex)) / (2 * (p2 + v + ex) ** 2) - (x - a) / TAU ** 2

    A = a
    if delta ** 2 > phi ** 2 + v:
        B = math.log(delta ** 2 - phi ** 2 - v)
    else:
        k = 1
        while f(a - k * TAU) < 0:
            k += 1
        B = a - k * TAU

    fA = f(A)
    fB = f(B)

    for _ in range(100):
        if abs(B - A) < EPSILON:
            break
        C = A + (A - B) * fA / (fB - fA)
        fC = f(C)
        if fC * fB <= 0:
            A = B
            fA = fB
        else:
            fA /= 2
        B = C
        fB = fC

    new_vol = math.exp(A / 2)

    # Step 6: Update RD
    phi_star = math.sqrt(phi ** 2 + new_vol ** 2)

    # Step 7: New rating and RD
    new_phi = 1.0 / math.sqrt(1 / phi_star ** 2 + 1 / v)
    new_mu = mu + new_phi ** 2 * g_j * (score - e_j)

    # Convert back to Glicko scale
    new_rating = 173.7178 * new_mu + 1500
    new_rd = 173.7178 * new_phi

    return new_rating, new_rd, new_vol


def update_glicko2_after_match(team1_id, team2_id, winner_id):
    """Update Glicko-2 ratings after a match."""
    conn = get_connection()

    r1, rd1, v1 = _get_glicko2(conn, team1_id)
    r2, rd2, v2 = _get_glicko2(conn, team2_id)

    s1 = 1.0 if winner_id == team1_id else 0.0
    s2 = 1.0 - s1

    new_r1, new_rd1, new_v1 = glicko2_update(r1, rd1, v1, r2, rd2, s1)
    new_r2, new_rd2, new_v2 = glicko2_update(r2, rd2, v2, r1, rd1, s2)

    _set_glicko2(conn, team1_id, new_r1, new_rd1, new_v1)
    _set_glicko2(conn, team2_id, new_r2, new_rd2, new_v2)

    conn.commit()
    conn.close()
    return (new_r1, new_rd1), (new_r2, new_rd2)


# ──────────────────────── DB Helpers ────────────────────────

def _get_rating(conn, team_id, rating_type, default):
    row = conn.execute(
        "SELECT rating FROM team_ratings WHERE team_id = ? AND rating_type = ?",
        (team_id, rating_type),
    ).fetchone()
    return row["rating"] if row else default


def _set_rating(conn, team_id, rating_type, rating, rd=None, vol=None):
    conn.execute("""
        INSERT INTO team_ratings (team_id, rating_type, rating, rd, volatility, updated_at)
        VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(team_id, rating_type)
        DO UPDATE SET rating=?, rd=?, volatility=?, updated_at=CURRENT_TIMESTAMP
    """, (team_id, rating_type, rating, rd, vol, rating, rd, vol))


def _get_glicko2(conn, team_id):
    row = conn.execute(
        "SELECT rating, rd, volatility FROM team_ratings WHERE team_id = ? AND rating_type = 'glicko2'",
        (team_id,),
    ).fetchone()
    if row:
        return row["rating"], row["rd"] or GLICKO2_DEFAULT_RD, row["volatility"] or GLICKO2_DEFAULT_VOL
    return GLICKO2_DEFAULT_RATING, GLICKO2_DEFAULT_RD, GLICKO2_DEFAULT_VOL


def _set_glicko2(conn, team_id, rating, rd, vol):
    _set_rating(conn, team_id, "glicko2", rating, rd, vol)


def recalculate_all_ratings():
    """Recalculate all ratings from match history (chronological order) with time-decay."""
    conn = get_connection()

    # Reset all ratings
    conn.execute("DELETE FROM team_ratings")
    conn.commit()

    matches = conn.execute(
        "SELECT id, team1_id, team2_id, winner_id, match_date FROM matches ORDER BY match_date ASC"
    ).fetchall()
    conn.close()

    for match in matches:
        if match["winner_id"]:
            match_date = None
            if match["match_date"]:
                try:
                    match_date = datetime.fromisoformat(str(match["match_date"]))
                except (ValueError, TypeError):
                    pass
            update_elo_after_match(
                match["team1_id"], match["team2_id"], match["winner_id"],
                match_date=match_date,
            )
            update_glicko2_after_match(match["team1_id"], match["team2_id"], match["winner_id"])

    return len(matches)


def get_team_elo(team_id):
    conn = get_connection()
    r = _get_rating(conn, team_id, "elo", ELO_DEFAULT_RATING)
    conn.close()
    return r


def get_team_glicko2(team_id):
    conn = get_connection()
    r, rd, v = _get_glicko2(conn, team_id)
    conn.close()
    return r, rd, v

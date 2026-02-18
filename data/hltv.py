"""
HLTV data collector for CS2 match results, team rankings, and player stats.

Uses hltv-async-api to scrape real data from HLTV.org.
This is the PRIMARY source for team rankings and a strong supplementary
source for match results and upcoming matches.

Install: pip install hltv-async-api
"""

import asyncio
import logging
import time
from datetime import datetime

from data.database import get_connection, init_db

logger = logging.getLogger(__name__)


def _get_hltv_client():
    """Create an HLTV client with safe defaults."""
    from hltv_async_api import Hltv
    return Hltv(
        max_delay=15,
        timeout=30,
        max_retries=5,
        debug=False,
        tz="UTC",
    )


def _get_or_create_team(conn, name, hltv_id=None):
    """Get team ID by name, or create if doesn't exist."""
    if not name or name.strip() == "":
        return None
    name = name.strip()
    row = conn.execute("SELECT id FROM teams WHERE name = ?", (name,)).fetchone()
    if row:
        tid = row["id"]
        if hltv_id:
            conn.execute("UPDATE teams SET hltv_id = ? WHERE id = ? AND (hltv_id IS NULL OR hltv_id != ?)",
                         (hltv_id, tid, hltv_id))
        return tid
    cursor = conn.execute(
        "INSERT INTO teams (name, hltv_id, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
        (name, hltv_id),
    )
    conn.commit()
    return cursor.lastrowid


# ═══════════════════════════════════════════════════════════════
# TEAM RANKINGS — Primary source for world rankings
# ═══════════════════════════════════════════════════════════════

async def _fetch_rankings(max_teams=30):
    """Fetch current HLTV world rankings."""
    async with _get_hltv_client() as hltv:
        teams = await hltv.get_top_teams(max_teams=max_teams)
    return teams


def fetch_rankings(max_teams=30):
    """Sync wrapper: fetch HLTV top team rankings."""
    try:
        result = asyncio.run(_fetch_rankings(max_teams))
        if result:
            logger.info("Fetched %d team rankings from HLTV", len(result))
        return result or []
    except Exception as e:
        logger.error("Failed to fetch HLTV rankings: %s", e)
        return []


def store_rankings(rankings):
    """Store HLTV rankings in the database, updating world_ranking for each team."""
    if not rankings:
        return 0

    conn = get_connection()
    updated = 0

    for team in rankings:
        try:
            title = team.get("title", "").strip()
            rank = int(team.get("rank", 0))
            hltv_id = team.get("id")
            points = team.get("points", "")

            if not title or rank == 0:
                continue

            team_id = _get_or_create_team(conn, title, hltv_id)
            if not team_id:
                continue

            conn.execute("""
                UPDATE teams
                SET world_ranking = ?, hltv_id = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (rank, hltv_id, team_id))
            updated += 1

        except Exception as e:
            logger.error("Error storing ranking for %s: %s", team.get("title"), e)

    conn.commit()
    conn.close()
    logger.info("Updated rankings for %d teams from HLTV", updated)
    return updated


# ═══════════════════════════════════════════════════════════════
# MATCH RESULTS — Real completed match data
# ═══════════════════════════════════════════════════════════════

async def _fetch_results(days=7, max_results=50):
    """Fetch recent match results from HLTV."""
    async with _get_hltv_client() as hltv:
        results = await hltv.get_results(days=days, min_rating=1, max=max_results)
    return results


def fetch_results(days=7, max_results=50):
    """Sync wrapper: fetch recent HLTV match results."""
    try:
        result = asyncio.run(_fetch_results(days, max_results))
        if result:
            logger.info("Fetched %d match results from HLTV", len(result))
        return result or []
    except Exception as e:
        logger.error("Failed to fetch HLTV results: %s", e)
        return []


def store_results(results):
    """Store HLTV match results in the database."""
    if not results:
        return 0

    conn = get_connection()
    stored = 0

    for match in results:
        try:
            team1_name = match.get("team1", "").strip()
            team2_name = match.get("team2", "").strip()
            if not team1_name or not team2_name or team1_name == "TBD" or team2_name == "TBD":
                continue

            match_id = match.get("id")
            hltv_match_id = f"hltv_{match_id}" if match_id else None

            team1_id = _get_or_create_team(conn, team1_name)
            team2_id = _get_or_create_team(conn, team2_name)
            if not team1_id or not team2_id:
                continue

            try:
                score1 = int(match.get("score1", 0))
                score2 = int(match.get("score2", 0))
            except (ValueError, TypeError):
                score1, score2 = 0, 0

            if score1 > score2:
                winner_id = team1_id
            elif score2 > score1:
                winner_id = team2_id
            else:
                winner_id = None

            event_name = match.get("event", "")

            # Parse date if available
            match_date = match.get("date", "")
            if match_date:
                try:
                    match_date = datetime.strptime(match_date, "%d-%m-%Y").isoformat()
                except (ValueError, TypeError):
                    match_date = datetime.utcnow().isoformat()
            else:
                match_date = datetime.utcnow().isoformat()

            # Determine best_of from scores
            total = score1 + score2
            if total <= 1:
                best_of = 1
            elif total <= 3:
                best_of = 3
            else:
                best_of = 5

            conn.execute("""
                INSERT OR IGNORE INTO matches
                    (hltv_id, team1_id, team2_id, team1_score, team2_score,
                     winner_id, event_name, match_date, best_of)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (hltv_match_id, team1_id, team2_id, score1, score2,
                  winner_id, event_name, match_date, best_of))
            stored += 1

        except Exception as e:
            logger.error("Error storing HLTV match: %s", e)
            continue

    conn.commit()
    conn.close()
    logger.info("Stored %d match results from HLTV", stored)
    return stored


# ═══════════════════════════════════════════════════════════════
# UPCOMING MATCHES — For predictions
# ═══════════════════════════════════════════════════════════════

async def _fetch_upcoming(days=3, min_rating=1):
    """Fetch upcoming matches from HLTV."""
    async with _get_hltv_client() as hltv:
        matches = await hltv.get_matches(days=days, min_rating=min_rating, live=True, future=True)
    return matches


def fetch_upcoming(days=3, min_rating=1):
    """Sync wrapper: fetch upcoming HLTV matches."""
    try:
        result = asyncio.run(_fetch_upcoming(days, min_rating))
        if result:
            logger.info("Fetched %d upcoming matches from HLTV", len(result))
        return result or []
    except Exception as e:
        logger.error("Failed to fetch HLTV upcoming matches: %s", e)
        return []


# ═══════════════════════════════════════════════════════════════
# TEAM INFO — Roster, coach, rank details
# ═══════════════════════════════════════════════════════════════

async def _fetch_team_info(team_id, title):
    """Fetch detailed team info from HLTV."""
    async with _get_hltv_client() as hltv:
        info = await hltv.get_team_info(team_id, title)
    return info


def fetch_team_info(team_id, title):
    """Sync wrapper: fetch team info from HLTV."""
    try:
        result = asyncio.run(_fetch_team_info(team_id, title))
        return result
    except Exception as e:
        logger.warning("Failed to fetch team info for %s: %s", title, e)
        return None


def update_team_rosters(rankings):
    """Fetch and store player rosters for ranked teams.

    Uses HLTV team info to get real player data.
    Only fetches for top N teams to respect rate limits.
    """
    if not rankings:
        return 0

    conn = get_connection()
    updated = 0
    max_teams = min(len(rankings), 30)

    for i, team in enumerate(rankings[:max_teams]):
        hltv_id = team.get("id")
        title = team.get("title", "").strip()
        if not hltv_id or not title:
            continue

        logger.info("Fetching roster for %s (%d/%d)...", title, i + 1, max_teams)

        try:
            info = fetch_team_info(hltv_id, title)
            if not info or not info.get("players"):
                continue

            # Find team in DB
            row = conn.execute("SELECT id FROM teams WHERE name = ?", (title,)).fetchone()
            if not row:
                continue
            db_team_id = row["id"]

            # Clear old players for this team
            conn.execute("DELETE FROM players WHERE team_id = ?", (db_team_id,))

            players = info.get("players", {})
            for nickname, player_hltv_id in players.items():
                conn.execute("""
                    INSERT OR IGNORE INTO players
                        (name, nickname, team_id, hltv_id)
                    VALUES (?, ?, ?, ?)
                """, (nickname, nickname, db_team_id, player_hltv_id))

            updated += 1
            # Delay between team info requests to respect HLTV
            time.sleep(3)

        except Exception as e:
            logger.warning("Error fetching roster for %s: %s", title, e)
            continue

    conn.commit()
    conn.close()
    logger.info("Updated rosters for %d teams", updated)
    return updated


# ═══════════════════════════════════════════════════════════════
# TOP-LEVEL COLLECTION
# ═══════════════════════════════════════════════════════════════

def collect_hltv_rankings():
    """Fetch and store HLTV rankings. Primary source for world_ranking."""
    rankings = fetch_rankings(max_teams=30)
    if rankings:
        store_rankings(rankings)
    return rankings


def collect_hltv_results(days=7, max_results=50):
    """Fetch and store HLTV match results."""
    results = fetch_results(days=days, max_results=max_results)
    if results:
        store_results(results)
    return results


def collect_hltv_all():
    """Full HLTV data collection: rankings + results + upcoming."""
    init_db()

    # 1. Rankings (most important — real HLTV world rankings)
    logger.info("Fetching HLTV rankings...")
    rankings = collect_hltv_rankings()

    # 2. Match results
    logger.info("Fetching HLTV match results...")
    collect_hltv_results(days=7, max_results=50)

    # 3. Upcoming matches (logged but not stored — used by web app)
    logger.info("Fetching HLTV upcoming matches...")
    upcoming = fetch_upcoming(days=3, min_rating=1)

    return rankings, upcoming

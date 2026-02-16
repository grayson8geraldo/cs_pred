"""SQLite database for storing CS2 match data, team stats, and ratings."""

import sqlite3
import os
from config.settings import DB_PATH, DATA_DIR


def get_connection():
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.executescript("""
    CREATE TABLE IF NOT EXISTS teams (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        hltv_id INTEGER,
        country TEXT,
        world_ranking INTEGER,
        logo_url TEXT,
        roster_age_days INTEGER DEFAULT 90,
        roster_changes_6m INTEGER DEFAULT 0,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS players (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        nickname TEXT,
        team_id INTEGER,
        hltv_id INTEGER,
        country TEXT,
        rating_2_1 REAL DEFAULT 1.0,
        adr REAL DEFAULT 70.0,
        kast REAL DEFAULT 0.65,
        kd_ratio REAL DEFAULT 1.0,
        headshot_pct REAL DEFAULT 0.45,
        opening_kill_ratio REAL DEFAULT 1.0,
        clutch_win_pct REAL DEFAULT 0.0,
        is_awper INTEGER DEFAULT 0,
        joined_date TIMESTAMP,
        FOREIGN KEY (team_id) REFERENCES teams(id)
    );

    CREATE TABLE IF NOT EXISTS matches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        hltv_id INTEGER UNIQUE,
        team1_id INTEGER NOT NULL,
        team2_id INTEGER NOT NULL,
        team1_score INTEGER,
        team2_score INTEGER,
        winner_id INTEGER,
        best_of INTEGER DEFAULT 1,
        event_name TEXT,
        event_id INTEGER,
        event_tier INTEGER DEFAULT 1,
        is_lan INTEGER DEFAULT 0,
        is_playoff INTEGER DEFAULT 0,
        match_date TIMESTAMP,
        map_name TEXT,
        team1_ct_rounds INTEGER,
        team1_t_rounds INTEGER,
        team2_ct_rounds INTEGER,
        team2_t_rounds INTEGER,
        team1_pistol_wins INTEGER DEFAULT 0,
        team2_pistol_wins INTEGER DEFAULT 0,
        team1_first_kills INTEGER DEFAULT 0,
        team2_first_kills INTEGER DEFAULT 0,
        overtime INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (team1_id) REFERENCES teams(id),
        FOREIGN KEY (team2_id) REFERENCES teams(id)
    );

    CREATE TABLE IF NOT EXISTS map_stats (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        match_id INTEGER,
        team_id INTEGER NOT NULL,
        map_name TEXT NOT NULL,
        ct_rounds_won INTEGER DEFAULT 0,
        t_rounds_won INTEGER DEFAULT 0,
        total_rounds_won INTEGER DEFAULT 0,
        total_rounds_lost INTEGER DEFAULT 0,
        pistol_rounds_won INTEGER DEFAULT 0,
        first_kills INTEGER DEFAULT 0,
        is_winner INTEGER DEFAULT 0,
        FOREIGN KEY (match_id) REFERENCES matches(id),
        FOREIGN KEY (team_id) REFERENCES teams(id)
    );

    CREATE TABLE IF NOT EXISTS team_ratings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        team_id INTEGER NOT NULL,
        rating_type TEXT NOT NULL,
        rating REAL NOT NULL,
        rd REAL,
        volatility REAL,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (team_id) REFERENCES teams(id),
        UNIQUE(team_id, rating_type)
    );

    CREATE TABLE IF NOT EXISTS team_map_ratings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        team_id INTEGER NOT NULL,
        map_name TEXT NOT NULL,
        rating REAL NOT NULL DEFAULT 1500,
        matches_played INTEGER DEFAULT 0,
        wins INTEGER DEFAULT 0,
        ct_wr REAL DEFAULT 0.5,
        t_wr REAL DEFAULT 0.5,
        avg_rounds_won REAL DEFAULT 8.0,
        pistol_wr REAL DEFAULT 0.5,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (team_id) REFERENCES teams(id),
        UNIQUE(team_id, map_name)
    );

    CREATE TABLE IF NOT EXISTS predictions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        match_id INTEGER,
        team1_id INTEGER NOT NULL,
        team2_id INTEGER NOT NULL,
        team1_win_prob REAL NOT NULL,
        team2_win_prob REAL NOT NULL,
        predicted_winner_id INTEGER,
        actual_winner_id INTEGER,
        confidence REAL,
        confidence_label TEXT,
        method TEXT,
        features_json TEXT,
        analysis_json TEXT,
        bookmaker_odds_team1 REAL,
        bookmaker_odds_team2 REAL,
        is_value_bet INTEGER DEFAULT 0,
        value_edge REAL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (team1_id) REFERENCES teams(id),
        FOREIGN KEY (team2_id) REFERENCES teams(id)
    );

    CREATE INDEX IF NOT EXISTS idx_matches_date ON matches(match_date);
    CREATE INDEX IF NOT EXISTS idx_matches_teams ON matches(team1_id, team2_id);
    CREATE INDEX IF NOT EXISTS idx_matches_winner ON matches(winner_id);
    CREATE INDEX IF NOT EXISTS idx_map_stats_team ON map_stats(team_id, map_name);
    CREATE INDEX IF NOT EXISTS idx_team_ratings_team ON team_ratings(team_id);
    CREATE INDEX IF NOT EXISTS idx_predictions_date ON predictions(created_at);
    CREATE INDEX IF NOT EXISTS idx_players_team ON players(team_id);
    """)

    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
    print("Database initialized successfully.")

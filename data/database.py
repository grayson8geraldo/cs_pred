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
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS players (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        nickname TEXT,
        team_id INTEGER,
        hltv_id INTEGER,
        country TEXT,
        rating REAL DEFAULT 1.0,
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
        is_lan INTEGER DEFAULT 0,
        match_date TIMESTAMP,
        map_name TEXT,
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
        rating_type TEXT NOT NULL,  -- 'elo', 'glicko2'
        rating REAL NOT NULL,
        rd REAL,  -- rating deviation (Glicko2)
        volatility REAL,  -- volatility (Glicko2)
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
        features_json TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (team1_id) REFERENCES teams(id),
        FOREIGN KEY (team2_id) REFERENCES teams(id)
    );

    CREATE INDEX IF NOT EXISTS idx_matches_date ON matches(match_date);
    CREATE INDEX IF NOT EXISTS idx_matches_teams ON matches(team1_id, team2_id);
    CREATE INDEX IF NOT EXISTS idx_map_stats_team ON map_stats(team_id, map_name);
    CREATE INDEX IF NOT EXISTS idx_team_ratings_team ON team_ratings(team_id);
    """)

    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
    print("Database initialized successfully.")

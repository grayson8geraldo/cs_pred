"""Application configuration."""

import os

# PandaScore API (free tier: 1000 req/hour)
PANDASCORE_BASE = "https://api.pandascore.co"
PANDASCORE_TOKEN = os.environ.get("PANDASCORE_TOKEN", "u_kwjA6YhIWSlD5QD1i8zDF0ySW60pa9451Tk0ZSTRKQRgtwD6w")

# Data paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
MODELS_DIR = os.path.join(BASE_DIR, "models")
DB_PATH = os.path.join(DATA_DIR, "cs_pred.db")

# Rating system defaults
ELO_K_FACTOR = 32
ELO_DEFAULT_RATING = 1500
GLICKO2_DEFAULT_RATING = 1500
GLICKO2_DEFAULT_RD = 350
GLICKO2_DEFAULT_VOL = 0.06

# Time-decay Elo: K-factor increases for recent matches
ELO_K_FACTOR_RECENT = 40   # last 30 days
ELO_K_FACTOR_OLD = 20      # older than 90 days

# Prediction model
MODEL_PATH = os.path.join(MODELS_DIR, "ensemble_model.pkl")
FEATURE_COLUMNS_PATH = os.path.join(MODELS_DIR, "feature_columns.json")
CALIBRATOR_PATH = os.path.join(MODELS_DIR, "calibrator.pkl")

# Data refresh interval (seconds)
DATA_REFRESH_INTERVAL = 3600  # 1 hour

# Maps in CS2 competitive pool
CS2_MAPS = [
    "Mirage", "Inferno", "Nuke", "Overpass",
    "Ancient", "Anubis", "Dust2", "Vertigo", "Train"
]

# Event tiers — higher = more prestigious
EVENT_TIERS = {
    "major": 5,
    "pgl": 5,
    "blast premier": 4,
    "iem": 4,
    "esl pro league": 4,
    "thunderpick": 3,
    "betboom": 3,
    "cct": 2,
    "esl challenger": 2,
    "skyesports": 2,
    "default": 1,
}

# Flask
FLASK_HOST = "0.0.0.0"
FLASK_PORT = 5000
SECRET_KEY = os.environ.get("SECRET_KEY", "cs-pred-dev-key-change-in-production")

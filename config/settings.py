"""Application configuration."""

import os

# HLTV unofficial API (Vercel)
HLTV_API_BASE = "https://hltv-api.vercel.app"

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

# Prediction model
MODEL_PATH = os.path.join(MODELS_DIR, "xgboost_model.json")
FEATURE_COLUMNS_PATH = os.path.join(MODELS_DIR, "feature_columns.json")

# Data refresh interval (seconds)
DATA_REFRESH_INTERVAL = 3600  # 1 hour

# Maps in CS2 competitive pool
CS2_MAPS = [
    "Mirage", "Inferno", "Nuke", "Overpass",
    "Ancient", "Anubis", "Dust2", "Vertigo", "Train"
]

# Flask
FLASK_HOST = "0.0.0.0"
FLASK_PORT = 5000
SECRET_KEY = os.environ.get("SECRET_KEY", "cs-pred-dev-key-change-in-production")

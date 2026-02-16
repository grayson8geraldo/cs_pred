"""XGBoost-based CS2 match predictor."""

import json
import os
import logging
import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.model_selection import cross_val_score, StratifiedKFold
from sklearn.metrics import accuracy_score, classification_report

from models.features import compute_features, get_feature_names
from models.rating_systems import elo_expected, get_team_elo, get_team_glicko2
from data.database import get_connection
from config.settings import MODEL_PATH, MODELS_DIR, FEATURE_COLUMNS_PATH

logger = logging.getLogger(__name__)


class CSPredictor:
    """Counter-Strike 2 match outcome predictor."""

    def __init__(self):
        self.model = None
        self.feature_names = get_feature_names()
        self._load_model()

    def _load_model(self):
        """Load trained model if available."""
        if os.path.exists(MODEL_PATH):
            self.model = xgb.XGBClassifier()
            self.model.load_model(MODEL_PATH)
            logger.info("Model loaded from %s", MODEL_PATH)
        else:
            logger.info("No trained model found, will use heuristic predictor")

    def train(self):
        """Train XGBoost model on historical match data."""
        conn = get_connection()
        matches = conn.execute("""
            SELECT id, team1_id, team2_id, winner_id, map_name, is_lan
            FROM matches
            WHERE winner_id IS NOT NULL
            ORDER BY match_date ASC
        """).fetchall()
        conn.close()

        if len(matches) < 20:
            logger.warning("Not enough matches to train (%d). Need at least 20.", len(matches))
            return None

        X, y = [], []
        for match in matches:
            features = compute_features(
                match["team1_id"], match["team2_id"],
                map_name=match["map_name"],
                is_lan=bool(match["is_lan"]),
            )
            feature_vector = [features[f] for f in self.feature_names]
            label = 1 if match["winner_id"] == match["team1_id"] else 0
            X.append(feature_vector)
            y.append(label)

        X = np.array(X)
        y = np.array(y)

        # XGBoost with tuned hyperparameters for esports prediction
        self.model = xgb.XGBClassifier(
            n_estimators=200,
            max_depth=5,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            min_child_weight=3,
            reg_alpha=0.1,
            reg_lambda=1.0,
            eval_metric="logloss",
            random_state=42,
        )

        # Cross-validation
        cv = StratifiedKFold(n_splits=min(5, max(2, len(y) // 10)), shuffle=True, random_state=42)
        scores = cross_val_score(self.model, X, y, cv=cv, scoring="accuracy")
        logger.info("CV Accuracy: %.3f (+/- %.3f)", scores.mean(), scores.std())

        # Train on full data
        self.model.fit(X, y)

        # Save
        os.makedirs(MODELS_DIR, exist_ok=True)
        self.model.save_model(MODEL_PATH)

        with open(FEATURE_COLUMNS_PATH, "w") as f:
            json.dump(self.feature_names, f)

        logger.info("Model saved to %s", MODEL_PATH)
        return {
            "cv_accuracy": float(scores.mean()),
            "cv_std": float(scores.std()),
            "n_samples": len(y),
            "feature_importance": dict(zip(
                self.feature_names,
                [float(x) for x in self.model.feature_importances_]
            )),
        }

    def predict(self, team1_id, team2_id, map_name=None, is_lan=False):
        """
        Predict match outcome.
        Returns dict with probabilities and analysis.
        """
        features = compute_features(team1_id, team2_id, map_name=map_name, is_lan=is_lan)
        feature_vector = [features[f] for f in self.feature_names]

        if self.model is not None:
            # ML prediction
            proba = self.model.predict_proba(np.array([feature_vector]))[0]
            team1_prob = float(proba[1])  # class 1 = team1 wins
            team2_prob = float(proba[0])  # class 0 = team2 wins
            method = "xgboost"
        else:
            # Heuristic fallback using rating-based prediction
            team1_prob, team2_prob = self._heuristic_predict(features)
            method = "heuristic"

        # Determine confidence
        confidence = abs(team1_prob - team2_prob)
        confidence_label = (
            "high" if confidence > 0.3
            else "medium" if confidence > 0.15
            else "low"
        )

        # Get team names
        conn = get_connection()
        t1 = conn.execute("SELECT name FROM teams WHERE id = ?", (team1_id,)).fetchone()
        t2 = conn.execute("SELECT name FROM teams WHERE id = ?", (team2_id,)).fetchone()
        conn.close()

        team1_name = t1["name"] if t1 else f"Team {team1_id}"
        team2_name = t2["name"] if t2 else f"Team {team2_id}"

        predicted_winner = team1_name if team1_prob > team2_prob else team2_name
        predicted_winner_id = team1_id if team1_prob > team2_prob else team2_id

        return {
            "team1": {"id": team1_id, "name": team1_name, "win_prob": round(team1_prob, 4)},
            "team2": {"id": team2_id, "name": team2_name, "win_prob": round(team2_prob, 4)},
            "predicted_winner": predicted_winner,
            "predicted_winner_id": predicted_winner_id,
            "confidence": round(confidence, 4),
            "confidence_label": confidence_label,
            "method": method,
            "features": {k: round(v, 4) for k, v in features.items()},
            "analysis": self._build_analysis(features, team1_name, team2_name),
        }

    def _heuristic_predict(self, features):
        """
        Heuristic prediction when no ML model is trained.
        Weighted combination of normalized features.
        """
        weights = {
            "elo_diff": 0.25,
            "glicko2_diff": 0.20,
            "ranking_diff": 0.15,
            "win_rate_diff": 0.15,
            "recent_form_diff": 0.10,
            "h2h_advantage": 0.05,
            "map_wr_diff": 0.05,
            "streak_diff": 0.03,
            "avg_rounds_diff": 0.02,
        }

        # Normalize each feature to [-1, 1] range approximately
        norm = {
            "elo_diff": features["elo_diff"] / 400,
            "glicko2_diff": features["glicko2_diff"] / 400,
            "ranking_diff": features["ranking_diff"] / 50,
            "win_rate_diff": features["win_rate_diff"] * 2,
            "recent_form_diff": features["recent_form_diff"] * 2,
            "h2h_advantage": (features["h2h_advantage"] - 0.5) * 2,
            "map_wr_diff": features["map_wr_diff"] * 2,
            "streak_diff": features["streak_diff"] / 5,
            "avg_rounds_diff": features["avg_rounds_diff"] / 5,
        }

        # Clamp to [-1, 1]
        for k in norm:
            norm[k] = max(-1, min(1, norm[k]))

        # Weighted sum -> sigmoid
        score = sum(weights[k] * norm[k] for k in weights)
        team1_prob = 1.0 / (1 + np.exp(-4 * score))  # sigmoid with scaling
        team2_prob = 1.0 - team1_prob

        return team1_prob, team2_prob

    def _build_analysis(self, features, team1_name, team2_name):
        """Build human-readable analysis of key factors."""
        points = []

        elo_diff = features["elo_diff"]
        if abs(elo_diff) > 100:
            better = team1_name if elo_diff > 0 else team2_name
            points.append(f"{better} has a significant Elo advantage ({abs(elo_diff):.0f} pts)")
        elif abs(elo_diff) > 30:
            better = team1_name if elo_diff > 0 else team2_name
            points.append(f"{better} has a slight Elo advantage ({abs(elo_diff):.0f} pts)")

        wr_diff = features["win_rate_diff"]
        if abs(wr_diff) > 0.1:
            better = team1_name if wr_diff > 0 else team2_name
            points.append(f"{better} has better recent win rate ({abs(wr_diff)*100:.0f}% difference)")

        form_diff = features["recent_form_diff"]
        if abs(form_diff) > 0.2:
            better = team1_name if form_diff > 0 else team2_name
            points.append(f"{better} is in better recent form")

        h2h = features["h2h_advantage"]
        if h2h > 0.6:
            points.append(f"{team1_name} has head-to-head advantage ({h2h*100:.0f}% win rate)")
        elif h2h < 0.4:
            points.append(f"{team2_name} has head-to-head advantage ({(1-h2h)*100:.0f}% win rate)")

        map_diff = features["map_wr_diff"]
        if abs(map_diff) > 0.1:
            better = team1_name if map_diff > 0 else team2_name
            points.append(f"{better} is stronger on this map")

        streak_diff = features["streak_diff"]
        if abs(streak_diff) >= 3:
            better = team1_name if streak_diff > 0 else team2_name
            points.append(f"{better} has a longer win streak")

        if not points:
            points.append("Very even matchup - hard to call")

        return points


# Singleton
_predictor = None


def get_predictor():
    global _predictor
    if _predictor is None:
        _predictor = CSPredictor()
    return _predictor

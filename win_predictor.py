import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import cross_val_score
import pickle
import os
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)


class WinPredictor:
    def __init__(self, model_path='models/win_predictor.pkl'):
        self.model_path = model_path
        self.model = None
        self.features = ['quality_score', 'rsi', 'adx', 'vol_ratio', 'atr', 'hour_of_day']
        self._load()

    def _load(self):
        if os.path.exists(self.model_path):
            try:
                with open(self.model_path, 'rb') as f:
                    self.model = pickle.load(f)
                logger.info(f"Loaded ML model from {self.model_path}")
            except Exception as e:
                logger.error(f"Failed to load model: {e}")
                self.model = None

    def train(self, signals_df):
        if len(signals_df) < 100:
            logger.warning("Not enough data to train model (< 100 signals)")
            return False

        X = signals_df[self.features]
        y = (signals_df['outcome'] == 'WIN').astype(int)

        self.model = RandomForestClassifier(
            max_depth=4,
            n_estimators=100,
            min_samples_leaf=5,
            random_state=42
        )

        scores = cross_val_score(self.model, X, y, cv=5)
        logger.info(f"CV Accuracy: {scores.mean():.2%} (+/- {scores.std():.2%})")

        self.model.fit(X, y)

        os.makedirs(os.path.dirname(self.model_path), exist_ok=True)
        with open(self.model_path, 'wb') as f:
            pickle.dump(self.model, f)

        return True

    def predict_proba(self, signal):
        if self.model is None:
            return 0.5

        features = [
            signal.get('quality_score', 50),
            signal.get('rsi', 50),
            signal.get('adx', 25),
            signal.get('vol_ratio', 1.0),
            signal.get('atr', 0),
            datetime.now(timezone.utc).hour
        ]

        return self.model.predict_proba([features])[0][1]

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

    def get_feature_importance(self):
        if self.model is None:
            return {}
        return dict(zip(self.features, self.model.feature_importances_))


def train_model_from_tracker(tracker):
    """
    Extract signals data from a tracker instance and train the win predictor model.

    Args:
        tracker: A tracker instance with a get_signals() method or signals attribute

    Returns:
        bool: True if training succeeded, False otherwise
    """
    predictor = WinPredictor()

    # Try to get signals from tracker
    signals_data = None
    if hasattr(tracker, 'get_signals'):
        signals_data = tracker.get_signals()
    elif hasattr(tracker, 'signals'):
        signals_data = tracker.signals
    elif hasattr(tracker, 'db') and hasattr(tracker.db, 'get_all_signals'):
        signals_data = tracker.db.get_all_signals()

    if signals_data is None:
        logger.warning("No signals data found in tracker")
        return False

    # Convert to DataFrame
    if isinstance(signals_data, pd.DataFrame):
        df = signals_data
    else:
        df = pd.DataFrame(signals_data)

    if len(df) == 0:
        logger.warning("No signals available for training")
        return False

    # Filter for closed signals with outcomes
    closed_df = df[df['status'].isin(['WIN', 'SL', 'TP1', 'TP2', 'TP3', 'TP4', 'BREAKEVEN', 'EXPIRED'])]

    if len(closed_df) < 100:
        logger.warning(f"Not enough closed signals for training ({len(closed_df)} found, need 100)")
        return False

    # Ensure required columns exist
    required_cols = ['quality_score', 'rsi', 'adx', 'vol_ratio', 'atr', 'outcome']
    missing_cols = [col for col in required_cols if col not in closed_df.columns]

    if missing_cols:
        logger.warning(f"Missing columns for training: {missing_cols}")
        # Add default values for missing columns
        for col in missing_cols:
            if col == 'outcome':
                # Map status to outcome if outcome column is missing
                closed_df[col] = closed_df['status'].apply(
                    lambda x: 'WIN' if x in ['WIN', 'TP1', 'TP2', 'TP3', 'TP4'] else 'LOSS' if x == 'SL' else 'NEUTRAL'
                )
            elif col == 'hour_of_day':
                closed_df[col] = pd.to_datetime(closed_df.get('timestamp', datetime.now(timezone.utc))).dt.hour
            else:
                closed_df[col] = 0

    logger.info(f"Training win predictor with {len(closed_df)} closed signals")
    return predictor.train(closed_df)

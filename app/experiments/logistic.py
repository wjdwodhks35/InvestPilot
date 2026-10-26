"""Shared past-only logistic fitting; callers retain their experiment definitions."""
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from app.experiments.training import LABELS


def fit_past_returns(target, x, horizon, require_all_classes=False):
    if horizon <= 0:
        raise ValueError('Positive calendar-day horizon required')
    if target.empty or len(x) != len(target):
        return {'status': 'insufficient_history'}
    dates = pd.to_datetime(target.date)
    if dates.duplicated().any() or not dates.is_monotonic_increasing:
        raise ValueError('Unique ascending dates required')
    # Match both experiments: decision on next observation, prior close reference.
    endpoints = dates.searchsorted(dates.shift(-1) + pd.Timedelta(days=horizon))
    usable = (endpoints < len(target)) & np.isfinite(x.to_numpy(dtype=float)).all(axis=1)
    indices = np.flatnonzero(usable)
    if len(indices) < 100 or not np.isfinite(x.iloc[-1]).all():
        return {'status': 'insufficient_history'}
    returns = target.close.iloc[endpoints[indices]].to_numpy() / target.close.iloc[indices].to_numpy() - 1
    y = np.where(returns > 0, 2, np.where(returns < 0, 0, 1))
    if len(set(y)) < (3 if require_all_classes else 2):
        return {'status': 'insufficient_classes'}
    model = make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000, random_state=42))
    model.fit(x.iloc[indices], y)
    probabilities = np.zeros(3)
    probabilities[model[-1].classes_] = model.predict_proba(x.iloc[[-1]])[0]
    means = np.array([returns[y == cls].mean() if (y == cls).any() else 0 for cls in range(3)])
    return dict(status='ok', probabilities=dict(zip(LABELS, map(float, probabilities))),
                prediction=LABELS[int(probabilities.argmax())],
                expected_return_pct=float(probabilities @ means * 100), train_rows=len(indices),
                latest_label_date=str(target.iloc[endpoints[indices[-1]]].date),
                return_estimator='Probability-weighted past-only class mean returns')

"""Both public experiment paths preserve the same numerical baseline without peers."""
import numpy as np
import pandas as pd
import pytest
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from app.experiments.logistic import fit_past_returns
from app.experiments.training import features
from scripts.ollama_history import logistic_before
from scripts.top50_experiment import train_past


def frame():
    rng=np.random.default_rng(91)
    close=np.round(10000*np.exp(np.cumsum(rng.normal(0,.02,500))))
    return pd.DataFrame(dict(date=pd.bdate_range('2022-01-01',periods=500).strftime('%Y-%m-%d'),
                             close=close,open=close,high=close+10,low=close-10,volume=1000))


@pytest.mark.parametrize('days',[7,30,90])
def test_both_experiments_match_original_baseline_and_do_not_mutate_input(days):
    target=frame(); original=target.copy(deep=True); x=features(target)
    dates=pd.to_datetime(target.date)
    endpoints=dates.searchsorted(dates.shift(-1)+pd.Timedelta(days=days))
    ix=np.flatnonzero((endpoints<len(target)) & x.notna().all(axis=1).to_numpy())
    returns=target.close.iloc[endpoints[ix]].to_numpy()/target.close.iloc[ix].to_numpy()-1
    labels=np.where(returns>0,2,np.where(returns<0,0,1))
    model=make_pipeline(StandardScaler(),LogisticRegression(max_iter=2000,random_state=42))
    model.fit(x.iloc[ix],labels)
    expected=np.zeros(3);expected[model[-1].classes_]=model.predict_proba(x.iloc[[-1]])[0]
    many=train_past('005930',[],{'005930':target},days)
    assert list(many['probabilities'].values())==pytest.approx(expected)
    assert many['latest_label_date']<=target.date.iloc[-1]
    single=logistic_before(target,'2026-01-01',days)
    if len(set(labels))==3:
        assert single['probabilities']==many['probabilities']
        assert single['expected_return_pct']==many['expected_return_pct']
    else: assert single['status']=='missing_training_class'
    pd.testing.assert_frame_equal(target,original)


def test_shared_fit_rejects_unsorted_dates_and_handles_missing_latest_features():
    target=frame()
    with pytest.raises(ValueError): fit_past_returns(target.iloc[::-1],features(target),7)
    x=features(target);x.iloc[-1,0]=np.nan
    assert fit_past_returns(target,x,7)['status']=='insufficient_history'


def test_multi_horizon_reuses_prepared_features(monkeypatch):
    import scripts.top50_experiment as experiment
    target=frame();past={'005930':target}
    matrix=experiment.feature_matrix('005930',[],past)
    expected={days:experiment.train_past('005930',[],past,days) for days in [7,30,90]}
    def unexpected(*args): raise AssertionError('Feature matrix recomputed')
    monkeypatch.setattr(experiment,'feature_matrix',unexpected)
    for days in [7,30,90]:
        assert experiment.train_past('005930',[],past,days,matrix=matrix)==expected[days]

"""Causal daily-price experiment. No broker or order imports."""
import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from defusedxml import ElementTree
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, log_loss
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

FEATURES = ['return_1','return_5','return_20','ma5_distance','ma20_distance',
            'volatility_20','volume_ratio','range_ratio']
LABELS = ['down','flat','up']


def parse_naver(body, years=5, now=None):
    now=now or datetime.now(ZoneInfo('Asia/Seoul'))
    if not now.tzinfo:raise ValueError('시간대가 필요합니다')
    now=now.astimezone(ZoneInfo('Asia/Seoul'))
    root=ElementTree.fromstring(body.decode('euc-kr').encode('utf-8').replace(b'EUC-KR',b'UTF-8'))
    rows=[]
    for item in root.findall('.//item'):
        values=item.attrib['data'].split('|')
        date=datetime.strptime(values[0],'%Y%m%d').date()
        # Exclude today's unfinished daily bar, and all provider future rows.
        if date>now.date() or (date==now.date() and (now.hour,now.minute)<(15,30)):continue
        if date<now.date()-timedelta(days=365*years+2):continue
        nums=[int(v) for v in values[1:]]
        if len(nums)!=5 or any(x<=0 for x in nums[:4]) or nums[4]<0:continue
        rows.append({'date':date.isoformat(),'open':nums[0],'high':nums[1],'low':nums[2],'close':nums[3],'volume':nums[4]})
    df=pd.DataFrame(rows)
    if df.empty:raise ValueError('사용 가능한 일봉이 없습니다')
    df=df.sort_values('date').reset_index(drop=True)
    if df['date'].duplicated().any():raise ValueError('중복 일봉 날짜')
    if ((df.high<df[['open','close','low']].max(axis=1)) | (df.low>df[['open','close','high']].min(axis=1))).any():
        raise ValueError('OHLC 가격 범위 불일치')
    return df


def features(df):
    c=df.close.astype(float);v=df.volume.astype(float);ret=c.pct_change()
    return pd.DataFrame({
        'return_1':ret,'return_5':c.pct_change(5),'return_20':c.pct_change(20),
        'ma5_distance':c/c.rolling(5).mean()-1,'ma20_distance':c/c.rolling(20).mean()-1,
        'volatility_20':ret.rolling(20).std(),
        'volume_ratio':v/v.rolling(20).mean().replace(0,np.nan)-1,
        'range_ratio':(df.high-df.low)/c,
    }).replace([np.inf,-np.inf],np.nan)


def split_indices(index,horizon):
    a,b=int(len(index)*0.6),int(len(index)*0.8)
    calibration=index[a:b];test=index[b:]
    train=index[:a];train=train[train+horizon<calibration[0]]
    calibration=calibration[calibration+horizon<test[0]]
    if min(map(len,[train,calibration,test]))<50:raise ValueError('학습·보정·평가 구간의 데이터 부족')
    return train,calibration,test


def probabilities(logits,temperature):
    scaled=logits/temperature
    scaled-=scaled.max(axis=1,keepdims=True)
    p=np.exp(scaled);return p/p.sum(axis=1,keepdims=True)


def reliability(y,p):
    result=[]
    for cls in range(3):
        bins=[]
        for left,right in zip([0,.2,.4,.6,.8],[.2,.4,.6,.8,1.00001]):
            mask=(p[:,cls]>=left)&(p[:,cls]<right)
            if mask.any():bins.append(dict(count=int(mask.sum()),predicted=float(p[mask,cls].mean()),observed=float((y[mask]==cls).mean())))
        result.append({'class':LABELS[cls],'bins':bins})
    return result


def train_experiment(df,output,source_hash,source_url):
    if len(df)<500:raise ValueError('실험에는 최소 500개 일봉이 필요합니다')
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    x=features(df);reports=[]
    for horizon in [1,5]:
        threshold=.01  # Defined before evaluation: +/-1% price return, excluding dividends/costs.
        future=df.close.shift(-horizon)/df.close-1
        y=np.where(future>threshold,2,np.where(future< -threshold,0,1))
        valid=np.flatnonzero(x.notna().all(axis=1)&future.notna())
        tr,ca,te=split_indices(valid,horizon)
        if set(y[tr])!={0,1,2}:raise ValueError('학습 데이터에 세 가지 결과가 모두 필요합니다')
        model=make_pipeline(StandardScaler(),LogisticRegression(C=1,max_iter=2000,random_state=42))
        model.fit(x.iloc[tr],y[tr])
        calibration_logits=model.decision_function(x.iloc[ca])
        candidates=np.linspace(.5,3,51)
        temperature=float(min(candidates,key=lambda t:log_loss(y[ca],probabilities(calibration_logits,t),labels=[0,1,2])))
        pred=probabilities(model.decision_function(x.iloc[te]),temperature)
        freq=np.bincount(y[tr],minlength=3)/len(tr)
        baseline=np.tile(freq,(len(te),1))
        score=float(log_loss(y[te],pred,labels=[0,1,2]));baseline_score=float(log_loss(y[te],baseline,labels=[0,1,2]))
        brier=float(np.mean(np.sum((pred-np.eye(3)[y[te]])**2,axis=1)))
        latest=np.flatnonzero(x.notna().all(axis=1))[-1]
        latest_p=probabilities(model.decision_function(x.iloc[[latest]]),temperature)[0]
        scaler,clf=model.steps[0][1],model.steps[1][1]
        np.savez(output/f'model_{horizon}d.npz',mean=scaler.mean_,scale=scaler.scale_,coef=clf.coef_,intercept=clf.intercept_,classes=clf.classes_,temperature=temperature,features=np.array(FEATURES))
        predictions=pd.DataFrame({'date':df.date.iloc[te].values,'actual':[LABELS[i] for i in y[te]],**{LABELS[i]:pred[:,i] for i in range(3)}})
        predictions.to_csv(output/f'holdout_{horizon}d.csv',index=False)
        reports.append(dict(horizon_trading_days=horizon,threshold_pct=1.0,temperature=temperature,
            train_rows=len(tr),calibration_rows=len(ca),test_rows=len(te),
            train_start=df.date.iloc[tr[0]],train_end=df.date.iloc[tr[-1]],
            calibration_start=df.date.iloc[ca[0]],calibration_end=df.date.iloc[ca[-1]],
            test_start=df.date.iloc[te[0]],test_end=df.date.iloc[te[-1]],
            accuracy=float(accuracy_score(y[te],pred.argmax(axis=1))),
            baseline_accuracy=float(accuracy_score(y[te],baseline.argmax(axis=1))),
            log_loss=score,baseline_log_loss=baseline_score,brier_multiclass=brier,
            beats_baseline_log_loss=score<baseline_score,
            reliability=reliability(y[te],pred),
            latest=dict(as_of=df.date.iloc[latest],probabilities=dict(zip(LABELS,map(float,latest_p))),status='experimental_not_trading_signal')))
    report=dict(symbol='005930',name='삼성전자',model='StandardScaler + multinomial logistic regression + temporal temperature calibration',
        scope='price_only_research',trading_connected=False,rows=len(df),start=df.date.iloc[0],end=df.date.iloc[-1],
        created_at=datetime.now(ZoneInfo('Asia/Seoul')).isoformat(),source_url=source_url,source_sha256=source_hash,
        feature_names=FEATURES,experiments=reports,
        limitations=['뉴스·시장지수·공시 미포함','외부 공개 차트의 수정주가·배당 처리 독립 검증 미완료',
            '평가 구간 한 번으로 일반화·수익성을 입증하지 못함','5일 결과는 서로 겹치므로 평가 사례가 독립적이지 않음',
            '수수료·배당 제외 종가 수익률 분류이며 다음 거래 가격이나 실현 수익률을 예측하지 않음',
            '일봉 종가 확정 후 다음 거래일 종가/5거래일 후 종가를 대상으로 함'])
    (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    return report

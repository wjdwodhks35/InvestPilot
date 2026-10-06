"""Independent historical-data inspection API for the model lab."""
import csv
import io
import math
from datetime import datetime
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix='/api/experiments', tags=['Model lab (experimental)'])

class Dataset(BaseModel):
    csv_text: str = Field(min_length=1, max_length=2_000_000)

@router.get('/status')
def status():
    return dict(mode='research_only', trading_connected=False, training_available=False,
                probability_available=False, message='과거 데이터 검사용 실험 공간입니다. 학습 모델은 아직 없습니다.')

@router.post('/inspect')
def inspect_dataset(data: Dataset):
    reader = csv.DictReader(io.StringIO(data.csv_text))
    required = {'timestamp', 'symbol', 'close', 'volume'}
    if not required <= set(reader.fieldnames or []):
        raise HTTPException(422, '필수 열: timestamp,symbol,close,volume')
    rows = []
    previous = {}
    duplicates = set()
    missing_news = 0
    try:
        for line, row in enumerate(reader, 2):
            if len(rows) >= 10000: raise ValueError('최대 10,000행까지 검사합니다')
            stamp = datetime.fromisoformat(row['timestamp'].replace('Z', '+00:00'))
            if stamp.tzinfo is None: raise ValueError(f'{line}행: timestamp에 시간대가 필요합니다')
            symbol = row['symbol'].strip()
            if not symbol or len(symbol) > 30: raise ValueError(f'{line}행: 종목 코드 오류')
            close, volume = float(row['close']), float(row['volume'])
            if not math.isfinite(close) or close <= 0 or not math.isfinite(volume) or volume < 0:
                raise ValueError(f'{line}행: 가격·거래량 오류')
            key = (symbol, stamp)
            if key in duplicates: raise ValueError(f'{line}행: 같은 종목·시각 중복')
            duplicates.add(key)
            if symbol in previous and stamp <= previous[symbol]:
                raise ValueError(f'{line}행: 종목별 시각 오름차순으로 정렬하세요')
            previous[symbol] = stamp
            title = row.get('news_title', '').strip()
            published = row.get('news_published_at', '').strip()
            if title and not published:
                raise ValueError(f'{line}행: 뉴스 발행시각이 필요합니다')
            if published:
                news_stamp = datetime.fromisoformat(published.replace('Z', '+00:00'))
                if news_stamp.tzinfo is None or news_stamp > stamp:
                    raise ValueError(f'{line}행: 판단 시각 이후 뉴스 또는 뉴스 시간대 누락')
            if not title: missing_news += 1
            rows.append(stamp)
    except (ValueError, TypeError, AttributeError, KeyError) as exc:
        raise HTTPException(422, str(exc)) from exc
    if not rows: raise HTTPException(422, '데이터 행이 없습니다')
    return dict(rows=len(rows), symbols=sorted(previous), start=min(rows).isoformat(),
                end=max(rows).isoformat(), rows_without_news=missing_news,
                status='inspection_only', trading_connected=False,
                warnings=['이 검사는 학습 또는 확률 산출이 아닙니다.',
                          '원본 뉴스의 당시 버전과 실제 공개·수신 시각은 별도로 확인해야 합니다.',
                          '횡보 기준, 예측 기간, 시간순 분할, 확률 보정은 학습 구현 시 설정합니다.'])

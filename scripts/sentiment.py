import pandas as pd
import numpy as np
import os, sys, warnings
warnings.filterwarnings('ignore')

if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, 'stock_data')
LOOKBACK = 60

def load_csv(name):
    path = os.path.join(DATA_DIR, name)
    if not os.path.exists(path):
        print(f'[WARN] {path} not found')
        return None
    return pd.read_csv(path, encoding='utf-8-sig')

def percentile_rank(series, lookback=LOOKBACK):
    scores = np.full(len(series), 50.0, dtype=float)
    for i in range(1, len(series)):
        win_size = min(i, lookback)
        if win_size < 5:
            continue
        win = series.iloc[i-win_size:i]
        less = (win < series.iloc[i]).sum()
        equal = (win == series.iloc[i]).sum()
        scores[i] = (less + 0.5 * equal) / win_size * 100
    return scores

def trend_acceleration(price_series, slope_window=20, accel_window=5):
    """趋势加速度(二阶导): 斜率变化率的百分位. 加速=强转更强, 衰减=强转弱."""
    price = price_series.values.astype(float)
    slopes = np.full(len(price_series), 0.0, dtype=float)
    for i in range(slope_window, len(price_series)):
        y = price[i-slope_window:i]
        x = np.arange(slope_window)
        slopes[i] = np.polyfit(x, y, 1)[0]
    accel = np.full(len(price_series), 0.0, dtype=float)
    for i in range(accel_window, len(price_series)):
        accel[i] = slopes[i] - slopes[i-accel_window]
    return percentile_rank(pd.Series(accel))

def score_position_sz(price_series, levels):
    """上证VWAP位置: 近支撑=75 / 近压力=25 / 突破更高."""
    levels = sorted(set(l for l in levels if pd.notna(l)))
    scores = np.full(len(price_series), 50.0, dtype=float)
    for i in range(len(price_series)):
        p = price_series.iloc[i]
        if pd.isna(p) or not levels:
            continue
        sup, res = None, None
        for l in levels:
            if l < p: sup = l
            elif l > p and res is None: res = l
        if sup is not None and res is not None:
            pos = (p - sup) / (res - sup)
            scores[i] = np.clip(75 - pos * 50, 0, 100)
        elif sup is not None:
            scores[i] = 50.0  # 突破全部VWAP，无上方参照，持中性
        elif res is not None:
            dist = (res - p) / p
            scores[i] = np.clip(25 - dist * 100, 0, 100)
    return scores

def main():
    market = load_csv('涨跌个数_市场.csv')
    volume = load_csv('全市场成交额.csv')
    if market is None or volume is None:
        print('Missing required input files')
        sys.exit(1)

    market['date'] = pd.to_datetime(market['date'])
    volume['date'] = pd.to_datetime(volume['日期'])

    df = market[['date', 'limit_up', 'limit_down', 'median_change']].copy()
    df = df.merge(volume[['date', '成交额(元)', '成交额60日均值']], on='date', how='left')

    # 百分位评分 (涨停、中位数: 极端反转, 越高越好→极高分预警/极低分抄底)
    df['limit_up_pct'] = percentile_rank(df['limit_up'].astype(float))
    df['median_pct'] = percentile_rank(df['median_change'].astype(float))
    for col in ['limit_up_pct', 'median_pct']:
        norm = (df[col] - 50) / 50
        score_col = col.replace('_pct', '_score')
        df[score_col] = np.clip(50 - np.power(norm, 3) * 50, 0, 100)
    df['volume_score'] = percentile_rank(df['成交额(元)'].astype(float))

    # 趋势加速度 + SMA60 (从全量历史计算)
    sz_full = load_csv('历史价格_上证指数.csv')
    if sz_full is not None:
        sz_full['date'] = pd.to_datetime(sz_full['日期'])
        sz_full = sz_full.sort_values('date')
        sz_full['sma60'] = sz_full['收盘'].astype(float).rolling(60).mean()
        sz_full['ma_score'] = trend_acceleration(sz_full['收盘'].astype(float))
        df = df.merge(sz_full[['date', '收盘', 'ma_score', 'sma60']], on='date', how='left')
        df['ma_score'] = df['ma_score'].fillna(50.0)
    else:
        df['ma_score'] = 50.0
        df['sma60'] = np.nan

    ps_sz = load_csv('压力支撑_上证指数.csv')
    if ps_sz is not None and '收盘' in df.columns:
        levels = pd.to_numeric(ps_sz['VWAP值'], errors='coerce').dropna().tolist()
        s = score_position_sz(df['收盘'].astype(float), levels)
        df['position_score'] = s
    else:
        df['position_score'] = 50.0

    # 指数强弱分界 (状态机: 强+量回落直接→弱)
    above_ma = (df['收盘'] > df['sma60']).fillna(False)
    above_vol = (df['成交额(元)'].astype(float) > df['成交额60日均值'].astype(float)).fillna(False)
    zone = np.full(len(df), '弱', dtype=object)
    adj = np.full(len(df), -10, dtype=int)
    for i in range(len(df)):
        if above_ma.iloc[i] and above_vol.iloc[i]:
            zone[i] = '强+量'
            adj[i] = 10
        elif i > 0 and zone[i-1] == '强+量':
            zone[i] = '弱'
            adj[i] = -10
        elif above_ma.iloc[i]:
            zone[i] = '强'
            adj[i] = 5
    df['zone'] = zone
    df['zone_adjust'] = adj

    # 五维二值评分 (±20/0, 总分 -100~100)
    df['dim_limit_up'] = np.select(
        [df['limit_up_score'] >= 75, df['limit_up_score'] <= 25], [20, -20], default=0)
    df['dim_median'] = np.select(
        [df['median_score'] >= 75, df['median_score'] <= 25], [20, -20], default=0)
    df['dim_trend'] = np.where(above_ma, 20, -20)
    df['dim_volume'] = np.where(above_vol, 20, -20)
    df['dim_position'] = np.select(
        [df['position_score'] >= 60, df['position_score'] <= 40], [20, -20], default=0)

    sentiment_raw = df['dim_limit_up'] + df['dim_median'] + df['dim_trend'] + df['dim_volume'] + df['dim_position']
    df['sentiment'] = (sentiment_raw + 100) / 2  # -100~100 → 0~100
    df['sentiment_raw'] = sentiment_raw

    def signal(s):
        if s >= 80: return '极好'
        if s >= 65: return '良好'
        if s >= 50: return '中性偏好'
        if s >= 35: return '中性偏差'
        if s >= 20: return '偏差'
        return '极差'

    df['signal'] = df['sentiment'].apply(signal)

    out = df[['date', 'limit_up_score', 'median_score', 'volume_score',
              'ma_score', 'position_score', 'zone', 'zone_adjust',
              'dim_limit_up', 'dim_median', 'dim_trend', 'dim_volume', 'dim_position',
              'sentiment_raw', 'sentiment', 'signal']].copy()
    out['date'] = out['date'].dt.strftime('%Y-%m-%d')

    out_path = os.path.join(DATA_DIR, '情绪指数.csv')
    out.to_csv(out_path, index=False, encoding='utf-8-sig')
    print(f'情绪指数已生成 ({len(out)} rows)')
    print(f'最新: {out.iloc[-1]["date"]}  sentiment={out.iloc[-1]["sentiment"]:.1f}  signal={out.iloc[-1]["signal"]}')

if __name__ == '__main__':
    main()

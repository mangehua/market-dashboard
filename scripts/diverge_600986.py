"""
浙文互联 (600986) 背离分析
- 涨跌背离(反向) vs (市场中位, 游戏ETF)
- 涨跌幅背离(同向急跌/急涨) vs (市场中位, 游戏ETF)
"""
import pandas as pd
import numpy as np
import os, sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, '..', 'stock_data')

def load_stock(name):
    df = pd.read_csv(f'{DATA_DIR}/历史价格_{name}.csv', encoding='utf-8-sig')
    df['日期'] = pd.to_datetime(df['日期'])
    df = df.sort_values('日期').reset_index(drop=True)
    df['涨跌幅'] = df['收盘'].pct_change() * 100
    return df

def load_median():
    df = pd.read_csv(f'{DATA_DIR}/涨跌个数_市场.csv', encoding='utf-8-sig')
    df['日期'] = pd.to_datetime(df['date'])
    df = df.sort_values('日期').reset_index(drop=True)
    return df[['日期', 'median_change']].rename(columns={'median_change': 'ref_pct'})

def analyze_diverge(asset_df, ref_df, name_a, name_r, k=0.8, hold=1):
    """涨跌背离(反向)：asset涨跌方向 vs ref涨跌方向相反时触发"""
    merged = pd.merge(asset_df[['日期', '涨跌幅']], ref_df[['日期', 'ref_pct']], on='日期', how='inner')
    merged = merged.dropna().reset_index(drop=True)
    merged['asset_dir'] = np.sign(merged['涨跌幅'])
    merged['ref_dir'] = np.sign(merged['ref_pct'])
    merged['diff'] = merged['涨跌幅'] - merged['ref_pct']

    # 自适应阈值
    pos = merged[merged['diff'] > 0]['diff']
    neg = merged[merged['diff'] < 0]['diff']
    thresh_pos = k * pos.std() if len(pos) > 1 else 2.0
    thresh_neg = k * neg.std() if len(neg) > 1 else 2.0

    results = []
    for i in range(len(merged) - hold):
        row = merged.iloc[i]
        # 涨跌背离(反向) — asset和ref方向相反
        if row['asset_dir'] != 0 and row['ref_dir'] != 0 and row['asset_dir'] != row['ref_dir']:
            is_long = row['asset_dir'] == -1  # asset跌、ref涨 → 做多
            fwd = merged.iloc[i + hold]
            asset_ret = fwd['涨跌幅']
            ref_ret = fwd['ref_pct']
            excess = asset_ret - ref_ret  # 补涨/补跌
            results.append({
                'date': row['日期'],
                'type': '做多' if is_long else '做空',
                'asset_chg': row['涨跌幅'],
                'ref_chg': row['ref_pct'],
                'diff': row['diff'],
                'fwd_asset_chg': asset_ret,
                'fwd_ref_chg': ref_ret,
                'excess': excess,
                'win_abs': 1 if (is_long and asset_ret > 0) or (not is_long and asset_ret < 0) else 0,
                'win_excess': 1 if (is_long and excess > 0) or (not is_long and excess < 0) else 0,
            })

    df_r = pd.DataFrame(results)
    if len(df_r) == 0:
        return {'n_signals': 0, 'k': k, 'hold': hold}

    def grp_stats(sub):
        return {
            'n': len(sub),
            'win_abs': sub['win_abs'].mean() * 100,
            'win_excess': sub['win_excess'].mean() * 100,
            'avg_abs': sub['fwd_asset_chg'].mean(),
            'avg_excess': sub['excess'].mean(),
        }

    stats = {'n_signals': len(df_r), 'k': k, 'hold': hold, 'thresholds': (thresh_neg, thresh_pos)}
    for t in ['做多', '做空']:
        sub = df_r[df_r['type'] == t]
        stats[t] = grp_stats(sub) if len(sub) > 0 else {'n': 0, 'win_abs': 0, 'win_excess': 0, 'avg_abs': 0, 'avg_excess': 0}
    stats['all_做多'] = stats.pop('做多')
    stats['all_做空'] = stats.pop('做空')

    # 打印
    def fmt(s, label):
        if s['n'] == 0:
            return f'    {label}: 0次'
        return f'    {label}: {s["n"]}次 | 绝对胜率{s["win_abs"]:.0f}% | 补涨胜率{s["win_excess"]:.0f}% | 绝对均值{s["avg_abs"]:+.2f}% | 补涨均值{s["avg_excess"]:+.2f}%'

    print(f'\n  [{name_a} vs {name_r}] 涨跌背离(反向) k={k} hold={hold}d (阈值neg={thresh_neg:.2f}%, pos={thresh_pos:.2f}%)')
    print(f'    总信号: {len(df_r)}次')
    print(fmt(stats['all_做多'], '做多'))
    print(fmt(stats['all_做空'], '做空'))
    return stats

def analyze_magnitude(asset_df, ref_df, name_a, name_r, k=0.8, hold=1):
    """涨跌幅背离(同向)：asset和ref同方向，但asset涨跌幅显著大于/小于ref"""
    merged = pd.merge(asset_df[['日期', '涨跌幅']], ref_df[['日期', 'ref_pct']], on='日期', how='inner')
    merged = merged.dropna().reset_index(drop=True)
    merged['asset_dir'] = np.sign(merged['涨跌幅'])
    merged['ref_dir'] = np.sign(merged['ref_pct'])
    merged['diff'] = merged['涨跌幅'] - merged['ref_pct']

    pos = merged[merged['diff'] > 0]['diff']
    neg = merged[merged['diff'] < 0]['diff']
    thresh_pos = k * pos.std() if len(pos) > 1 else 2.0
    thresh_neg = k * neg.std() if len(neg) > 1 else 2.0

    results = []
    for i in range(len(merged) - hold):
        row = merged.iloc[i]
        # 同向且asset偏离ref超过阈值
        if row['asset_dir'] != 0 and row['ref_dir'] != 0 and row['asset_dir'] == row['ref_dir']:
            if row['diff'] > thresh_pos:
                # asset急涨 → ref也涨，但asset涨更多 → 做空(回归)
                is_long = False
            elif row['diff'] < -thresh_neg:
                # asset急跌 → ref也跌，但asset跌更多 → 做多(回归)
                is_long = True
            else:
                continue

            fwd = merged.iloc[i + hold]
            asset_ret = fwd['涨跌幅']
            ref_ret = fwd['ref_pct']
            excess = asset_ret - ref_ret
            results.append({
                'date': row['日期'],
                'type': '做多' if is_long else '做空',
                'asset_chg': row['涨跌幅'],
                'ref_chg': row['ref_pct'],
                'diff': row['diff'],
                'fwd_asset_chg': asset_ret,
                'fwd_ref_chg': ref_ret,
                'excess': excess,
                'win_abs': 1 if (is_long and asset_ret > 0) or (not is_long and asset_ret < 0) else 0,
                'win_excess': 1 if (is_long and excess > 0) or (not is_long and excess < 0) else 0,
            })

    df_r = pd.DataFrame(results)
    if len(df_r) == 0:
        return {'n_signals': 0, 'k': k, 'hold': hold}

    def grp_stats(sub):
        return {
            'n': len(sub),
            'win_abs': sub['win_abs'].mean() * 100,
            'win_excess': sub['win_excess'].mean() * 100,
            'avg_abs': sub['fwd_asset_chg'].mean(),
            'avg_excess': sub['excess'].mean(),
        }

    stats = {'n_signals': len(df_r), 'k': k, 'hold': hold, 'thresholds': (thresh_neg, thresh_pos)}
    for t in ['做多', '做空']:
        sub = df_r[df_r['type'] == t]
        stats[t] = grp_stats(sub) if len(sub) > 0 else {'n': 0, 'win_abs': 0, 'win_excess': 0, 'avg_abs': 0, 'avg_excess': 0}
    stats['all_做多'] = stats.pop('做多')
    stats['all_做空'] = stats.pop('做空')

    def fmt(s, label):
        if s['n'] == 0:
            return f'    {label}: 0次'
        return f'    {label}: {s["n"]}次 | 绝对胜率{s["win_abs"]:.0f}% | 补涨胜率{s["win_excess"]:.0f}% | 绝对均值{s["avg_abs"]:+.2f}% | 补涨均值{s["avg_excess"]:+.2f}%'

    print(f'\n  [{name_a} vs {name_r}] 涨跌幅背离(同向) k={k} hold={hold}d (阈值neg={thresh_neg:.2f}%, pos={thresh_pos:.2f}%)')
    print(f'    总信号: {len(df_r)}次')
    print(fmt(stats['all_做多'], '做多'))
    print(fmt(stats['all_做空'], '做空'))
    return stats


def filter_last_n(asset_df, ref_df, n):
    """取两个df共有的最近n个交易日"""
    m = pd.merge(asset_df[['日期']], ref_df[['日期']], on='日期', how='inner')
    m = m.sort_values('日期')
    take = min(n, len(m))
    cutoff = m.iloc[-take]['日期']
    asset_df = asset_df[asset_df['日期'] >= cutoff].copy()
    ref_df = ref_df[ref_df['日期'] >= cutoff].copy()
    return asset_df, ref_df

def main():
    import sys
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    stock_name = sys.argv[2] if len(sys.argv) > 2 else '浙文互联'

    print('=' * 60)
    print(f'{stock_name} 背离分析')
    print('=' * 60)

    asset = load_stock(stock_name)
    median = load_median()
    game_etf = load_stock('游戏ETF')
    game_etf = game_etf[['日期', '涨跌幅']].rename(columns={'涨跌幅': 'ref_pct'})

    refs = [
        ('市场中位', median),
        ('游戏ETF',  game_etf),
    ]
    ks = [0.6, 0.8, 1.0, 1.2]
    holds = [1, 3]

    if days:
        print(f'\n限制最近 {days} 个交易日')
        asset, median = filter_last_n(asset, median, days)
        _, game_etf = filter_last_n(asset, game_etf, days)

    print(f'\n数据范围: {asset["日期"].min().date()} ~ {asset["日期"].max().date()}, {len(asset)}条')

    for rf_name, rf_df in refs:
        print(f'\n{"─" * 50}')
        print(f'参考系: {rf_name}')
        print(f'{"─" * 50}')

        for k in ks:
            for h in holds:
                analyze_diverge(asset, rf_df, stock_name, rf_name, k=k, hold=h)

        print()
        for k in ks:
            for h in holds:
                analyze_magnitude(asset, rf_df, stock_name, rf_name, k=k, hold=h)


if __name__ == '__main__':
    main()

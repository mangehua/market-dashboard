import os
import pandas as pd
import sys
import json

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, '..', 'config.json')
with open(CONFIG_PATH, encoding='utf-8') as f:
    CONFIG = json.load(f)

window = int(sys.argv[1]) if len(sys.argv) > 1 else 60
symbol = sys.argv[2] if len(sys.argv) > 2 else '上证指数'

try:
    base = os.path.join(SCRIPT_DIR, '..', CONFIG['data']['output_dir'])
    file_path = f'{base}/历史价格_{symbol}.csv'
    
    if not os.path.exists(file_path):
        print(f'Error: file not found: {file_path}')
        sys.exit(1)
    
    df = pd.read_csv(file_path, encoding='utf-8-sig')
    
    # 统一列名（可能有成交额列）
    cols = list(df.columns)
    if '日' not in cols and '日期' in cols:
        # 重命名列
        df = df.rename(columns={'日期':'日', '股票代码':'代码'})
    
    if '成交量' not in df.columns:
        if len(df.columns) >= 7:
            df = df.iloc[:, :7]  # 只取前7列
            df.columns = ['日','代码','收盘','开盘','最高','最低','成交量']
    
    df['日'] = pd.to_datetime(df['日'])
    df = df.sort_values('日').reset_index(drop=True)
    
    # VWAP = sum(典型价格 × 成交量) / sum(成交量)
    df['典型价格'] = (df['最高'] + df['最低'] + df['收盘']) / 3
    df['price_vol'] = df['典型价格'] * df['成交量']
    df['vwap'] = df['price_vol'].rolling(window).sum() / df['成交量'].rolling(window).sum()
    
    result = df[['日', 'vwap']].dropna().tail(60)
    
    lines = ['日,移动VWAP']
    for _, r in result.iterrows():
        lines.append(r['日'].strftime('%Y-%m-%d') + ',' + str(round(r['vwap'], 3)))
    
    out_path = f'{base}/移动加权强弱线_{symbol}.csv'
    with open(out_path, 'w', encoding='utf-8-sig') as f:
        f.write('\n'.join(lines))
    print(f'OK: {symbol} ({window}天移动VWAP)')
except Exception as e:
    print(f'Error: {e}')
    sys.exit(1)

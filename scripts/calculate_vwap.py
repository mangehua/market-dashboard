import pandas as pd
import os
import sys
import json

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, '..', 'config.json')
with open(CONFIG_PATH, encoding='utf-8') as f:
    CONFIG = json.load(f)

def calculate_vwap(df, start_date):
    """计算VWAP（使用成交量，非成交额），df需含日期、最高、最低、收盘、成交量"""
    df = df.copy()
    print(f'VWAP计算: 共 {len(df)} 行, 起始>={start_date}')
    
    df['日期'] = pd.to_datetime(df['日期'])
    mask = df['日期'] >= pd.to_datetime(start_date)
    print(f'匹配 {mask.sum()} 行')
    df_masked = df[mask].copy()
    
    df_masked['典型价格'] = (df_masked['最高'] + df_masked['最低'] + df_masked['收盘']) / 3
    df_masked['price_vol'] = df_masked['典型价格'] * df_masked['成交量']
    vwap = df_masked['price_vol'].sum() / df_masked['成交量'].sum()
    print(f'VWAP from {start_date} = {vwap:.3f}')
    return vwap

def main():
    data_dir = os.path.join(SCRIPT_DIR, '..', CONFIG['data']['output_dir'])
    vwap_config = CONFIG.get('vwap', {})
    
    for name, cfg in vwap_config.items():
        file_path = os.path.join(data_dir, cfg['file'])
        if not os.path.exists(file_path):
            print(f'Skip {name}: file not found')
            continue
            
        df = pd.read_csv(file_path, encoding='utf-8-sig')
        print(f'Read {len(df)} rows from {cfg["file"]}')
        
        # 统一列名
        if '成交量' not in df.columns:
            df.columns = ['日期','股票代码','收盘','开盘','最高','最低','成交量','成交额']
            df = df[['日期','股票代码','收盘','开盘','最高','最低','成交量']]
        
        df_dates = pd.to_datetime(df['日期'])
        latest = df_dates.max()
        
        lines = ['指标,起始日期,VWAP值,最新日期']
        seen_starts = set()
        seq = 0
        for start in cfg.get('periods', []):
            if start in seen_starts:
                continue
            seen_starts.add(start)
            seq += 1
            vwap = calculate_vwap(df, start)
            lines.append(f"T{seq},{start},{round(vwap, 3)},{latest.strftime('%Y-%m-%d')}")
        
        out_path = os.path.join(data_dir, f"压力支撑_{name}.csv")
        with open(out_path, 'w', encoding='utf-8-sig') as f:
            f.write('\n'.join(lines))
        print(f"OK: {name}")

if __name__ == '__main__':
    main()

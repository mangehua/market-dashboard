#!/usr/bin/env python3
"""
A股股价数据获取脚本
三种模式:
1. 默认(非增量): 读取本地数据，从配置的开始日期起
2. 增量模式(-i): 检查新数据则追加
3. 补齐模式(--fill): 对特定日期范围进行补齐

数据源智能选择:
- 优先检查TDX是否有最新数据（最近N天，N从config.json读取）
- TDX有最新数据 -> 用TDX
- TDX无/过期 -> 切换API
"""

import argparse
import json
import os
import struct
import time
from datetime import datetime, timedelta
import pandas as pd
import requests
import glob

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, '..', 'config.json')
with open(CONFIG_PATH, encoding='utf-8') as f:
    CONFIG = json.load(f)

DATA_DIR = os.path.join(SCRIPT_DIR, '..', CONFIG['data']['output_dir'])
TDX_PATH = CONFIG['sources']['tongdaxin']
START_DATE = CONFIG['data'].get('start_date', '2024-09-01')
START_DATE_INT = int(START_DATE.replace('-', ''))
CHECK_DAYS = CONFIG['data'].get('check_days', 5)
os.makedirs(DATA_DIR, exist_ok=True)

SESSION = requests.Session()
SESSION.trust_env = False

STOCKS = CONFIG['stocks']

def get_tdx_index_code(code):
    """标准股票码 -> TDX指数码"""
    return {'000001': '999999', '399001': '399001', '899050': '899050'}.get(code, code)

def get_market_indices_amounts(date_int=None):
    """获取沪深京三个市场指数的成交额（元）"""
    indices = {
        '000001': ('sh', '上证指数'),
        '399001': ('sz', '深证成指'),
        '899050': ('bj', '北证50')
    }
    
    results = {}
    for code, (market, name) in indices.items():
        tdx_code = get_tdx_index_code(code)
        filepath = os.path.join(TDX_PATH, market, 'lday', f'{market}{tdx_code}.day')
        if not os.path.exists(filepath):
            continue
        
        try:
            with open(filepath, 'rb') as f:
                f.seek(-32, 2)
                rec = f.read(32)
                if len(rec) == 32:
                    amount = struct.unpack('f', rec[20:24])[0]  # 成交额（元）
                    results[name] = amount
        except Exception:
            pass
    
    return results

def generate_market_amount_csv():
    """生成全市场成交额CSV（沪深京指数成交额之和）"""
    print('\n=== 生成全市场成交额数据 ===')
    
    indices = [
        ('sh', '999999', '上证指数'),
        ('sz', '399001', '深证成指'),
        ('bj', '899050', '北证50')
    ]
    
    all_dates = {}
    for market, code, name in indices:
        fp = os.path.join(TDX_PATH, market, 'lday', f'{market}{code}.day')
        if not os.path.exists(fp):
            print(f'{name}文件不存在: {fp}')
            continue
        
        dates = {}
        with open(fp, 'rb') as f:
            f.seek(0, 2)  # 移动到文件末尾
            size = f.tell() # 获取文件大小
            for i in range(0, size, 32):
                f.seek(i)
                rec = f.read(32)
                if len(rec) < 32:
                    break
                date_int = int.from_bytes(rec[0:4], 'little')
                amount = struct.unpack('f', rec[20:24])[0]
                dates[date_int] = amount
        
        print(f'{name}: {len(dates)}条')
        all_dates[name] = dates
    
    if not all_dates:
        print('无指数数据')
        return
    
    # 取上证指数的日期为基准（共同交易日），保留120日，前60日为60日均值提供回看缓冲
    base_dates = sorted(all_dates.get('上证指数', {}).keys())
    base_dates = base_dates[-120:] if len(base_dates) > 120 else base_dates
    
    # 生成CSV
    rows = []
    for date_int in base_dates:
        if date_int < START_DATE_INT:
            continue
        
        total = 0
        for name, dates in all_dates.items():
            if date_int in dates:
                total += dates[date_int]
        
        year = date_int // 10000
        month = (date_int % 10000) // 100
        day = date_int % 100
        date_str = f'{year}-{month:02d}-{day:02d}'
        rows.append(f'{date_str},{total:.2f}')
    
    # 生成CSV（含60日均值：rolling窗口，后续sentiment只取后60行）
    amounts = [float(r.split(',')[1]) for r in rows]
    ma60 = []
    for i in range(len(amounts)):
        start = max(0, i - 59)
        window = amounts[start:i+1]
        ma60.append(sum(window) / len(window))
    
    output_file = os.path.join(DATA_DIR, '全市场成交额.csv')
    with open(output_file, 'w', encoding='utf-8-sig') as f:
        f.write('日期,成交额(元),成交额60日均值\n')
        for i, row in enumerate(rows):
            f.write(f'{row},{ma60[i]:.2f}\n')
    
    print(f'已保存: {output_file}, 共{len(rows)}条')
    if rows:
        latest = rows[-1].split(',')
        print(f'最新: {latest[0]} 成交额={float(latest[1])/100000000:.2f}亿')

# ============================================================
# 工具函数
# ============================================================

def get_name(code):
    return STOCKS.get(code, {}).get('name', code)

def get_api_code(code):
    # 指数统一用sh市场
    if code in STOCKS and STOCKS[code].get('index', False):
        return f'sh{code}'
    if code.startswith('6'):
        return f'sh{code}'
    return f'sz{code}'

def get_tdx_filepath(code):
    """根据股票代码返回TDX文件路径"""
    # 先检查config，看是否为指数
    if code in STOCKS and STOCKS[code].get('index', False):
        market = 'sh'
        tdx_code = get_tdx_index_code(code)
    elif code.startswith('6'):
        market = 'sh'
        tdx_code = code
    elif code.startswith('4') or code.startswith('8'):
        market = 'bj'
        tdx_code = code
    else:
        market = 'sz'
        tdx_code = code
    return os.path.join(TDX_PATH, market, 'lday', f'{market}{tdx_code}.day')

def date_int_to_str(date_int):
    year = date_int // 10000
    month = (date_int % 10000) // 100
    day = date_int % 100
    return f'{year}-{month:02d}-{day:02d}'

def get_tdx_latest_date(filepath):
    """获取TDX文件最新日期（直接读最后32字节）"""
    if not os.path.exists(filepath):
        return None
    try:
        with open(filepath, 'rb') as f:
            f.seek(-32, 2)  # 移到最后一条记录
            data = f.read(32)
            if len(data) == 32:
                date_int = int.from_bytes(data[0:4], 'little')
                return date_int_to_str(date_int)
    except Exception:
        pass
    return None

# ============================================================
# TDX数据读取模块
# ============================================================

def read_tdx_records(filepath, n=None):
    """从TDX文件读取记录，n=None读全部，否则读最后n条"""
    if not os.path.exists(filepath):
        return None
    records = []
    try:
        with open(filepath, 'rb') as f:
            if n is not None:
                # 只读最后n条
                f.seek(0, 2)
                size = f.tell()
                record_size = 32
                num_records = size // record_size
                start = max(0, num_records - n) * record_size
                f.seek(start)
                data = f.read()
            else:
                data = f.read()
        
        for i in range(0, len(data), 32):
            rec = data[i:i+32]
            if len(rec) < 32:
                break
            date_int = int.from_bytes(rec[0:4], 'little')
            open_price = int.from_bytes(rec[4:8], 'little') / 100.0
            high = int.from_bytes(rec[8:12], 'little') / 100.0
            low = int.from_bytes(rec[12:16], 'little') / 100.0
            close = int.from_bytes(rec[16:20], 'little') / 100.0
            amount = struct.unpack('f', rec[20:24])[0]  # 成交额（元），20-23字节，float
            volume = int.from_bytes(rec[24:28], 'little')  # 成交量（股），24-27字节
            records.append((date_int, open_price, high, low, close, volume, amount))
    except Exception:
        return None
    return records if records else None

def tdx_to_dataframe(records, code):
    """将TDX记录转为DataFrame，成交量=股，成交额=元"""
    rows = []
    for date_int, o, h, l, c, vol, amt in records:
        date_str = date_int_to_str(date_int)
        rows.append([date_str, code, c, o, h, l, vol, amt])
    df = pd.DataFrame(rows, columns=['日期', '股票代码', '收盘', '开盘', '最高', '最低', '成交量', '成交额'])
    df['日期'] = pd.to_datetime(df['日期'])
    df = df.sort_values('日期')
    df['日期'] = df['日期'].dt.strftime('%Y-%m-%d')
    return df

def fetch_from_tdx(code, days=500):
    """从TDX读取指定天数数据"""
    filepath = get_tdx_filepath(code)
    records = read_tdx_records(filepath, n=days)
    if not records:
        return None
    return tdx_to_dataframe(records, code)

def should_use_tdx(code, local_latest_date=None):
    """
    判断是否应该使用TDX数据源
    逻辑:
    1. 获取TDX最新日期
    2. 如果有本地数据，只有TDX > 本地才用TDX（避免TDX过期仍使用）
    3. 如果没有本地数据，只要TDX有数据就用
    返回: (should_use, tdx_latest_str)
    """
    filepath = get_tdx_filepath(code)
    tdx_latest_str = get_tdx_latest_date(filepath)
    
    if not tdx_latest_str:
        print(f'  TDX文件不存在或无数据')
        return False, None
    
    # 没有本地数据，只要TDX有数据就用
    if local_latest_date is None:
        print(f'  TDX有数据，最新: {tdx_latest_str}')
        return True, tdx_latest_str
    
    # 比较TDX和本地数据的新鲜度
    tdx_latest = datetime.strptime(tdx_latest_str, '%Y-%m-%d')
    local_latest = datetime.strptime(local_latest_date, '%Y-%m-%d')
    
    if tdx_latest > local_latest:
        print(f'  TDX数据更新: {tdx_latest_str} > 本地{local_latest_date}')
        return True, tdx_latest_str
    else:
        # TDX <= 本地，说明TDX无新数据或已过期
        print(f'  TDX数据不更新: {tdx_latest_str} <= 本地{local_latest_date}，切换API')
        return False, tdx_latest_str

# ============================================================
# API数据获取模块
# ============================================================

def safe_fetch(api_code, param):
    url = 'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get'
    params = {'param': param}
    try:
        r = SESSION.get(url, params=params, timeout=15)
        data = json.loads(r.text)
        if 'data' not in data or api_code not in data['data']:
            return []
        return [row for row in data['data'][api_code]['day'] if len(row) == 6]
    except (json.JSONDecodeError, KeyError, Exception) as e:
        print(f"  API error: {e}")
        return []

def fetch_from_api(code, days=100):
    api_code = get_api_code(code)
    param = f'{api_code},day,,,{days},qfqa'
    all_data = safe_fetch(api_code, param)
    
    if not all_data:
        return None
    
    df = pd.DataFrame(all_data, columns=['日期', '开盘', '收盘', '最高', '最低', '成交量'])
    df['股票代码'] = code
    df['成交额'] = 0  # API无成交额字段，补0保持与TDX一致
    df = df[['日期', '股票代码', '收盘', '开盘', '最高', '最低', '成交量', '成交额']]
    df['日期'] = pd.to_datetime(df['日期'])
    df = df.sort_values('日期')
    df['日期'] = df['日期'].dt.strftime('%Y-%m-%d')
    return df


# ============================================================
# 本地数据管理模块
# ============================================================

def load_local(name):
    path = f'{DATA_DIR}/历史价格_{name}.csv'
    if os.path.exists(path):
        return pd.read_csv(path)
    return None

def get_local_latest(name):
    df = load_local(name)
    if df is not None and len(df) > 0:
        return df['日期'].max()
    return None

def merge_incremental(df_new, csv_path):
    if not os.path.exists(csv_path):
        df_new.to_csv(csv_path, index=False, encoding='utf-8-sig')
        print(f'新建文件，保存 {len(df_new)} 条')
        return
    
    df_old = pd.read_csv(csv_path)
    df_old['日期'] = pd.to_datetime(df_old['日期'])
    df_new['日期'] = pd.to_datetime(df_new['日期'])
    
    last_date = df_old['日期'].max()
    new_rows = df_new[df_new['日期'] > last_date]
    
    if len(new_rows) == 0:
        print('无新数据可追加')
        return
    
    df_merged = pd.concat([df_old, new_rows]).sort_values('日期')
    df_merged['日期'] = df_merged['日期'].dt.strftime('%Y-%m-%d')
    df_merged.to_csv(csv_path, index=False, encoding='utf-8-sig')
    print(f'新增 {len(new_rows)} 条，合并后共 {len(df_merged)} 条')

def fill_range(df_api, csv_path, start_date, end_date):
    if not os.path.exists(csv_path):
        df_api.to_csv(csv_path, index=False, encoding='utf-8-sig')
        print(f'新建文件，保存 {len(df_api)} 条')
        return
    
    df_old = pd.read_csv(csv_path)
    df_old['日期'] = pd.to_datetime(df_old['日期'])
    df_api['日期'] = pd.to_datetime(df_api['日期'])
    
    mask = (df_api['日期'] >= start_date) & (df_api['日期'] <= end_date)
    fill_data = df_api[mask]
    
    if len(fill_data) == 0:
        print(f'{start_date} ~ {end_date} 范围内无数据')
        return
    
    df_old = df_old[~df_old['日期'].isin(fill_data['日期'])]
    df_merged = pd.concat([df_old, fill_data]).sort_values('日期')
    df_merged['日期'] = df_merged['日期'].dt.strftime('%Y-%m-%d')
    df_merged.to_csv(csv_path, index=False, encoding='utf-8-sig')
    print(f'补齐 {len(fill_data)} 条（{start_date} ~ {end_date}）')

# ============================================================
# 智能数据源选择
# ============================================================

def smart_fetch(code, days=500, is_index=False, incremental=False, local_latest_date=None):
    """
    智能数据获取：优先TDX，TDX无最新数据则切API
    
    判断逻辑（借鉴增量更新）:
    1. 检查TDX最新日期
    2. 比较本地最新日期，TDX更新或相等则用TDX
    3. TDX更旧或不存在则切API
    """
    print(f'  智能选择数据源...')
    
    should_use, tdx_latest_str = should_use_tdx(code, local_latest_date)
    
    if should_use:
        print(f'  [OK] 使用TDX数据源')
        if incremental:
            df = fetch_from_tdx(code, days=15)
        else:
            df = fetch_from_tdx(code, days=days)
    else:
        print(f'  [X] 切换API数据源')
        if is_index:
            df = fetch_from_api(code, days=5 if incremental else days)
        else:
            df = fetch_from_api(code, days=15 if incremental else days)
    
    if df is not None and len(df) > 0:
        print(f'  获取成功：{len(df)} 条')
    else:
        print(f'  获取失败')
    
    return df

# ============================================================
# 主程序
# ============================================================

def main():
    parser = argparse.ArgumentParser(description='A股股价获取')
    parser.add_argument('--code', help='股票代码 (默认全部)')
    parser.add_argument('--all', '-a', action='store_true', help='更新config中所有启用的股票')
    parser.add_argument('--incremental', '-i', action='store_true', help='增量模式：检查新数据并追加')
    parser.add_argument('--fill', metavar='START,END', help='补齐模式：补齐特定日期范围，格式: YYYY-MM-DD,YYYY-MM-DD')
    parser.add_argument('--days', type=int, default=500, help='获取天数 (默认500)')
    args = parser.parse_args()
    
    codes = [args.code] if args.code else [c for c, v in STOCKS.items() if v.get('enabled', True)]
    
    for code in codes:
        info = STOCKS.get(code, {})
        name = info.get('name', code)
        is_index = info.get('index', False)
        csv_path = f'{DATA_DIR}/历史价格_{name}.csv'
        
        print(f'\n=== {name} ({code}) ===')
        
        # 获取本地最新日期
        local_latest = get_local_latest(name)
        
        if args.fill:
            start_date, end_date = args.fill.split(',')
            df = smart_fetch(code, days=args.days, is_index=is_index, local_latest_date=local_latest)
            if df is not None:
                fill_range(df, csv_path, start_date, end_date)
            continue
        
        if args.incremental:
            df = smart_fetch(code, is_index=is_index, incremental=True, local_latest_date=local_latest)
            if df is None:
                continue
            merge_incremental(df, csv_path)
            continue
        
        # 默认模式：检查本地是否有START_DATE至今的数据
        df_local = load_local(name)
        if df_local is not None and len(df_local) > 0:
            existing = df_local[df_local['日期'] >= START_DATE]
            if len(existing) > 0:
                print(f'本地已有 {len(existing)} 条（{START_DATE}至今），共 {len(df_local)} 条')
                continue
        
        # 没有本地数据的，从头获取
        df = smart_fetch(code, days=args.days, is_index=is_index, local_latest_date=local_latest)
        
        if df is None:
            continue
        
        df = df[df['日期'] >= START_DATE]
        df.to_csv(csv_path, index=False, encoding='utf-8-sig')
        print(f'已保存 {len(df)} 条（{START_DATE}至今）到: {csv_path}')
        
        time.sleep(1)
    
    # 生成全市场成交额CSV
    generate_market_amount_csv()

if __name__ == '__main__':
    main()

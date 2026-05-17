import struct
import os
import csv
import glob
import json
import pickle
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, '..', 'config.json')
with open(CONFIG_PATH, encoding='utf-8') as f:
    CONFIG = json.load(f)

DATA_PATH = CONFIG['sources']['tongdaxin']
OUTPUT_PATH = os.path.join(SCRIPT_DIR, '..', CONFIG['data']['output_dir'])
MAX_DAYS = 120
BATCH_SIZE = 3
CACHE_FILE = os.path.join(OUTPUT_PATH, 'stock_cache.pkl')

def read_tdx_last_n(filepath, n):
    try:
        with open(filepath, 'rb') as f:
            f.seek(0, 2)
            size = f.tell()
            record_size = 32
            num_records = size // record_size
            start = max(0, num_records - n) * record_size
            f.seek(start)
            data = f.read()
    except Exception:
        return []
    
    records = []
    for i in range(0, len(data), record_size):
        rec = data[i:i+record_size]
        if len(rec) < 32:
            break
        date_int = int.from_bytes(rec[0:4], 'little')
        open_price = int.from_bytes(rec[4:8], 'little') / 100.0
        high = int.from_bytes(rec[8:12], 'little') / 100.0
        low = int.from_bytes(rec[12:16], 'little') / 100.0
        close = int.from_bytes(rec[16:20], 'little') / 100.0
        records.append((date_int, open_price, high, low, close))
    return records

def date_int_to_str(date_int):
    year = date_int // 10000
    month = (date_int % 10000) // 100
    day = date_int % 100
    return f'{year}-{month:02d}-{day:02d}'

def get_limit_pct(code):
    if code.startswith('900') or code.startswith('400'):
        return 5
    if code.startswith('30') or code.startswith('688'):
        return 20
    if code.startswith('8') or code.startswith('4'):
        return 30
    return 10

def get_latest_day_mtime():
    """获取所有源 .day 文件的最新修改时间"""
    latest = 0
    for market in ['sh', 'sz', 'bj']:
        lday_path = os.path.join(DATA_PATH, market, 'lday')
        if not os.path.exists(lday_path):
            continue
        for filepath in glob.glob(os.path.join(lday_path, '*.day')):
            try:
                mtime = os.path.getmtime(filepath)
                if mtime > latest:
                    latest = mtime
            except Exception:
                pass
    return latest

def load_or_build_cache(index_dates):
    """加载或构建股票数据缓存（只统计股票，排除指数和已退市股票）"""
    if os.path.exists(CACHE_FILE):
        try:
            cache_mtime = os.path.getmtime(CACHE_FILE)
            source_mtime = get_latest_day_mtime()
            if source_mtime > cache_mtime:
                print(f'检测到数据源更新，重建缓存...')
            else:
                with open(CACHE_FILE, 'rb') as f:
                    cache = pickle.load(f)
                print(f'从缓存加载了 {len(cache)} 只股票的数据')
                return cache
        except Exception as e:
            print(f'缓存校验失败: {e}')
    
    print('构建股票数据缓存...')
    stocks_data = {}
    count = 0
    delisted = 0
    
    # 股票代码前缀规则
    stock_prefixes = {
        'sh': ['600', '601', '603', '605', '688'],  # 上海A股+科创板
        'sz': ['000', '001', '002', '003', '300', '301'],  # 深圳A股+创业板
        'bj': ['8', '4']  # 北交所
    }
    
    # 多读 20 条防止边界截断
    read_extra = MAX_DAYS + 20
    
    for market in ['sh', 'sz', 'bj']:
        lday_path = os.path.join(DATA_PATH, market, 'lday')
        if not os.path.exists(lday_path):
            continue
        for filepath in glob.glob(os.path.join(lday_path, '*.day')):
            code = os.path.basename(filepath).replace('.day', '')
            # 排除指数（9开头是指数）
            if code[2:].isdigit():
                if any(code[2:].startswith(p) for p in stock_prefixes.get(market, [])):
                    try:
                        # 先读取最后一条记录，检查是否已退市
                        with open(filepath, 'rb') as f:
                            f.seek(-32, 2)
                            last_rec = f.read(32)
                            if len(last_rec) < 32:
                                continue
                            latest_date = int.from_bytes(last_rec[0:4], 'little')
                        
                        # 最新日期不在指数交易日历中 → 已退市
                        if latest_date not in index_dates:
                            delisted += 1
                            continue
                        
                        records = read_tdx_last_n(filepath, read_extra)
                        # 过滤出指数交易日历中的日期
                        filtered = [r for r in records if r[0] in index_dates]
                        if not filtered:
                            continue
                        
                        # 确保最早日期的前一条记录被保留（用于计算涨跌幅）
                        first_date = filtered[0][0]
                        for i, r in enumerate(records):
                            if r[0] == first_date and i > 0:
                                filtered.insert(0, records[i - 1])
                                break
                        
                        stocks_data[code] = filtered
                        count += 1
                        if count % 1000 == 0:
                            print(f'  已处理 {count} 只股票...')
                    except Exception:
                        pass
    
    print(f'缓存构建完成: {count} 只股票（已排除 {delisted} 只退市股票）')
    
    try:
        with open(CACHE_FILE, 'wb') as f:
            pickle.dump(stocks_data, f)
        print(f'缓存已保存到 {CACHE_FILE}')
    except Exception as e:
        print(f'缓存保存失败: {e}')
    
    return stocks_data

def main():
    os.makedirs(OUTPUT_PATH, exist_ok=True)
    output_file = os.path.join(OUTPUT_PATH, '涨跌个数_市场.csv')
    
    existing = {}
    if os.path.exists(output_file):
        with open(output_file, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                existing[row['date']] = row
    print(f'已存在数据: {len(existing)} 天')
    
    index_file = os.path.join(DATA_PATH, 'sh', 'lday', 'sh999999.day')
    if not os.path.exists(index_file):
        print('上证指数文件不存在')
        return
    
    try:
        index_dates = set()
        records = read_tdx_last_n(index_file, MAX_DAYS)
        for r in records:
            index_dates.add(r[0])
    except Exception as e:
        print(f'读取指数文件失败: {e}')
        return
    
    print(f'指数有 {len(index_dates)} 个交易日')
    
    missing_dates = sorted([d for d in index_dates if date_int_to_str(d) not in existing])
    if not missing_dates:
        print('没有缺失日期')
        return
    
    print(f'缺失日期: {len(missing_dates)} 个')
    
    # 加载缓存
    stocks_data = load_or_build_cache(index_dates)
    
    total_batches = (len(missing_dates) + BATCH_SIZE - 1) // BATCH_SIZE
    print(f'分为 {total_batches} 批处理，每批 {BATCH_SIZE} 天')
    
    for batch_idx in range(total_batches):
        batch_start = batch_idx * BATCH_SIZE
        batch_end = min(batch_start + BATCH_SIZE, len(missing_dates))
        batch_dates = missing_dates[batch_start:batch_end]
        print(f'\n第 {batch_idx+1}/{total_batches} 批: {len(batch_dates)} 天')
        
        for date_int in batch_dates:
            date_str = date_int_to_str(date_int)
            up = down = flat = limit_up = limit_down = 0
            pct_changes = []  # for median calculation
            
            for code, records in stocks_data.items():
                for idx, (d, o, h, l, c) in enumerate(records):
                    if d == date_int and idx > 0:
                        prev = records[idx-1][4]
                        if prev > 0:
                            pct = (c - prev) / prev * 100
                            pct_changes.append(pct)
                            limit_pct = get_limit_pct(code)
                            limit_up_price = round(prev * (1 + limit_pct / 100), 2)
                            limit_down_price = round(prev * (1 - limit_pct / 100), 2)
                            tolerance = max(0.005, c * 0.001)
                            
                            if abs(c - limit_up_price) < tolerance:
                                limit_up += 1
                                up += 1
                            elif abs(c - limit_down_price) < tolerance:
                                limit_down += 1
                                down += 1
                            elif pct > 0:
                                up += 1
                            elif pct < 0:
                                down += 1
                            else:
                                flat += 1
                        break
            
            # 计算涨跌幅中位数
            if pct_changes:
                pct_changes.sort()
                n = len(pct_changes)
                median_change = pct_changes[n // 2] if n % 2 else (pct_changes[n//2 - 1] + pct_changes[n//2]) / 2
            else:
                median_change = 0.0
            
            existing[date_str] = {
                'date': date_str, 'up': str(up), 'down': str(down),
                'flat': str(flat), 'limit_up': str(limit_up), 'limit_down': str(limit_down),
                'median_change': f'{median_change:.2f}'
            }
            print(f'  {date_str}: 涨={up}, 跌={down}, 平={flat}, 中位数={median_change:.2f}%')
        
        sorted_dates = sorted(existing.keys())[-MAX_DAYS:]
        results = [existing[d] for d in sorted_dates]
        
        with open(output_file, 'w', newline='', encoding='utf-8-sig') as f:
            fieldnames = ['date', 'up', 'down', 'flat', 'limit_up', 'limit_down', 'median_change']
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(results)
        
        print(f'第 {batch_idx+1} 批完成: 已保存 {len(results)} 天')

if __name__ == '__main__':
    main()

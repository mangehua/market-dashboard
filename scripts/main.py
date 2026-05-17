import subprocess
import sys
import time
import os

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
SYMBOLS = ['上证指数', '巨人网络', '游戏ETF', '妙可蓝多']

def run(cmd, desc):
    print(f'[{desc}] start...')
    t0 = time.time()
    result = subprocess.run(cmd, cwd=SCRIPTS_DIR, capture_output=True, text=True, timeout=300)
    elapsed = time.time() - t0
    if result.returncode == 0:
        print(f'[{desc}] done ({elapsed:.1f}s)')
    else:
        print(f'[{desc}] fail ({elapsed:.1f}s)')
        print(f'  stderr: {result.stderr.strip()}')
    return result.returncode

def main():
    steps = [
        (['python', 'fetch_stock.py', '-i'], '价格获取'),
        (['python', 'get_updown.py'], '涨跌统计'),
    ]
    for sym in SYMBOLS:
        steps.append((['python', 'moving_vwap.py', '60', sym], f'强弱线({sym})'))
    steps.append((['python', 'calculate_vwap.py'], '压力支撑'))
    steps.append((['python', 'sentiment.py'], '情绪指数'))

    for cmd, desc in steps:
        if run(cmd, desc) != 0:
            print(f'[错误] {desc} 失败，终止流水线')
            sys.exit(1)

if __name__ == '__main__':
    main()

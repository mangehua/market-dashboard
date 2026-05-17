from flask import Flask, jsonify, send_from_directory
import threading
import os
import subprocess
import requests
import base64
import time
import json

import sys
import warnings
warnings.filterwarnings('ignore', message='Unverified HTTPS request')

from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

if sys.platform == 'win32':
    result = subprocess.run(
        ['powershell', '-Command', '[Environment]::GetEnvironmentVariable("GITHUB_TOKEN", "User")'],
        capture_output=True, text=True
    )
    env_token = result.stdout.strip()
    if env_token:
        os.environ['GITHUB_TOKEN'] = env_token

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, static_folder=os.path.join(BASE_DIR, '.'), static_url_path='')

GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN', '')
if not GITHUB_TOKEN:
    print("WARNING: GITHUB_TOKEN not set, upload disabled")
GITHUB_REPO = 'mangehua/market-dashboard'

task_status = {}
task_timestamp = {}
task_lock = threading.Lock()

def set_task(task_id, data):
    with task_lock:
        task_status[task_id] = data
        task_timestamp[task_id] = time.time()
        cutoff = time.time() - 3600
        stale = [k for k, v in task_timestamp.items() if v < cutoff]
        for k in stale:
            task_status.pop(k, None)
            task_timestamp.pop(k, None)

def get_task(task_id):
    with task_lock:
        return task_status.get(task_id, {'status': 'not_found'})

def upload_to_github(local_path, github_path):
    if not GITHUB_TOKEN:
        return False
    url = f'https://api.github.com/repos/{GITHUB_REPO}/contents/{github_path}'
    headers = {'Authorization': f'token {GITHUB_TOKEN}', 'Accept': 'application/vnd.github.v3+json'}
    for attempt in range(3):
        try:
            session = requests.Session()
            retry = Retry(total=3, backoff_factor=1)
            adapter = HTTPAdapter(max_retries=retry)
            session.mount('https://', adapter)
            r = session.get(url, headers=headers, timeout=15, verify=False)
            existing = r.json() if r.status_code == 200 else {}
            with open(local_path, 'rb') as f:
                content = f.read()
            encoded = base64.b64encode(content).decode()
            payload = {'message': f'Update {github_path}', 'content': encoded}
            if 'sha' in existing:
                payload['sha'] = existing['sha']
            r = session.put(url, headers=headers, json=payload, timeout=60, verify=False)
            if r.status_code in [200, 201]:
                print(f'Uploaded: {github_path}')
                return True
            elif r.status_code == 422:
                print(f'Skip (unchanged): {github_path}')
                return True
        except requests.exceptions.Timeout:
            print(f'Upload attempt {attempt+1} timeout: {github_path}')
        except requests.exceptions.ConnectionError:
            print(f'Upload attempt {attempt+1} connection error: {github_path}')
        except Exception as e:
            print(f'Upload error: {github_path} - {e}')
        if attempt < 2:
            time.sleep(2)
    print(f'Failed after 3 attempts: {github_path}')
    return False

def upload_html():
    uploaded = []
    for f in ['index.html', 'resonance.html', 'analysis.html', 'track.html']:
        path = os.path.join(BASE_DIR, f)
        if os.path.exists(path) and upload_to_github(path, f'huafu/{f}'):
            uploaded.append(f)
    return uploaded

def upload_csv():
    data_dir = os.path.join(BASE_DIR, 'stock_data')
    uploaded = []
    for f in os.listdir(data_dir):
        if f.endswith('.csv'):
            path = os.path.join(data_dir, f)
            if upload_to_github(path, f'huafu/stock_data/{f}'):
                uploaded.append(f)
    return uploaded

@app.route('/')
def index():
    return send_from_directory(BASE_DIR, 'index.html')

@app.route('/index.html')
def index_html():
    return send_from_directory(BASE_DIR, 'index.html')

@app.route('/resonance.html')
def resonance():
    return send_from_directory(BASE_DIR, 'resonance.html')

@app.route('/<path:filename>')
def serve_static(filename):
    if os.path.exists(os.path.join(BASE_DIR, filename)):
        return send_from_directory(BASE_DIR, filename)
    return "Not Found", 404

@app.get('/api/health')
def health():
    return jsonify({
        'status': 'ok',
        'github_token_set': bool(GITHUB_TOKEN),
        'uptime': time.time()
    })

@app.get('/api/task/<task_id>')
def get_task_route(task_id):
    return jsonify(get_task(task_id))

@app.post('/api/upload/html')
def upload_html_route():
    task_id = f'html_{int(time.time())}'
    set_task(task_id, {'status': 'running', 'message': '上传HTML中...'})
    def do_upload():
        result = upload_html()
        set_task(task_id, {'status': 'done', 'result': result})
    t = threading.Thread(target=do_upload, daemon=True)
    t.start()
    return jsonify({'status': 'ok', 'task_id': task_id, 'message': 'HTML上传任务已启动'})

@app.post('/api/upload/csv')
def upload_csv_route():
    task_id = f'csv_{int(time.time())}'
    set_task(task_id, {'status': 'running', 'message': '上传CSV中...'})
    def do_upload():
        result = upload_csv()
        set_task(task_id, {'status': 'done', 'result': result})
    t = threading.Thread(target=do_upload, daemon=True)
    t.start()
    return jsonify({'status': 'ok', 'task_id': task_id, 'message': 'CSV上传任务已启动'})

@app.post('/api/update/market')
def update_market():
    task_id = f'market_{int(time.time())}'
    set_task(task_id, {'status': 'running', 'message': '更新市场数据...'})
    def do_update():
        try:
            script_dir = os.path.join(BASE_DIR, 'scripts')
            result = subprocess.run(
                ['python', 'get_updown.py'],
                cwd=script_dir, capture_output=True, timeout=300, text=True
            )
            set_task(task_id, {
                'status': 'done' if result.returncode == 0 else 'error',
                'output': result.stdout, 'error': result.stderr
            })
        except subprocess.TimeoutExpired:
            set_task(task_id, {'status': 'error', 'error': 'Timeout'})
        except Exception as e:
            set_task(task_id, {'status': 'error', 'error': str(e)})
    t = threading.Thread(target=do_update, daemon=True)
    t.start()
    return jsonify({'status': 'ok', 'task_id': task_id, 'message': '数据更新任务已启动'})

@app.post('/api/update/price')
def update_price():
    task_id = f'price_{int(time.time())}'
    set_task(task_id, {'status': 'running', 'message': '更新价格数据...'})
    def do_update():
        try:
            script_dir = os.path.join(BASE_DIR, 'scripts')
            result = subprocess.run(
                ['python', 'fetch_stock.py', '-i'],
                cwd=script_dir, capture_output=True, timeout=300, text=True
            )
            set_task(task_id, {
                'status': 'done' if result.returncode == 0 else 'error',
                'output': result.stdout, 'error': result.stderr
            })
        except subprocess.TimeoutExpired:
            set_task(task_id, {'status': 'error', 'error': 'Timeout'})
        except Exception as e:
            set_task(task_id, {'status': 'error', 'error': str(e)})
    t = threading.Thread(target=do_update, daemon=True)
    t.start()
    return jsonify({'status': 'ok', 'task_id': task_id, 'message': '价格更新任务已启动'})

@app.post('/api/update/strength')
def update_strength():
    task_id = f'strength_{int(time.time())}'
    set_task(task_id, {'status': 'running', 'message': '更新强弱线数据...'})
    def do_update():
        try:
            script_dir = os.path.join(BASE_DIR, 'scripts')
            symbols = ['上证指数', '巨人网络', '游戏ETF']
            outputs = []
            for sym in symbols:
                result = subprocess.run(
                    ['python', 'moving_vwap.py', '60', sym],
                    cwd=script_dir, capture_output=True, timeout=120, text=True
                )
                outputs.append(f'{sym}: {result.stdout.strip()}')
            set_task(task_id, {'status': 'done', 'output': '\n'.join(outputs)})
        except Exception as e:
            set_task(task_id, {'status': 'error', 'error': str(e)})
    t = threading.Thread(target=do_update, daemon=True)
    t.start()
    return jsonify({'status': 'ok', 'task_id': task_id, 'message': '强弱线更新任务已启动'})

@app.post('/api/update/support')
def update_support():
    task_id = f'support_{int(time.time())}'
    set_task(task_id, {'status': 'running', 'message': '更新压力支撑数据...'})
    def do_update():
        try:
            script_dir = os.path.join(BASE_DIR, 'scripts')
            result = subprocess.run(
                ['python', 'calculate_vwap.py'],
                cwd=script_dir, capture_output=True, timeout=120, text=True
            )
            set_task(task_id, {
                'status': 'done' if result.returncode == 0 else 'error',
                'output': result.stdout, 'error': result.stderr
            })
        except subprocess.TimeoutExpired:
            set_task(task_id, {'status': 'error', 'error': 'Timeout'})
        except Exception as e:
            set_task(task_id, {'status': 'error', 'error': str(e)})
    t = threading.Thread(target=do_update, daemon=True)
    t.start()
    return jsonify({'status': 'ok', 'task_id': task_id, 'message': '压力支撑更新任务已启动'})

@app.post('/api/update/all')
def update_all():
    task_id = f'all_{int(time.time())}'
    set_task(task_id, {'status': 'running', 'message': '全量更新中...'})
    def do_update():
        try:
            script_dir = os.path.join(BASE_DIR, 'scripts')
            result = subprocess.run(
                ['python', 'main.py'],
                cwd=script_dir, capture_output=True, timeout=1800, text=True
            )
            set_task(task_id, {
                'status': 'done' if result.returncode == 0 else 'error',
                'output': result.stdout, 'error': result.stderr
            })
        except subprocess.TimeoutExpired:
            set_task(task_id, {'status': 'error', 'error': 'Timeout'})
        except Exception as e:
            set_task(task_id, {'status': 'error', 'error': str(e)})
    t = threading.Thread(target=do_update, daemon=True)
    t.start()
    return jsonify({'status': 'ok', 'task_id': task_id, 'message': '全量更新任务已启动'})

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=8000, debug=False, use_reloader=False)

/* 华夫饼手册 - 公共脚本（5页共用）
   提供: 侧边导航 / Toast / fetchCSV / 盘后更新 / 盘中更新 / 数字键切换
         十字线联动插件 / 数据健康条 + 过期自动更新
   页面需在 <body data-page="xxx"> 标注当前页，并放置 <div class="sidebar" id="appSidebar"></div> */

const baseUrl = '.';
const IS_REMOTE = !['localhost', '127.0.0.1', '::1'].includes(window.location.hostname);

/* ================= Toast ================= */
function showToast(msg, type, onRetry) {
    type = type || 'error';
    var c = document.getElementById('toastContainer');
    if (!c) { c = document.createElement('div'); c.id = 'toastContainer'; c.className = 'toast-container'; document.body.appendChild(c); }
    var t = document.createElement('div');
    t.className = 'toast ' + type;
    t.textContent = msg;
    if (onRetry) {
        var b = document.createElement('button');
        b.textContent = '重试';
        b.style.cssText = 'margin-left:12px;padding:4px 12px;border:none;border-radius:4px;background:rgba(255,255,255,0.25);color:#fff;cursor:pointer;font-size:13px;vertical-align:middle;';
        b.onclick = function(e) { e.stopPropagation(); t.remove(); onRetry(); };
        t.appendChild(b);
    }
    c.appendChild(t);
    setTimeout(function() { t.style.opacity = '0'; t.style.transition = 'opacity 0.3s'; setTimeout(function() { t.remove(); }, 300); }, 4000);
}

/* ================= CSV解析 (nocache=true时加时间戳防缓存) ================= */
async function fetchCSV(url, nocache) {
    if (nocache) url += (url.indexOf('?') >= 0 ? '&' : '?') + 't=' + Date.now();
    const response = await fetch(url);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const text = await response.text();
    const lines = text.trim().split('\n');
    const headers = lines[0].split(',').map(h => h.trim().replace(/^﻿/, ''));
    return lines.slice(1).map(line => {
        const values = line.split(',');
        const obj = {};
        headers.forEach((h, i) => obj[h] = values[i] ? values[i].trim() : '');
        return obj;
    });
}

/* ================= 盘后数据更新 ================= */
async function updateData() {
    const nav = document.getElementById('updateNavBtn');
    const dateSpan = document.getElementById('updateDate');
    const pb = document.getElementById('progressBar');
    if (!nav) return;
    if (IS_REMOTE) { showToast('该功能仅限电脑本地使用', 'warning'); return; }
    nav.classList.add('disabled');
    if (pb) pb.classList.add('active');
    try {
        const res = await fetch('/api/update/all', { method: 'POST' });
        const data = await res.json();
        if (data.status !== 'ok') {
            showToast('更新失败: ' + data.message, 'error', function() { updateData(); });
            nav.classList.remove('disabled');
            if (pb) pb.classList.remove('active');
            return;
        }
        const taskId = data.task_id;
        const poll = setInterval(async () => {
            const pr = await fetch('/api/task/' + taskId);
            const ps = await pr.json();
            if (ps.status === 'done') {
                clearInterval(poll);
                if (pb) pb.classList.remove('active');
                if (dateSpan) dateSpan.textContent = '最新数据: ' + new Date().toLocaleTimeString();
                showToast('数据更新完成', 'success');
                setTimeout(() => { location.reload(); }, 2000);
            } else if (ps.status === 'error') {
                clearInterval(poll);
                showToast('更新失败: ' + (ps.error || '未知错误'), 'error', function() { updateData(); });
                nav.classList.remove('disabled');
                if (pb) pb.classList.remove('active');
            }
        }, 2000);
    } catch (e) {
        showToast('请求失败: ' + e.message, 'error', function() { updateData(); });
        nav.classList.remove('disabled');
        if (pb) pb.classList.remove('active');
    }
}

/* ================= 盘中数据更新 (页面定义了 remoteUpdateData 则直接刷新，否则跳转共振页) ================= */
function realtimeUpdate() {
    var nav = document.getElementById('rtNav');
    if (!nav || nav.classList.contains('disabled')) return;
    var today = new Date().toDateString();
    var savedDate = localStorage.getItem('realtime_quota_date') || '';
    if (savedDate !== today) {
        localStorage.setItem('realtime_quota_date', today);
        localStorage.setItem('realtime_quota_20', '0');
    }
    var quota = JSON.parse(localStorage.getItem('realtime_quota_20') || '0');
    if (quota >= 20) {
        showToast('今日盘中更新(20次)已用完，明日重置', 'warning');
        return;
    }
    quota++;
    localStorage.setItem('realtime_quota_20', JSON.stringify(quota));
    showToast('盘中更新配额余' + (20 - quota) + '次', 'success');
    nav.classList.add('disabled');
    if (typeof remoteUpdateData === 'function') {
        nav.textContent = '⏳ 更新中...';
        remoteUpdateData().then(function() {
            nav.textContent = '盘中数据';
            nav.classList.remove('disabled');
        });
    } else {
        nav.textContent = '⏳ 跳转中...';
        setTimeout(function() { location.href = 'resonance.html?realtime=1'; }, 1500);
    }
}

/* ================= 侧边导航 ================= */
var NAV_PAGES = [
    ['resonance', '共振分析', 'resonance.html'],
    ['index', '图谱分析', 'index.html'],
    ['track', '周期研判', 'track.html'],
    ['analysis', '信号收集', 'analysis.html'],
    ['scanner', '扫描结果', 'scanner.html']
];

function renderSidebar() {
    var sb = document.getElementById('appSidebar');
    if (!sb) return;
    var cur = document.body.dataset.page || '';
    var html = '<div class="logo">华夫饼手册</div>';
    NAV_PAGES.forEach(function(p) {
        html += '<div class="nav-item' + (p[0] === cur ? ' active' : '') + '" onclick="location.href=\'' + p[2] + '\'">' + p[1] + '</div>';
    });
    html += '<div class="nav-item" onclick="showToast(\'该功能暂未开放\', \'warning\')" style="cursor:default;">设置</div>';
    html += '<hr class="nav-divider">';
    html += '<div class="nav-item" id="updateNavBtn" onclick="updateData()">盘后数据</div>';
    html += '<div class="nav-item" id="rtNav" onclick="realtimeUpdate()">盘中数据</div>';
    sb.innerHTML = html;
}

/* ================= 数字键1-5切换页面, R键更新 ================= */
document.addEventListener('keydown', function(e) {
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
    if (e.key === 'r' || e.key === 'R') { updateData(); return; }
    var targets = { '1': 'resonance.html', '2': 'index.html', '3': 'track.html', '4': 'analysis.html', '5': 'scanner.html' };
    var target = targets[e.key];
    if (target && location.pathname.indexOf(target) === -1) location.href = target;
});

/* ================= 十字线联动 (resonance/track/analysis 使用) ================= */
const allCharts = [];
let syncIndex = -1;
let isLocked = false;

const crosshairPlugin = {
    id: 'crosshair',
    afterDraw(chart) {
        if (syncIndex >= 0 && syncIndex < chart.config.data.labels.length && chart.chartArea) {
            const ctx = chart.ctx;
            const xAxis = chart.scales.x;
            const yAxis = chart.scales.y;
            if (!xAxis || !yAxis) return;
            const x = xAxis.getPixelForValue(syncIndex);

            ctx.save();
            ctx.beginPath();
            ctx.moveTo(x, chart.chartArea.top);
            ctx.lineTo(x, chart.chartArea.bottom);
            ctx.lineWidth = 1;
            ctx.strokeStyle = '#000000';
            ctx.setLineDash([4, 4]);
            ctx.stroke();
            ctx.restore();

            const datasets = chart.config.data.datasets;
            if (datasets.length > 0 && datasets[0].data[syncIndex] !== undefined) {
                const yVal = datasets[0].data[syncIndex];
                if (yVal !== null && !isNaN(yVal)) {
                    const y = yAxis.getPixelForValue(yVal);
                    ctx.save();
                    ctx.beginPath();
                    ctx.moveTo(chart.chartArea.left, y);
                    ctx.lineTo(chart.chartArea.right, y);
                    ctx.lineWidth = 1;
                    ctx.strokeStyle = '#000000';
                    ctx.setLineDash([4, 4]);
                    ctx.stroke();
                    ctx.restore();
                }
            }
        }
    }
};

function syncCrosshair(sourceChart, eventIndex) {
    if (isLocked) return;
    syncIndex = eventIndex;
    allCharts.forEach(c => c.update('none'));
}

function toggleCrosshair(sourceChart, event) {
    if (syncIndex === -1) {
        const el = sourceChart.getElementsAtEventForMode(event, 'index', { mode: 'index', intersect: false }, false);
        if (el.length > 0) {
            isLocked = true;
            syncIndex = el[0].index;
            allCharts.forEach(c => c.update('none'));
        }
    } else {
        isLocked = false;
        syncIndex = -1;
        allCharts.forEach(c => c.update('none'));
    }
}

/* ================= 数据健康条 + 过期自动更新 ================= */
function renderDataHealth(s) {
    var host = document.querySelector('.header-right') || document.querySelector('.header');
    if (!host) return;
    var el = document.createElement('span');
    var warns = (s.warnings || []);
    el.className = 'data-health ' + (warns.length ? 'warn' : (s.stale ? 'stale' : 'ok'));
    var txt = '数据 ' + (s.latest || '?');
    if (s.stale) txt += ' · 待更新';
    if (warns.length) txt += ' · ' + warns.join('、');
    el.textContent = txt;
    if (s.tdx) el.title = '通达信: 沪 ' + (s.tdx.sh || '-') + ' / 深 ' + (s.tdx.sz || '-') + ' / 北 ' + (s.tdx.bj || '-');
    host.insertBefore(el, host.firstChild);
}

async function initDataHealth() {
    if (IS_REMOTE) return;
    var s;
    try {
        var r = await fetch('/api/data_status');
        if (!r.ok) return;
        s = await r.json();
    } catch (e) { return; }
    renderDataHealth(s);
    // 数据过期 → 每会话每天最多自动更新一次（更新完成后updateData会刷新页面）
    if (s.stale) {
        try {
            var key = 'auto_update_try_date';
            if (sessionStorage.getItem(key) === new Date().toDateString()) return;
            sessionStorage.setItem(key, new Date().toDateString());
        } catch (e) { return; }
        showToast('数据非最新，自动更新中...', 'warning');
        updateData();
    }
}

document.addEventListener('DOMContentLoaded', function() {
    renderSidebar();
    initDataHealth();
});

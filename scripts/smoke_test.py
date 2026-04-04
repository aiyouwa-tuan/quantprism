#!/usr/bin/env python3
"""
QuantPrism 功能冒烟测试
每次部署后必须运行，验证核心功能而不只是 HTTP 状态码。

用法:
    python3 scripts/smoke_test.py [base_url]
    python3 scripts/smoke_test.py http://caotaibanzi.xyz
"""
import sys
import json
import time
import subprocess
import requests

BASE = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://caotaibanzi.xyz"
PASS = 0
FAIL = 0
ERRORS = []

S = requests.Session()
S.headers["User-Agent"] = "QuantPrism-SmokeTest/1.0"


def ok(msg):
    global PASS
    PASS += 1
    print(f"  \033[32m✓\033[0m  {msg}")


def fail(msg, detail=""):
    global FAIL
    FAIL += 1
    ERRORS.append(msg)
    print(f"  \033[31m✗\033[0m  {msg}")
    if detail:
        print(f"     → {detail[:200]}")


def section(title):
    print(f"\n\033[1m── {title}\033[0m")


# ─────────────────────────────────────────────────────────────
# 1. 页面可访问性（不只是 200，还要检查关键内容）
# ─────────────────────────────────────────────────────────────
section("页面渲染检查")

PAGES = [
    ("/goals",    "设定投资目标"),
    ("/hunt",     "策略猎手"),
    ("/backtest", "回测实验室"),
    ("/scan",     "标的扫描"),
    ("/risk",     "风控护盾"),
    ("/watchlist","观察列表"),
    ("/settings", "系统配置"),
]

for path, keyword in PAGES:
    try:
        r = S.get(BASE + path, timeout=15, allow_redirects=True)
        if r.status_code != 200:
            fail(f"{path} → HTTP {r.status_code}")
        elif keyword not in r.text:
            fail(f"{path} 页面内容缺少「{keyword}」", r.text[:300])
        elif "Internal Server Error" in r.text or "TemplateSyntaxError" in r.text:
            fail(f"{path} 包含服务器错误", r.text[:300])
        else:
            ok(f"{path} 正常（含「{keyword}」）")
    except Exception as e:
        fail(f"{path} 请求失败: {e}")


# ─────────────────────────────────────────────────────────────
# 2. /settings 不能暴露 API key 明文
# ─────────────────────────────────────────────────────────────
section("安全检查")

try:
    r = S.get(BASE + "/settings", timeout=15, allow_redirects=True)
    import re
    # 查找 value="..." 中超过 20 字符的字符串（可能是 key）
    exposed = re.findall(r'value="([A-Za-z0-9_\-]{20,})"', r.text)
    if exposed:
        fail("/settings 存在疑似明文 API Key 暴露", str(exposed[:2]))
    else:
        ok("/settings 未暴露明文 API Key")
    # type=password 检查
    if 'type="password"' in r.text or "type=password" in r.text:
        ok("/settings API key 输入框为 password 类型")
    else:
        fail("/settings API key 输入框不是 password 类型")
except Exception as e:
    fail(f"/settings 安全检查失败: {e}")


# ─────────────────────────────────────────────────────────────
# 3. 导航高亮（/risk 只能有一个高亮项）
# ─────────────────────────────────────────────────────────────
section("导航高亮检查")

try:
    r = S.get(BASE + "/risk", timeout=15, allow_redirects=True)
    import re
    # 找 nav 里 active 的链接数
    active_count = r.text.count("bg-dark-500 text-white")
    if active_count == 1:
        ok(f"/risk 导航只有 1 个高亮项")
    elif active_count == 0:
        fail("/risk 导航没有任何高亮项")
    else:
        fail(f"/risk 导航有 {active_count} 个高亮项（应为 1 个）")
except Exception as e:
    fail(f"导航高亮检查失败: {e}")


# ─────────────────────────────────────────────────────────────
# 4. API 数据质量（返回真实数据，不是空/null）
# ─────────────────────────────────────────────────────────────
section("API 数据质量检查")

API_CHECKS = [
    ("/api/vix",    "price",   lambda v: isinstance(v.get("price"), (int, float)) and v["price"] > 0),
    ("/api/regime", "regime",  lambda v: isinstance(v.get("regime"), str) and len(v["regime"]) > 0),
    ("/healthz",    "status",  lambda v: v.get("status") == "ok"),
]

for path, key, validator in API_CHECKS:
    try:
        r = S.get(BASE + path, timeout=15)
        data = r.json()
        if validator(data):
            ok(f"{path} 返回有效数据（{key}={data.get(key)!r}）")
        else:
            fail(f"{path} 数据无效", json.dumps(data)[:200])
    except Exception as e:
        fail(f"{path} 请求/解析失败: {e}")


# ─────────────────────────────────────────────────────────────
# 5. 回测功能检查（最关键——指标不能全为 0）
# ─────────────────────────────────────────────────────────────
section("回测功能检查（核心）")

# 先找一个可用的 strategy_id
try:
    r = S.get(BASE + "/backtest", timeout=15, allow_redirects=True)
    import re
    ids = re.findall(r'option value="(\d+)"', r.text)
    if not ids:
        fail("回测页面没有找到任何策略 ID，跳过回测测试")
    else:
        strategy_id = ids[0]
        ok(f"回测页面找到 {len(ids)} 个策略（用 ID={strategy_id} 测试）")

        r2 = S.post(BASE + "/backtest/run", timeout=60, data={
            "strategy_id": strategy_id,
            "symbol": "SPY",
            "start_date": "2022-01-01",
            "end_date": "2024-12-31",
        })
        if r2.status_code != 200:
            fail(f"POST /backtest/run 返回 {r2.status_code}")
        elif "回测失败" in r2.text or "Internal Server Error" in r2.text:
            fail("回测返回错误", r2.text[:300])
        elif "0.0%" in r2.text and r2.text.count("0.0%") > 4:
            fail("回测指标疑似全为 0（多处出现 0.0%）", "策略可能缺少出仓信号")
        elif "年化收益" in r2.text or "tab-overview" in r2.text:
            ok(f"POST /backtest/run 返回有效结果（含年化收益字段）")
        else:
            fail("回测结果格式异常", r2.text[:300])
except Exception as e:
    fail(f"回测功能检查失败: {e}")


# ─────────────────────────────────────────────────────────────
# 6. 策略猎手搜索（返回策略且有结构）
# ─────────────────────────────────────────────────────────────
section("策略猎手搜索检查")

try:
    r = S.post(BASE + "/hunt/search", timeout=30)
    if r.status_code != 200:
        fail(f"POST /hunt/search 返回 {r.status_code}")
    elif "请先设定投资目标" in r.text:
        ok("POST /hunt/search 正常（未设目标，提示设置）")
    elif "候选策略" in r.text or "策略" in r.text:
        ok("POST /hunt/search 返回策略结果")
    else:
        fail("POST /hunt/search 返回内容异常", r.text[:300])
except Exception as e:
    fail(f"策略猎手搜索失败: {e}")


# ─────────────────────────────────────────────────────────────
# 7. 服务端单元检查（SSH 到服务器跑策略信号生成）
# ─────────────────────────────────────────────────────────────
section("服务端策略信号检查（SSH）")

SSH_CHECK = """
cd /opt/quantprism && python3 -c "
import sys; sys.path.insert(0, 'app')
from market_data import fetch_stock_history, compute_technicals
from strategies.m7_leaps import M7Leaps
from strategies.qqq_leaps import QQQLeaps

df = fetch_stock_history('AAPL', period='2y')
df = compute_technicals(df)

m7 = M7Leaps({})
sigs = m7.generate_signals(df)
longs = [s for s in sigs if s.direction == 'long']
closes = [s for s in sigs if s.direction == 'close']
print(f'M7 LEAPS: {len(longs)} 开仓 {len(closes)} 平仓')
if len(longs) != len(closes):
    print('ERROR: 开仓平仓数量不匹配')
    sys.exit(1)

df2 = fetch_stock_history('QQQ', period='2y')
df2 = compute_technicals(df2)
qqq = QQQLeaps({})
sigs2 = qqq.generate_signals(df2)
longs2 = [s for s in sigs2 if s.direction == 'long']
closes2 = [s for s in sigs2 if s.direction == 'close']
print(f'QQQ LEAPS: {len(longs2)} 开仓 {len(closes2)} 平仓')
if len(longs2) != len(closes2):
    print('ERROR: 开仓平仓数量不匹配')
    sys.exit(1)
print('OK')
" 2>&1
"""

import os
import socket

# 只有从本机（非服务器）且有 SSH key 时才运行此检测
_ssh_key = os.path.expanduser("~/.ssh/id_ed25519")
_on_server = socket.gethostname().startswith("srv") or os.path.isdir("/opt/quantprism")

if _on_server:
    # 服务端直接运行 Python 检查，无需 SSH
    try:
        result = subprocess.run(
            ["python3", "-c", """
import sys; sys.path.insert(0, '/opt/quantprism/app')
from market_data import fetch_stock_history, compute_technicals
from strategies.m7_leaps import M7Leaps
from strategies.qqq_leaps import QQQLeaps
df = fetch_stock_history('AAPL', period='2y')
df = compute_technicals(df)
m7 = M7Leaps({})
sigs = m7.generate_signals(df)
longs = [s for s in sigs if s.direction == 'long']
closes = [s for s in sigs if s.direction == 'close']
print(f'M7 LEAPS: {len(longs)} 开仓 {len(closes)} 平仓')
assert len(longs) == len(closes), 'M7 开仓平仓不匹配'
df2 = fetch_stock_history('QQQ', period='2y')
df2 = compute_technicals(df2)
from strategies.qqq_leaps import QQQLeaps
qqq = QQQLeaps({})
sigs2 = qqq.generate_signals(df2)
longs2 = [s for s in sigs2 if s.direction == 'long']
closes2 = [s for s in sigs2 if s.direction == 'close']
print(f'QQQ LEAPS: {len(longs2)} 开仓 {len(closes2)} 平仓')
assert len(longs2) == len(closes2), 'QQQ 开仓平仓不匹配'
print('OK')
"""],
            capture_output=True, text=True, timeout=90,
            cwd="/opt/quantprism"
        )
        output = result.stdout + result.stderr
        if result.returncode != 0 or "OK" not in output:
            fail("策略信号检查失败", output[:300])
        else:
            lines = [l for l in output.strip().split("\n") if "LEAPS" in l or "OK" in l]
            ok("策略信号完整（开仓=平仓）: " + " | ".join(lines))
    except Exception as e:
        fail(f"服务端策略检查失败: {e}")
elif os.path.exists(_ssh_key):
    try:
        result = subprocess.run(
            ["ssh", "-i", _ssh_key, "-o", "StrictHostKeyChecking=no",
             "root@caotaibanzi.xyz", SSH_CHECK],
            capture_output=True, text=True, timeout=60
        )
        output = result.stdout + result.stderr
        if "ERROR" in output:
            fail("策略信号检查失败", output.strip())
        elif "OK" in output:
            lines = [l for l in output.strip().split("\n") if "LEAPS" in l or "OK" in l]
            ok("策略信号完整（开仓=平仓）: " + " | ".join(lines))
        else:
            fail("SSH 策略检查输出异常", output[:300])
    except Exception as e:
        fail(f"SSH 连接失败（跳过服务端检查）: {e}")
else:
    ok("SSH 策略检查跳过（无 SSH key，仅 HTTP 检查）")


# ─────────────────────────────────────────────────────────────
# 结果汇总
# ─────────────────────────────────────────────────────────────
total = PASS + FAIL
print(f"\n{'═'*50}")
print(f"  结果: {PASS}/{total} 通过  {'✓ 全部通过' if FAIL == 0 else f'✗ {FAIL} 项失败'}")
if ERRORS:
    print(f"\n  失败项:")
    for e in ERRORS:
        print(f"    - {e}")
print(f"{'═'*50}\n")

sys.exit(0 if FAIL == 0 else 1)

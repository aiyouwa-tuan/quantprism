#!/usr/bin/env python3
"""
QuantPrism 用户流程测试
模拟真实用户操作序列，验证跨页面数据流和状态一致性。
"""
import requests, re, sys

BASE = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://localhost:8000"
S = requests.Session()
PASS = 0; FAIL = 0; ERRORS = []

SEP = "=" * 55

def ok(msg):
    global PASS; PASS += 1; print(f"  PASS  {msg}")

def fail(msg, detail=""):
    global FAIL; FAIL += 1; ERRORS.append(msg)
    print(f"  FAIL  {msg}")
    if detail: print(f"       -> {detail[:300]}")

def section(t):
    print(f"\n== {t}")


# ===== 1. 保存正常值 =====
section("1. Save normal goals 30%/15%")
r = S.post(BASE + "/goals/save", data={
    "annual_return_target": "30", "max_drawdown": "15",
    "risk_per_trade": "2.0", "holding_period": "any",
})
ok("POST /goals/save 200") if r.status_code == 200 else fail(f"POST /goals/save {r.status_code}", r.text[:200])

r = S.get(BASE + "/goals")
ok("/goals return=30") if 'value="30"' in r.text else fail("/goals not showing 30")
ok("/goals drawdown=15") if 'value="15"' in r.text else fail("/goals not showing 15")

r = S.get(BASE + "/hunt")
ok("/hunt shows 30%") if "30%" in r.text else fail("/hunt missing 30%")


# ===== 2. 清空收益目标 =====
section("2. Clear annual return -> save -> verify")
r = S.post(BASE + "/goals/save", data={
    "annual_return_target": "", "max_drawdown": "15",
    "risk_per_trade": "2.0", "holding_period": "any",
})
ok("Clear return save OK") if r.status_code == 200 else fail(f"Clear return save {r.status_code}", r.text[:200])

r = S.get(BASE + "/goals")
ret_match = re.search(r'name="annual_return_target"[^>]*value="([^"]*)"', r.text)
if ret_match and ret_match.group(1) == "":
    ok("/goals return field empty")
elif not ret_match:
    ok("/goals return field empty (no value attr)")
else:
    fail(f'/goals return not empty: "{ret_match.group(1)}"')

ok("/goals drawdown still 15") if 'value="15"' in r.text else fail("/goals drawdown lost")

r = S.get(BASE + "/hunt")
ok("/hunt shows 'bu xian'") if "\u4e0d\u9650" in r.text else fail("/hunt not showing 'bu xian'")


# ===== 3. 清空回撤目标 =====
section("3. Clear drawdown -> verify")
r = S.post(BASE + "/goals/save", data={
    "annual_return_target": "20", "max_drawdown": "",
    "risk_per_trade": "2.0", "holding_period": "any",
})
ok("Clear drawdown save OK") if r.status_code == 200 else fail(f"Clear drawdown save {r.status_code}")

r = S.get(BASE + "/hunt")
ok("/hunt drawdown shows 'bu xian'") if "\u4e0d\u9650" in r.text else fail("/hunt drawdown not 'bu xian'")
ok("/hunt return shows 20%") if "20%" in r.text else fail("/hunt not showing 20%")


# ===== 4. 两个都清空 =====
section("4. Both empty -> verify")
r = S.post(BASE + "/goals/save", data={
    "annual_return_target": "", "max_drawdown": "",
    "risk_per_trade": "2.0", "holding_period": "any",
})
ok("Both empty save OK") if r.status_code == 200 else fail(f"Both empty save {r.status_code}", r.text[:200])

r = S.get(BASE + "/goals")
ok("/goals shows no-return-limit text") if "\u4e0d\u8bbe\u6536\u76ca\u4e0a\u9650" in r.text else fail("/goals missing return no-limit text")
ok("/goals shows no-drawdown-limit text") if "\u4e0d\u8bbe\u56de\u64a4\u4e0b\u9650" in r.text else fail("/goals missing drawdown no-limit text")

r = S.get(BASE + "/hunt")
count = r.text.count("\u4e0d\u9650")
ok(f"/hunt shows 'bu xian' x{count}") if count >= 2 else fail(f"/hunt only {count} 'bu xian' (need 2)")


# ===== 5. 搜索结果按钮 =====
section("5. Search result buttons")
# Restore some goals first so search works
S.post(BASE + "/goals/save", data={
    "annual_return_target": "15", "max_drawdown": "10",
    "risk_per_trade": "2.0", "holding_period": "any",
})
r = S.post(BASE + "/hunt/search")
ok("POST /hunt/search 200") if r.status_code == 200 else fail(f"/hunt/search {r.status_code}")
ok("has 'chong xin sou suo' btn") if "\u91cd\u65b0\u641c\u7d22" in r.text else fail("missing 'chong xin sou suo'")
ok("has startResearch()") if "startResearch" in r.text else fail("missing startResearch()")
ok("has 'zu he you hua' btn") if "\u7ec4\u5408\u4f18\u5316" in r.text else fail("missing 'zu he you hua'")
ok("has 'rang AI' btn") if "\u8ba9 AI \u518d\u627e\u66f4\u591a" in r.text else fail("missing 'rang AI' btn")


# ===== 6. 恢复原值 =====
section("6. Restore 50%/10%")
r = S.post(BASE + "/goals/save", data={
    "annual_return_target": "50", "max_drawdown": "10",
    "risk_per_trade": "2.0", "holding_period": "any",
})
ok("Restore OK") if r.status_code == 200 else fail(f"Restore failed {r.status_code}")

r = S.get(BASE + "/hunt")
ok("/hunt shows 50%") if "50%" in r.text else fail("/hunt restore failed")


# Summary
total = PASS + FAIL
print(f"\n{SEP}")
if FAIL == 0:
    print(f"  User Flow Test: {PASS}/{total} passed  ALL PASS")
else:
    print(f"  User Flow Test: {PASS}/{total} passed  {FAIL} FAILED")
    print(f"\n  Failed:")
    for e in ERRORS:
        print(f"    - {e}")
print(SEP)

sys.exit(0 if FAIL == 0 else 1)

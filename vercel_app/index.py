"""
QuantPrism — Vercel 备份入口
当 VPS (caotaibanzi.xyz) 不可用时提供基础只读视图。
数据来源: Supabase PostgreSQL (DATABASE_URL 环境变量)
"""
import os
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

app = FastAPI(title="QuantPrism Backup", version="1.0.0")

VPS_URL = os.getenv("VPS_URL", "https://caotaibanzi.xyz")

_STATUS_HTML = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>QuantPrism — 备用节点</title>
  <style>
    body {{ background:#08090a; color:#d0d6e0; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
            display:flex; align-items:center; justify-content:center; min-height:100vh; margin:0; }}
    .card {{ background:#111213; border:1px solid rgba(255,255,255,0.08); border-radius:16px;
             padding:48px; max-width:480px; width:100%; text-align:center; }}
    .logo {{ background:#5e6ad2; width:48px; height:48px; border-radius:12px;
             display:flex; align-items:center; justify-content:center; font-weight:700;
             font-size:16px; color:#fff; margin:0 auto 24px; }}
    h1 {{ font-size:22px; font-weight:600; color:#f7f8f8; margin:0 0 8px; }}
    p  {{ font-size:14px; color:#8a8f98; margin:0 0 24px; line-height:1.6; }}
    .badge {{ display:inline-block; background:rgba(94,106,210,0.15); color:#818cf8;
              font-size:12px; padding:4px 10px; border-radius:6px; margin-bottom:24px; }}
    a.btn {{ display:inline-block; background:#5e6ad2; color:#fff; padding:10px 24px;
             border-radius:8px; text-decoration:none; font-size:14px; font-weight:500; }}
    a.btn:hover {{ background:#4f5bbf; }}
    .status {{ margin-top:24px; font-size:12px; color:#3e3e44; }}
  </style>
</head>
<body>
  <div class="card">
    <div class="logo">QP</div>
    <div class="badge">备用节点 · Vercel</div>
    <h1>QuantPrism</h1>
    <p>
      主服务运行于 VPS。<br>
      如果您看到此页面，主节点可能正在维护中。<br>
      通常几分钟内恢复。
    </p>
    <a class="btn" href="{vps_url}">前往主节点 &rarr;</a>
    <div class="status">主节点: {vps_url}</div>
  </div>
</body>
</html>
""".format(vps_url=VPS_URL)


@app.get("/", response_class=HTMLResponse)
async def root():
    """重定向到 VPS 主节点，VPS 不可用时显示备用页面。"""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(VPS_URL, follow_redirects=True)
            if r.status_code < 500:
                from fastapi.responses import RedirectResponse
                return RedirectResponse(VPS_URL, status_code=302)
    except Exception:
        pass
    return HTMLResponse(_STATUS_HTML)


@app.get("/health")
async def health():
    return JSONResponse({"status": "vercel_backup", "vps": VPS_URL})


@app.get("/{path:path}", response_class=HTMLResponse)
async def catch_all(path: str):
    """所有路径都重定向到 VPS，或显示备用页面。"""
    import httpx
    target = f"{VPS_URL}/{path}"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(target, follow_redirects=True)
            if r.status_code < 500:
                from fastapi.responses import RedirectResponse
                return RedirectResponse(target, status_code=302)
    except Exception:
        pass
    return HTMLResponse(_STATUS_HTML)

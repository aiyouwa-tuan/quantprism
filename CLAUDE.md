# QuantPrism — Project Instructions

## 操作规范（重要）

**用户只负责：登录授权、支付购买。其余所有技术操作由 Claude 自动完成。**

- 代码修改后必须自动部署到 VPS，不需要用户执行任何命令
- 部署流程：修改本地文件 → `git push` → rsync 到 VPS → `chown -R www-data:www-data` → `systemctl restart quantprism` → 验证 HTTP 200
- rsync 之后必须修复文件权限，否则 `www-data` 用户无法读取
- 验证部署：`curl https://caotaibanzi.xyz/portfolio` 返回 200 即为成功
- 不得要求用户手动 SSH、git push、重启服务或修改配置文件

## 部署架构

| 项目 | 地址 | 服务 |
|---|---|---|
| QuantPrism | `caotaibanzi.xyz` | systemd `quantprism.service`，uvicorn 2 workers，VPS 端口 8000 |
| IBKR 数据 | `localhost:3001` | `ibkr-service`（pm2），直连 IB Gateway Docker 容器（端口 4003） |
| VPS | `82.180.131.159` | 根目录 `/opt/quant/Quant/`，服务用户 `www-data` |
| Vercel | `quantprism.vercel.app` | 备用入口，proxy 到 VPS |

## CI/CD 流程（GitHub Actions）

每次 `git push origin main` 自动触发 `.github/workflows/deploy.yml`：

1. **SCP 同步**：`app/`, `requirements.txt`, `scripts/`, `deploy/` → VPS `/opt/quant/Quant/`
2. **SSH 远程执行** `scripts/remote_deploy.sh`，该脚本：
   - `chown -R www-data:www-data`（修复文件权限）
   - 对比并同步 systemd service（`deploy/systemd/quantprism.service`）
   - 对比并同步 nginx config（`deploy/nginx/caotaibanzi.xyz.conf`）
   - `pip install -r requirements.txt`
   - `systemctl stop quantprism` → 清理端口 8000 残留进程 → `systemctl start quantprism`
   - 健康检查：`curl http://127.0.0.1:8000/` 返回 302 为正常

## 关键文件路径

| 文件 | 说明 |
|---|---|
| `scripts/remote_deploy.sh` | VPS 上执行的部署脚本（随 SCP 同步） |
| `scripts/run_prod.sh` | uvicorn 启动脚本，由 systemd 调用 |
| `deploy/systemd/quantprism.service` | systemd 服务定义 |
| `deploy/nginx/caotaibanzi.xyz.conf` | nginx 反向代理配置 |
| `.github/workflows/deploy.yml` | GitHub Actions CI/CD |

## 常见故障排查

- **端口 8000 占用**：`fuser 8000/tcp` 找到 PID，`kill -9 <PID>`，再 `systemctl start quantprism`
- **nginx 502**：检查 `deploy/nginx/caotaibanzi.xyz.conf` 是否有 `proxy_pass http://quantprism_app`，运行 `nginx -t` 验证配置
- **SSH key type -1**：secrets.VPS_SSH_KEY 写入方式必须用 `echo`，不能用 `printf '%s'`（后者会丢失换行导致 OpenSSH 无法识别）
- **pkill 危险**：绝不用 `pkill -f uvicorn`，会匹配并杀死运行脚本的 bash 进程。改用 `fuser 8000/tcp` 获取 PID 后精确 kill

---

## Skill routing

When the user's request matches an available skill, ALWAYS invoke it using the Skill
tool as your FIRST action. Do NOT answer directly, do NOT use other tools first.
The skill has specialized workflows that produce better results than ad-hoc answers.

Key routing rules:
- Product ideas, "is this worth building", brainstorming → invoke office-hours
- Bugs, errors, "why is this broken", 500 errors → invoke investigate
- Ship, deploy, push, create PR → invoke ship
- QA, test the site, find bugs → invoke qa
- Code review, check my diff → invoke review
- Update docs after shipping → invoke document-release
- Weekly retro → invoke retro
- Design system, brand → invoke design-consultation
- Visual audit, design polish → invoke design-review
- Architecture review → invoke plan-eng-review
- Save progress, checkpoint, resume → invoke checkpoint
- Code quality, health check → invoke health

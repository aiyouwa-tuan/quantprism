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

## 编码行为准则（Karpathy 原则）

> 减少常见 LLM 编码失误的行为规范。**这些准则偏谨慎而非偏速度，简单任务可酌情判断。**

### 1. 先思考再动手

**不猜测，不隐藏困惑，主动暴露权衡取舍。**

实现前：
- 明确说出假设，不确定时直接问
- 存在多种解读时，列出来让用户选，不要静默选择
- 有更简单方案时，说出来，必要时推回
- 有不清楚的地方，停下来，说明困惑点，再问

### 2. 极简主义

**只写解决问题的最小代码，不做任何推测性扩展。**

- 不添加未被要求的功能
- 单次使用的代码不做抽象封装
- 不加"灵活性"或"可配置性"（除非被要求）
- 不对不可能发生的场景做错误处理
- 写了 200 行能用 50 行完成的，重写

自问：「一个资深工程师会觉得这过度设计吗？」如果是，简化。

### 3. 外科手术式修改

**只动必须动的代码，只清理自己制造的烂摊子。**

修改已有代码时：
- 不"顺手优化"相邻代码、注释或格式
- 不重构没坏的东西
- 沿用现有风格，即使自己会做不同选择
- 发现无关的死代码，提一下——但不要删

自己的改动制造了孤儿时：
- 删掉**因自己改动**而不再使用的 import/变量/函数
- 不删除改动前就存在的死代码（除非被要求）

检验标准：每一行改动都能直接追溯到用户的需求。

### 4. 目标驱动执行

**定义成功标准，循环验证直到达成。**

把任务转化为可验证目标：
- "加校验" → "为非法输入写测试，再让测试通过"
- "修 bug" → "写能复现 bug 的测试，再让测试通过"
- "重构 X" → "重构前后测试都通过"

多步骤任务先给出简短计划：
```
1. [步骤] → 验证：[检查项]
2. [步骤] → 验证：[检查项]
3. [步骤] → 验证：[检查项]
```

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

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
| QuantPrism | `caotaibanzi.xyz` | systemd `quantprism.service`，uvicorn，VPS 端口 8001 |
| IBKR 数据 | `localhost:3001` | `ibkr-service`（pm2），直连 IB Gateway Docker 容器（端口 4003） |
| VPS | `82.180.131.159` | 根目录 `/opt/quant/Quant/`，服务用户 `www-data` |

## 部署命令（参考）

```bash
# 推送代码
cd /Volumes/MaiTuan2T/Quant && git add -A && git commit -m "xxx" && git push origin main

# 同步到 VPS（排除数据库和缓存）
rsync -avz --exclude='__pycache__' --exclude='*.pyc' --exclude='trading_os.db' \
  /Volumes/MaiTuan2T/Quant/app/ root@82.180.131.159:/opt/quant/Quant/app/

# 修复权限 + 重启
ssh root@82.180.131.159 "chown -R www-data:www-data /opt/quant/Quant/app/ && systemctl restart quantprism && sleep 5 && systemctl is-active quantprism"
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

# QuantPrism Deployment

这份仓库现在包含了最小可上线的部署骨架，用来修复此前线上暴露出的三类问题：

1. `caotaibanzi.xyz` 的 HTTPS 请求落到了错误服务
2. 同一个域名的不同路径落到了不同后端
3. 应用进程、数据库路径和反向代理缺少固定约束

## 目录

- `scripts/run_prod.sh`
- `deploy/systemd/quantprism.service`
- `deploy/nginx/caotaibanzi.xyz.conf`

## 推荐目录

```bash
/opt/quant/Quant
```

## 1. 启动应用

```bash
cd /opt/quant/Quant
./scripts/run_prod.sh
```

默认行为：

- 进入 `/opt/quant/Quant/app`
- 使用项目内 `venv`
- 监听 `127.0.0.1:8000`
- 默认数据库路径是 `/opt/quant/Quant/app/trading_os.db`

也可以通过环境变量覆盖：

```bash
HOST=127.0.0.1 PORT=8000 WORKERS=2 DATABASE_URL=sqlite:////opt/quant/Quant/app/trading_os.db ./scripts/run_prod.sh
```

如果你已经把仓库放到服务器上，也可以直接用一键安装脚本：

```bash
sudo bash /opt/quant/Quant/scripts/install_server.sh
```

## 2. systemd

把 `deploy/systemd/quantprism.service` 复制到：

```bash
/etc/systemd/system/quantprism.service
```

然后执行：

```bash
sudo systemctl daemon-reload
sudo systemctl enable quantprism
sudo systemctl restart quantprism
sudo systemctl status quantprism
```

## 3. nginx

把 `deploy/nginx/caotaibanzi.xyz.conf` 复制到：

```bash
/etc/nginx/sites-available/caotaibanzi.xyz.conf
```

再建立软链接：

```bash
sudo ln -s /etc/nginx/sites-available/caotaibanzi.xyz.conf /etc/nginx/sites-enabled/caotaibanzi.xyz.conf
sudo nginx -t
sudo systemctl reload nginx
```

这份配置保证：

- `http://caotaibanzi.xyz` 统一跳到 `https://caotaibanzi.xyz`
- `https://caotaibanzi.xyz/*` 全部反代到同一个 QuantPrism 进程
- `www.caotaibanzi.xyz` 统一 301 到主域名

## 4. 证书

如果服务器上没有有效证书，可以先申请：

```bash
sudo apt-get install certbot python3-certbot-nginx
sudo certbot --nginx -d caotaibanzi.xyz -d www.caotaibanzi.xyz
```

## 5. DNS / 入口检查

部署完成后，确认：

1. `caotaibanzi.xyz` 和 `www.caotaibanzi.xyz` 都只解析到一台对外 Web 服务器
2. 这台 Web 服务器的 `80/443` 都由 nginx 接管
3. OpenVPN-AS 不再绑定同一个 `443` 入口域名
4. Hostinger parked domain 的 DNS 记录已经移除

## 6. 验收

至少检查这些路径都返回 QuantPrism，而不是 parked page / OpenVPN：

```bash
curl -I https://caotaibanzi.xyz
curl https://caotaibanzi.xyz/healthz
curl https://caotaibanzi.xyz/goals
curl https://caotaibanzi.xyz/scan
curl https://caotaibanzi.xyz/risk
curl https://caotaibanzi.xyz/api/vix
curl https://caotaibanzi.xyz/api/regime
```

`/healthz` 正常返回：

```json
{"status":"ok"}
```

仓库里也附带了一个快速验收脚本：

```bash
bash /opt/quant/Quant/scripts/verify_production.sh https://caotaibanzi.xyz
```

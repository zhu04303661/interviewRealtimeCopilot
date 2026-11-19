# Interview Realtime Copilot

实时面试助手：Mac 桌面应用 + 网站（介绍、下载、账号、订阅、AI 转发与计费、管理后台）。

| 目录 | 内容 |
|---|---|
| `apps/desktop/` | 桌面应用（Electron + React + TypeScript） |
| `engine/` | 本地 Python 引擎：资料、实时转写、问题识别、回答提示、语音练习、复盘 |
| `web/` | 网站与云端服务（`web/server`），页面生成器（`web/build_site.py`），部署脚本（`web/deploy/`） |
| `marketing/` | 各渠道发布文案和带追踪标记的链接 |

开发命令和注意事项见 [AGENTS.md](AGENTS.md)。本文只讲**部署**。

---

## 一、两台服务器是什么关系

```
                      海外用户                                国内用户
                         │                                      │
                         ▼                                      ▼
        https://copilot.xichiuk.com            https://copilot.xichigroup.com.cn
        ┌──────────────────────────┐           ┌──────────────────────────────┐
        │ 英国主站（AWS 伦敦）       │           │ 国内入口（阿里云 河源）         │
        │ 18.134.135.24            │           │ 8.155.147.19                 │
        │                          │  /api/*   │                              │
        │ Caddy → 网站服务（Python） │◀──────────│ nginx                        │
        │  · 网页、安装包           │  /auth/*  │  · 网页、安装包：本机直接提供   │
        │  · 账号 / 订阅 / 用量     │   转发     │  · 账号、订阅、统计：转发到主站 │
        │  · AI 转发与计费          │           │  · 不存任何用户数据            │
        │  · 管理后台               │           └──────────────────────────────┘
        │  · 数据库（SQLite）       │
        └────────────┬─────────────┘
                     │ 服务器密钥
                     ▼
            AI 服务商 / Stripe
                     ▲
                     │ 桌面应用始终直连主站（登录、AI 请求）
               用户的 Mac
```

一句话：**英国是主站，深圳（河源）只是国内的「门面」**。

| | 英国主站 | 国内入口 |
|---|---|---|
| 域名 | `copilot.xichiuk.com` | `copilot.xichigroup.com.cn` |
| 位置 | AWS 伦敦，`18.134.135.24` | 阿里云华南2（河源），`8.155.147.19` |
| 登录方式 | `ssh -i ~/.ssh/ukssh.pem ubuntu@ec2-18-134-135-24.eu-west-2.compute.amazonaws.com` | `ssh xichi@8.155.147.19`（密钥登录） |
| Web 服务器 | Caddy（证书自动申请和续期） | nginx + certbot（定时自动续期） |
| 网页和安装包 | 本机提供 | 本机提供（国内访问和下载快） |
| 账号、订阅、用量、留言 | **唯一的数据库在这里** | 没有，全部转发到主站 |
| AI 转发 | 在这里（能访问 AI 服务商） | 不做（国内访问不了） |
| Stripe 回调 | 在这里 | 不接收 |
| 这台机器上的其他业务 | v2ray / x-ui（`uk.xichiuk.com`） | `xichigroup.com.cn` 现有网站、MySQL、Docker |

要点：

- **账号只有一套**。在哪个域名注册都一样；从国内站发起订阅，付款后会跳回国内站。
- **国内入口坏了**：只影响国内域名的访问，数据不会丢，英国站照常工作。
- **英国主站坏了**：两个域名都无法登录和订阅，桌面应用也用不了 AI；国内站的网页还能打开。
- **桌面应用不经过国内入口**，始终直连 `copilot.xichiuk.com`。
- 两台机器上都有别的业务，部署脚本只新增自己的站点配置，不改别人的。

---

## 二、日常部署

所有命令都在**仓库根目录**运行。

### 1. 改了网站内容或云端代码

```zsh
python3 web/build_site.py                      # 重新生成页面（改了文案或手册时）
cd web/server && uv run pytest -q && cd ../..  # 测试

# 先主站，后国内入口
sh web/deploy/deploy.sh ubuntu@ec2-18-134-135-24.eu-west-2.compute.amazonaws.com ~/.ssh/ukssh.pem copilot.xichiuk.com
sh web/deploy/deploy-mirror.sh
```

- `deploy.sh`：上传代码和页面，重启网站服务。保留服务器上的密钥、数据库和已上传的安装包。
- `deploy-mirror.sh`：把页面同步到国内入口，写好 nginx 配置；证书不存在时自动申请。
- 只改了后台逻辑（没动页面）时，只需要第一条；只改了页面时两条都要跑，否则两个站内容不一致。

### 2. 发布新的安装包

```zsh
cd apps/desktop && node scripts/package-mac.mjs && cd ../..   # 生成 dist-mac/*.dmg 和 latest.json
sh web/deploy/publish-installer.sh ubuntu@ec2-18-134-135-24.eu-west-2.compute.amazonaws.com ~/.ssh/ukssh.pem

cd apps/desktop && node scripts/package-win.mjs && cd ../..   # 生成 dist-win/*-setup.exe 和 latest-win.json
sh web/deploy/publish-installer.sh ubuntu@ec2-18-134-135-24.eu-west-2.compute.amazonaws.com ~/.ssh/ukssh.pem win
```

安装包会传到两台服务器，下载页读取 `latest.json`（Mac）和 `latest-win.json`（Windows）显示版本和下载按钮；还没发布 Windows 版时，Windows 卡片显示登记邮箱。

- Mac 版：需要 Apple 芯片的 Mac，以及 `uv python install 3.12`。
- Windows 版：在 Windows、Mac 或 Linux 上都能打包（会下载 Windows 版 Electron 和 Python）。需要 uv、curl、tar 和 NSIS 的 `makensis`
  （Windows：`winget install NSIS.NSIS`；Mac：`brew install makensis`；Linux：`apt install nsis`）。安装包按用户安装，不需要管理员权限；
  尚未代码签名，首次运行时 SmartScreen 会提示，点「更多信息 → 仍要运行」。卸载会保留 `%APPDATA%\Interview Realtime Copilot` 里的用户数据。

### 3. 让搜索引擎知道页面更新了（可选）

```zsh
python3 web/deploy/indexnow.py     # 提交给必应等；Google 和百度在各自后台提交 sitemap.xml
```

### 4. 部署后检查

```zsh
for h in copilot.xichiuk.com copilot.xichigroup.com.cn; do
  curl -s -o /dev/null -w "$h %{http_code}\n" https://$h/
  curl -s https://$h/api/me; echo
done
```

两个域名都应返回 `200` 和 `{"user": null, "payments": true}`。国内站的 `/api/me` 能返回，就说明到主站的转发是通的。

---

## 三、配置都放在哪里

### 英国主站

| 位置 | 内容 |
|---|---|
| `/etc/irc-web.env`（只有 root 可读） | 全部配置和密钥，见下表 |
| `/var/lib/irc-web/site.sqlite3` | 数据库：账号、订阅、用量、余额、价格表、留言、访问统计、加密后的 AI 服务商密钥 |
| `/opt/irc-web/server`、`/opt/irc-web/static` | 代码和页面（每次部署覆盖） |
| `/opt/irc-web/static/downloads/` | 安装包（部署时保留） |
| `/etc/caddy/sites/irc-web.conf` | 本站的 Caddy 配置（部署脚本生成） |
| `systemctl status irc-web` / `journalctl -u irc-web` | 服务状态和日志 |

`/etc/irc-web.env` 里的项目：

| 变量 | 作用 |
|---|---|
| `IRC_WEB_ORIGIN` | 主站地址 |
| `IRC_WEB_MIRRORS` | 允许的国内入口地址（部署脚本从 `mirror.env` 写入） |
| `IRC_WEB_DB` | 数据库路径 |
| `IRC_WEB_SECRET` | 加密 AI 服务商密钥用，首次部署自动生成。**丢了就要重新录入密钥** |
| `STRIPE_SECRET_KEY`、`STRIPE_WEBHOOK_SECRET` | Stripe 密钥和回调签名密钥 |
| `IRC_FREE_ALLOWANCE_USD`、`IRC_PRO_ALLOWANCE_USD` | 每月 AI 额度（不写时为 1 和 20） |

改完后执行 `sudo systemctl restart irc-web`。

### 国内入口

| 位置 | 内容 |
|---|---|
| `/var/www/irc-web/` | 页面；`downloads/` 里是安装包 |
| `/etc/nginx/sites-available/irc-web-mirror` | nginx 配置（部署脚本生成，不要手改） |
| `/etc/letsencrypt/live/copilot.xichigroup.com.cn/` | 证书，`certbot.timer` 自动续期 |

这台机器上**没有密钥，也没有数据库**。

### 仓库里

`web/deploy/mirror.env`：国内入口的地址、域名、IP。两个部署脚本都读它。里面没有任何密钥。

**密钥只写在服务器上，不要提交到仓库，也不要发到聊天里。**

---

## 四、管理命令（在英国主站上运行）

```zsh
ssh -i ~/.ssh/ukssh.pem ubuntu@ec2-18-134-135-24.eu-west-2.compute.amazonaws.com
# 配置文件只有 root 可读：由 root 读取配置，再降权到网站服务的用户运行
irc-admin() { sudo sh -c 'set -a; . /etc/irc-web.env; cd /opt/irc-web/server && exec setpriv --reuid ircweb --regid ircweb --init-groups /opt/irc-web/venv/bin/python -m irc_web.admin "$@"' -- "$@"; }

irc-admin set-openai-key              # 录入 AI 服务商密钥（输入不回显，加密存储）
irc-admin make-admin 邮箱              # 让某个账号能打开 /admin.html；remove-admin 取消
irc-admin usage                       # 本月各账号用量
irc-admin grant 邮箱 5 原因            # 给账号补 5 美元余额
irc-admin set-price 模型前缀 输入 缓存输入 输出 音频输入 音频输出 [每分钟]   # 每百万 token 的美元单价
```

管理后台：用管理员账号登录网站后打开 `/admin.html`，可以看注册、订阅、用量、流量来源、许愿单。

---

## 五、从零搭建

### 新的主站（Ubuntu，有 sudo）

1. 域名加一条 A 记录指向服务器，开放 80 和 443 端口。
2. 服务器上装好 Caddy，主配置里 `import /etc/caddy/sites/*.conf`。
3. 运行 `sh web/deploy/deploy.sh 用户@主机 密钥文件 域名`。脚本会创建系统用户 `ircweb`、Python 虚拟环境、systemd 服务、Caddy 站点和 `/etc/irc-web.env`。
4. 在服务器上录入 AI 服务商密钥（`set-openai-key`），在 `/etc/irc-web.env` 里填 Stripe 两个密钥，重启服务。
5. Stripe 后台：创建 Webhook 指向 `https://域名/api/stripe/webhook`，监听 `checkout.session.completed` 和 `customer.subscription.created/updated/deleted`；开启客户门户。
6. 在网站注册一个账号，用 `make-admin` 设为管理员。

### 新的国内入口（Ubuntu，nginx + certbot，有 sudo）

1. 准备一个**已备案**的域名，加 A 记录指向服务器。
2. 把本机 SSH 公钥加到服务器的 `~/.ssh/authorized_keys`。
3. 修改 `web/deploy/mirror.env` 里的地址、域名和 IP。
4. 先运行一次主站的 `deploy.sh`（让主站接受这个新入口），再运行 `sh web/deploy/deploy-mirror.sh`。域名解析生效后脚本会自动申请证书；没生效时先以 HTTP 提供，之后重跑一次即可。

---

## 六、常见问题

| 现象 | 原因和处理 |
|---|---|
| 国内站能打开，但登录或注册报错 | 到主站的转发不通。在国内服务器上 `curl -I https://copilot.xichiuk.com/api/me`；再看主站 `systemctl status irc-web` |
| 国内站登录提示「Cross-site request refused」 | 主站没有把国内域名列为可信。重新运行主站的 `deploy.sh`，检查 `/etc/irc-web.env` 里的 `IRC_WEB_MIRRORS` |
| 两个站页面内容不一样 | 只部署了其中一个。两条部署命令都跑一遍 |
| 订阅提示「Payments are not configured yet」 | `/etc/irc-web.env` 里没有 Stripe 密钥，或改完没重启 |
| 应用提示 AI 引擎暂时不可用 | 主站没有录入 AI 服务商密钥，或 `IRC_WEB_SECRET` 变了导致解密失败。重新 `set-openai-key` |
| 主站部署时代理断开约 1 秒 | 只有 Caddy 站点配置变化时才会重启 Caddy（它关闭了热加载接口）。平时部署不会 |
| 国内下载慢 | 检查阿里云实例的带宽：应为「按使用流量」，峰值 100 Mbps |
| 磁盘满 | 主站只有约 7 GB：删除 `/opt/irc-web/static/downloads/` 里的旧安装包 |

## 七、备份

唯一需要备份的是主站上的两个文件：

```zsh
ssh -i ~/.ssh/ukssh.pem ubuntu@ec2-18-134-135-24.eu-west-2.compute.amazonaws.com \
  "sudo sqlite3 /var/lib/irc-web/site.sqlite3 '.backup /tmp/site-backup.sqlite3' && sudo cat /tmp/site-backup.sqlite3" > site-backup-$(date +%F).sqlite3
```

以及 `/etc/irc-web.env`（含密钥，妥善保管）。国内入口没有需要备份的数据，随时可以用部署脚本重建。目前**没有自动备份**。

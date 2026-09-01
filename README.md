# X拾光（XGlow）

[English](README.en.md)

自托管的 X / Twitter **本地阅读与增量归档**系统。内容、媒体与访问控制全部落在你自己的机器上；公开阅读站与管理后台分离。

不调用 X 官方付费 API。抓取依赖你自己的网页登录 Cookie，经 [twscrape](https://github.com/vladkens/twscrape) 读取时间线，将文字、资料、图片、视频与 GIF 写入本机 SQLite 与文件系统。

> 非官方网页接口可能因平台改版、限流或登录校验而中断，亦可能与 X 现行服务条款冲突。请仅使用自己的会话、以合理频率归档你有权保存的内容，且不要分发 `data/` 目录。

许可证：[GNU Affero General Public License v3.0](LICENSE)

---

## 能力概览

**阅读**

- 账号导航（横幅 / 组件两种布局）与单账号时间线
- 简体中文 / English，偏好保存在浏览器
- 桌面、平板、手机与 Telegram Mini App 适配；系统或客户端明暗主题，可手动切换
- 原创、回复、转发、媒体、年份 / 月份筛选与本地全文搜索
- 回复以对话卡片呈现（原帖上下文 + 当前回复）；`@用户` 可跳转 X
- 图片灯箱、本地视频播放

**访问控制**

- 独立管理员后台（公开页不暴露入口）；首次运行设置密码
- 账号可设为公开或隐藏；隐藏账号仅管理员与获授权会员可见
- 会员账号、按人授权可读范围、个人 Bark / Telegram 通知订阅
- 5 分钟至 90 天的只读临时分享链接（服务端只存令牌哈希）

**抓取与通知**

- Cookie 粘贴提取、在线校验、多会话；按**最久未使用**轮换，避免请求堆在同一个号上
- HTTP / HTTPS / SOCKS5 代理
- 手动更新单个或全部账号；失败列表可一键只重试未恢复项
- 定时增量同步（5 分钟–7 天）
- Bark 与 Telegram 机器人 / Mini App：增量提醒、凭证失效告警、会员授权命令

**部署**

- Windows 一键脚本（venv + 可选本机防火墙规则）
- Docker / NAS：`compose.yaml`，数据目录单独挂载

---

## 要求

- Python **3.10+**（建议 3.12）
- 出站访问 X（通常需要代理）
- Docker 部署时：能构建镜像，并将 `./data` 持久化

---

## Windows 安装

1. 安装 Python，勾选 **Add Python to PATH**。
2. 在项目根目录用 PowerShell 运行 `setup-windows.ps1`（创建 `.venv` 并安装 `requirements.txt`）。
3. 双击 `start-windows.cmd`。公开站默认：

```text
http://127.0.0.1:8787
```

终端需保持运行；`Ctrl+C` 结束。服务监听全部网卡。同一局域网可用启动窗口给出的地址，例如 `http://192.168.1.20:8787`。以管理员身份运行安装脚本时，会添加仅允许本地子网访问 TCP 8787 的防火墙规则。

| 路径 | 用途 |
| --- | --- |
| `/` | 账号导航 |
| `/reader?account=1` | 指定账号阅读页 |
| `/login` | 会员登录 |
| `/admin` | 管理后台 |

---

## Docker

```yaml
# compose.yaml（项目已提供）
services:
  reader:
    build: .
    ports:
      - "8787:8787"
    volumes:
      - ./data:/data
```

```bash
docker compose up -d --build
```

镜像 **COPY** 源码，只有 `./data` 是绑定挂载。改 Python / 前端后需要重新 **build** 并 `--force-recreate`，仅 `restart` 不会带上代码。容器内 `127.0.0.1` 指向容器自身，代理应填宿主机或网关的局域网地址。

---

## 配置要点

首次打开 `/admin` 设置不少于 10 位的管理员密码（不可逆哈希，`data/admin-auth.json`）。

**代理**  
管理页填写 `http://`、`https://` 或 `socks5://` 地址，先测试再保存。校验 Cookie、拉时间线、下媒体都走该代理。

**抓取会话（Cookie）**  
在已登录的 `https://x.com` 复制 Cookie / 请求头 / cURL / JSON。后台会提取 `auth_token` 与 `ct0`，写入 `data/scraper-sessions.db`，接口不回显原文。可保存多个会话；请求按最近使用时间轮换。受保护账号要求**至少有一个 Cookie 对应账号已关注对方**，否则该时间线会失败而不是空成功。

**阅读账号**  
与抓取会话分开：前者是要归档的目标用户（可很多），后者是你自己的登录态。可分别开关公开展示、是否收录回复 / 转发。

**会员与分享**  
会员从 `/login` 进入，只能看到被分配的账号（外加公开账号，若其未关闭「显示公开」）。临时分享只开放单个账号的只读访问，到期自动失效。

**Bark / Telegram**  
Bark 仅在已有增量游标且本轮确有新内容时推送，首次全量归档不会刷屏。Telegram Mini App 需 HTTPS 站点地址与 Bot Token；Token 与 Webhook 密钥不会经管理 API 回传。

---

## 增量同步

- **首次读取条数**：尚无历史游标时的归档上限。
- **增量扫描上限**：本轮从 X 拉取的时间线条数上限（不是「最多保存几条」），界面最小 40。
- 停止条件是连续遇到**已经入库**的推文，而不是 `id <= 最大 id`。同一时刻连发时，平台可能漏掉其中一条；若用最大 id 做水位，空洞会被永远跨过。未入库的转发不会抬高游标。
- 多 Cookie 是同一串行扫描的备用凭证，不是并行爬虫。额度耗尽时会停止本轮剩余账号，避免把第二个会话也打满。

---

## 数据与安全

| 路径 | 内容 |
| --- | --- |
| `data/reader.db` | 账号、推文、会员、分享令牌哈希 |
| `data/scraper-sessions.db` | 抓取会话 |
| `data/settings.json` | 代理、调度、通知等 |
| `data/admin-auth.json` | 管理员密码哈希 |
| `data/media/`、`data/profiles/` | 媒体与头像 |

不要将 `data/` 提交到 Git 或发给他人。访问控制同时作用于列表、推文 API 与本地文件路径。

---

## 开发

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py
python -m unittest tests.test_core
```

环境变量：`HOST`、`PORT`（默认 `0.0.0.0:8787`）、`DATA_DIR`、`NO_BROWSER=1`。

---

## 致谢与声明

抓取层基于 [twscrape](https://github.com/vladkens/twscrape)。本项目与 X Corp. 无关联。请自行评估合规与账号风险。

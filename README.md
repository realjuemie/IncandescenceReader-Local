# Incandescence 本地 X 阅读器

这是一个可在 Windows 本地运行、之后可直接迁移到 NAS 的 X/Twitter 阅读与增量归档工具。公开阅读站与管理员后台相互分离：访客只能浏览本地归档，抓取凭证、代理、账号和更新任务只在管理员后台操作。

项目不使用付费 X API。它通过你自己的 X 网页登录 Cookie 和开源项目 [twscrape](https://github.com/vladkens/twscrape) 读取公开时间线，把文字、账号资料、图片、视频和 GIF 都保存到本机。网页内可添加并切换多个阅读账号，支持手动更新和定时更新。

> 非官方网页接口可能因 X 改版、限流、登录验证而暂时失效，也可能不符合 X 当前的服务条款。请只使用自己的登录会话，以合理频率归档你有权保存的公开内容；不要把 `data/` 目录分享给他人。

## 现在包含什么

- 公开账号导航页与阅读页，多账号浏览和切换；可按年份、月份筛选内容
- 阅读图片点击放大，支持点击遮罩空白处、关闭按钮或 `Esc` 退出
- 独立管理员后台与首次运行密码设置，公开页面不显示后台入口
- 用户公开状态管理；隐藏用户可按会员授权，未授权访客无法访问资料、内容和本地媒体
- 会员账号管理：管理员可创建、停用会员，并分别分配每位会员可查看的阅读账号
- 回复与被回复的原帖合并进同一张引用式对话卡片，原帖不会在后续翻页重复出现；每位作者使用自己的本地头像
- 正文、原帖和引用内容中的 `@用户` 均可直达对应 X 主页
- 可选 Bark 增量通知：包含账号头像、新增数量、内容摘要和阅读链接，并支持后台测试推送
- 完整 Cookie 自动提取、在线有效性验证和多抓取会话管理
- HTTP、HTTPS、SOCKS5 代理设置与连接测试
- 手动更新单个账号、手动更新全部账号
- 5 分钟到 7 天的自动更新间隔
- SQLite 本地数据库、图片/视频/GIF 本地文件
- 原创、回复、转发、媒体、年份、月份筛选和本地全文搜索
- Windows 一键安装/启动脚本
- Docker/NAS 部署文件

旧版 Electron 打包、在线存档组织清单、远程代理、赞助和其他与本地阅读无关的内容已移除。

## Windows 安装

### 1. 安装 Python

安装 Python 3.10 或更高版本，建议 Python 3.12。安装时勾选 **Add Python to PATH**。

### 2. 安装抓取组件

右键项目根目录的 `setup-windows.ps1`，选择“使用 PowerShell 运行”。脚本会在项目内创建 `.venv`，并安装固定版本的 `twscrape` 及其依赖。

也可以在 PowerShell 手动执行：

```powershell
cd "C:\path\to\IncandescenceReader-Local"
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### 3. 启动

双击 `start-windows.cmd`，浏览器会打开公开主页：

```text
http://127.0.0.1:8787
```

终端窗口需要保持运行。按 `Ctrl+C` 可停止服务。

服务默认监听所有本机网络接口。同一局域网设备可使用启动窗口显示的 LAN 地址，例如 `http://192.168.1.20:8787`。安装脚本以管理员身份运行时，会添加一条仅允许本地子网访问 TCP 8787 的 Windows 防火墙规则。

主要地址：

| 地址 | 用途 |
| --- | --- |
| `http://127.0.0.1:8787/` | 公开账号导航页 |
| `http://127.0.0.1:8787/reader?account=1` | 指定账号的公开阅读页 |
| `http://127.0.0.1:8787/login` | 会员登录页 |
| `http://127.0.0.1:8787/admin` | 管理员后台（公开页面不提供入口） |

## 首次配置

### 设置管理员密码

直接打开 `http://127.0.0.1:8787/admin`。第一次访问时设置至少 10 位的管理员密码，以后进入后台需要登录。密码只保存为不可逆哈希，位置是 `data/admin-auth.json`。

### 设置访问 X 的代理

登录 `/admin` 后，最上方第一块就是“访问 X 的网络代理”。打开开关并填写代理地址，例如本机代理软件常用的：

```text
http://127.0.0.1:7890
```

支持 `http://`、`https://` 和 `socks5://`。先点“测试连接”，成功后再点“保存代理”。凭证验证、时间线抓取、头像和媒体下载都会使用这项代理。

迁移到 Docker/NAS 后，容器里的 `127.0.0.1` 指向容器自身；应改填代理所在设备的局域网地址，或使用适合你的 Docker 网络地址。

### 添加免费抓取会话

1. 在浏览器打开并登录 `https://x.com`。
2. 从浏览器开发者工具或 Cookie 导出扩展复制整段 Cookie、请求头、Copy as cURL、JSON 或 Cookie 表格。
3. 进入 `/admin` 的“抓取账号凭证”，直接粘贴全部内容，无需手动寻找字段。
4. 页面会自动识别所需字段；点击“提取、验证并保存”，只有实际通过 X 登录验证的凭证才会保存。

系统只保留抓取所需的 `auth_token` 和 `ct0`，写入 `data/scraper-sessions.db`；原始 Cookie 不会由 API 回显或写入日志。Cookie 失效或 X 要求重新验证时，可以在后台重新验证或用相同会话名称覆盖更新。

### 添加阅读账号

在 `/admin` 的“用户管理”中填写目标 X 用户名。添加后点击“立即更新”。公开主页会自动显示设为“公开展示”的账号、最近更新时间、本地阅读页和 X 官方主页链接。关闭“公开展示”后，游客无法访问该用户的资料、内容和本地媒体；管理员登录后仍可从“预览”进入阅读页。

“阅读账号”和“抓取会话”是两类数据：

- 阅读账号：你想归档和切换阅读的公开账号，可以有很多个。
- 抓取会话：你自己的 X 登录状态，只负责访问网页接口，通常一个即可。

受保护账号只有在抓取会话本身有权查看时才可能读取。

### 管理会员访问范围

进入 `/admin` 的“会员管理”，可以创建会员、停用登录、重置密码，并勾选该会员能够查看的阅读账号。公开展示的账号仍可由所有访客访问；不公开的账号只有管理员和被明确授权的会员能访问。

会员从 `/login` 登录后，可在主页看到“会员专属”账号。访问权限同时作用于账号列表、推文、年月筛选接口以及本地头像和媒体文件，不能只靠猜测文件地址绕过。会员密码以不可逆哈希保存在 `data/reader.db` 中。

### 设置 Bark 通知

在 `/admin` 的“Bark 更新通知”中填写 Bark 服务器地址和 App 提供的 Device Key。默认服务器是 `https://api.day.app`，也支持填写自建 Bark Server 地址。Device Key 保存后不会由管理接口回传到网页。

“站点访问地址”应填写手机能够打开的地址，例如 `http://192.168.1.20:8787`。通知只在已有增量游标、且本次确实新增内容时发送；首次归档不会用历史内容刷屏。点击“测试推送”可以验证服务器和密钥。通知标题为 `@用户 有 N 条新内容`，正文包括内容类型和最新摘要，图标使用该 X 用户头像。

## 增量更新原理

首次更新只读取设置中的“首次读取条数”，默认 100 条，不会尝试回填整个历史。

每个阅读账号在 SQLite 中保存 `last_tweet_id`。后续更新会：

1. 从账号最新时间线开始读取；
2. 只接受 ID 大于 `last_tweet_id` 的内容；
3. 连续遇到旧内容后立即停止，避免向下遍历全部历史；
4. 依靠推文 ID 主键去重；
5. 只查询 `local_path` 为空或上次下载失败的媒体记录；
6. 已存在的本地文件直接跳过，不重新下载。

“增量扫描上限”默认 500。若某个账号在两次更新之间可能发布超过 500 条，可在设置中提高到 3200，或缩短自动更新间隔。

## 数据目录

所有可写数据都在项目的 `data/`，且已被 `.gitignore` 排除：

```text
data/
  admin-auth.json           # 管理员密码哈希与会话密钥
  reader.db                 # 阅读账号、推文、媒体索引、同步游标
  reader.db-wal
  settings.json             # 自动更新、代理和 Bark 设置（可能包含 Bark Device Key）
  scraper-sessions.db       # X 登录 Cookie，会话敏感文件
  scraper-session-meta.json # 抓取会话验证状态（不含 Cookie）
  media/
    <username>/<tweet-id>/  # 原图、最高码率 MP4、GIF 视频和预览图
  profiles/
    <username>/             # 监控账号头像、横幅及推文真实作者头像
```

备份时停止程序后复制整个 `data/` 即可。请把备份当作敏感数据保存。

## 自动更新

在 `/admin` 右侧的“自动增量更新”中打开开关、设置分钟数并保存。调度器运行在本地服务进程内：服务停止时不会更新，重新启动后会重新开始计时。

若同步失败，错误会显示在对应账号下。媒体下载失败不会丢失推文；下一次同步只重试失败媒体，不会扫描所有成功文件。

## NAS / Docker

项目已经使用跨平台路径，所有状态集中在 `DATA_DIR`，可直接迁移。

在装有 Docker Compose 的 NAS 上：

```bash
docker compose up -d --build
```

访问：

```text
http://NAS_IP:8787
```

`compose.yaml` 将当前目录的 `data/` 映射到容器 `/data`。从 Windows 迁移时，先停止 Windows 服务，再把完整 `data/` 复制到 NAS 项目目录。IP/环境变化可能使 X 会话失效，此时在 NAS 页面重新导入 Cookie。

默认 Windows 服务监听 `0.0.0.0`，局域网设备可通过 Windows 主机的 IPv4 地址访问。若只允许本机访问，可设置：

```powershell
$env:HOST = "127.0.0.1"
$env:PORT = "8787"
.\.venv\Scripts\python.exe .\app.py
```

管理员后台已有独立密码认证；公开账号无需登录，会员专属账号需使用 `/login` 的会员账号。不要把未加密的 HTTP 服务直接暴露到公网；NAS 上建议通过反向代理启用 HTTPS，并按需要为公开站增加外层访问控制。

支持的环境变量：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `HOST` | `0.0.0.0` | 监听地址；设为 `127.0.0.1` 时仅本机可访问 |
| `PORT` | `8787` | Web 端口 |
| `DATA_DIR` | `项目/data` | 数据与媒体目录 |
| `NO_BROWSER` | 未设置 | 设为 `1` 时启动后不自动打开浏览器 |
| `ADMIN_PASSWORD` | 未设置 | 可选：首次启动时预设管理员密码（至少 10 位） |
| `COOKIE_SECURE` | 未设置 | 使用 HTTPS 时设为 `1`，为后台登录 Cookie 增加 Secure 属性 |
| `TWS_PROXY` | 未设置 | 可选的代理环境变量；网页中保存的代理设置优先 |
| `TWS_TELEMETRY` | `0` | 本项目默认关闭 twscrape 匿名遥测 |

## 测试

核心测试不需要连接 X：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

测试覆盖设置边界、Cookie 提取、账号校验、管理员与会员认证、内容和媒体访问隔离、SQLite 去重/分页，以及第二次同步是否带入第一次保存的增量游标。

## 项目结构

```text
app.py                         # 启动入口
incandescence/
  config.py                    # 本地设置
  auth.py                      # 管理员密码与登录会话
  member_auth.py               # 会员密码、会话与账号授权
  notifications.py             # Bark 测试与增量更新通知
  database.py                  # SQLite 数据层
  scraper.py                   # twscrape Cookie 抓取适配器
  media.py                     # 媒体增量下载与安全路径
  sync_service.py              # 单账号/全部账号同步与调度器
  web.py                       # 本地 HTTP/API 与 Range 媒体服务
public/
  home.html / home.js          # 公开账号导航页
  index.html / app.js          # 公开阅读页
  admin.html / admin.js        # 管理员后台
  styles.css
  favicon.svg                  # 网站图标
tests/
Dockerfile
compose.yaml
```

## License

本地化版本基于 [sjshb57/IncandescenceReader](https://github.com/sjshb57/IncandescenceReader) 改造，并沿用 GNU Affero General Public License v3.0。存档内容的版权归原作者所有。

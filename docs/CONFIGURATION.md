# 配置

所有命令在仓库根目录执行。资讯阅读服务没有第三方 Python 运行时依赖。

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `--host` | `127.0.0.1` | 默认只允许本机。Kindle 访问时明确填写主机自己的局域网 IPv4 地址 |
| `--port` | `8766` | HTTP 端口 |
| `--state-dir` | `state` | 私密状态目录，包括访问码、问答和资讯缓存 |
| `--sdk-socket` | `/run/musegadget/musegadget.sock` | 官方 SDK 本地连接；不存在时只禁用问答 |
| `--publish-socket` | `STATE_DIR/publish.sock` | 接收回答与后台投递的本地 Unix socket；systemd 模板明确设为 `/run/kindle-muse-bridge/publish.sock` |

`--help` 查看全部参数。Unix socket 路径必须尽量短（通常不超过约 100 字节）；从较短的工作目录运行本地开发。

## Muse 适配层

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `MUSEGADGET_RUN_AS` | `kindle-muse` | 命令回调降权使用的本地账户；禁止配置有 sudo 权限的个人账户 |
| `KINDLE_MUSE_DISPLAY_NAME` | `Kindle Muse Reader` | 云端设备显示名称 |
| `KINDLE_MUSE_PUBLISH_SOCKET` | `/run/kindle-muse-bridge/publish.sock` | 必须与阅读服务的 `--publish-socket` 一致 |
| `MUSEGADGET_STATE_DIR` | `/var/lib/musegadget` | 上游 SDK 的身份、配对和令牌目录；阅读账户不能读取 |
| `MUSEGADGET_SOCKET` | `/run/musegadget/musegadget.sock` | 上游 SDK 本地消息 socket；与阅读服务一致 |

适配层继承上游受限子进程环境；只把非秘密的回调 socket 路径作为参数传给子进程，不传 SDK 令牌。生产部署路径在 systemd 模板中固定，改变安装位置时需要同时修改两个服务文件。

## 资讯与显示

来源固定为 `https://aihot.news/api/v1/items`，每个 `selected` / `all` 模式缓存最近七天最新至多 100 条，保留源站时间线顺序。这不是完整历史归档。默认首页和分类显示精选；`/?mode=all` 是兼容的全部列表。

每个模式最短检查间隔 60 秒；来源更长的缓存 TTL 和 `Retry-After` 优先。首页第一页再每 60 秒刷新，后续页、摘要、提问和回答不会自动刷新。端到端显示有轮询延迟，不是实时推送。所有显示日期使用 `Asia/Shanghai`。

## 私密状态

`reader.sqlite3`：提问、回答、登录会话、历史后台投递和来源核验。`aihot.sqlite3`：最近资讯快照与同步状态。`access_code`：随机八位登录码。目录权限 0700，数据库和访问码 0600；systemd 使用 UMask 0077。

备份数据库请使用 SQLite 的 backup API 或先停服务再复制。只更改访问码文件不会使已有登录 Cookie 立即失效；轮换时需停止服务、修改码并清空 sessions 表，再重启。不要发布运行目录、备份或配对文件。

## 主要路由

| 路由 | 内容 |
| --- | --- |
| `/` | 资讯首页及分类，需登录 |
| `/ai-news/{id}` | 缓存条目的摘要与出处，需登录 |
| `/ask` | Muse 提问与历史，需登录 |
| `/job/{id}` | 完整回答分页，需登录 |
| `/health` | 无秘密的连接状态 JSON，无需登录；不代表完整云端收发验收 |
| `/inbox` | 保留的后台投递阅读直链，需登录；首页不显示入口 |

没有通过公网 HTTP 写入回答或消息的 API；回调仅通过本地 Unix socket。

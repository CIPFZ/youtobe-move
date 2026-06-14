# hk-server — YouTube 视频每日发现与下载服务

香港服务器端，定时从 YouTube 发现指定分类的热门视频并下载，提供 HTTP API 供本地拉取。

Stage 3 DB/config 简化已完成：当前核心表为 `videos`，统一使用 `status` 表示视频生命周期；语言、评论数、点赞数等 yt-dlp 搜索路径不可靠字段已从模型、DB 和评分逻辑中移除；发现缓存路径和 TTL 已配置化。

## 架构

```
hk-server (常驻进程 :8503)
├── 后台定时器 — 周期执行发现 + 下载
├── GET  /api/health        — 健康检查
├── GET  /api/tasks         — 当前/最近任务状态
├── GET  /api/videos        — 视频列表（状态/分页）
├── GET  /api/videos/<id>   — 视频详情
├── GET  /api/videos/<id>/meta  — 完整元信息 JSON
├── GET  /api/videos/<id>/file?type=video|audio|thumbnail — 流式下载
├── POST /api/videos/<id>/confirm-pulled — 确认拉取，服务器删除
├── GET  /api/stats         — 存储统计
├── POST /api/discovery/run — 手动触发发现下载
└── POST /api/downloads     — 手动提交 URL 下载
```

## 依赖

```
certifi>=2024.0.0
yt-dlp>=2024.0.0
pydantic-settings>=2.0.0
python-dotenv>=1.0.0
socksio>=1.0.0     # 可选: socks5 代理
```

## 快速部署

```bash
cd hk-server
cp .env.example .env   # 编辑填入配置
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
hk-server              # 启动常驻服务
```

## 运行模式

### hk-server (常驻) — 推荐

HTTP API + 后台定时发现。发现周期由 `DISCOVERY_INTERVAL_MINUTES` 控制。

```bash
hk-server
# API server listening on http://0.0.0.0:8503
# Discovery timer started (interval=1440 min)
```

### hk-scheduler (单次)

执行一次完整流程后退出，适合 crontab。

## API

JSON API 成功响应统一为：

```json
{"ok": true, "data": {}}
```

JSON API 错误响应统一为：

```json
{"ok": false, "error": {"code": "not_found", "message": "Video not found"}}
```

文件下载接口直接返回文件流，不包 JSON。

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查 |
| GET | `/api/tasks` | 当前/最近任务状态 |
| GET | `/api/videos?status=downloaded` | 待拉取列表；推荐查询参数 |
| GET | `/api/videos?download_status=downloaded` | 旧查询参数，兼容别名 |
| GET | `/api/videos/<id>` | 视频详情 |
| GET | `/api/videos/<id>/meta` | 完整 .video_info.json |
| GET | `/api/videos/<id>/file?type=video` | 下载视频流(.mp4) |
| GET | `/api/videos/<id>/file?type=audio` | 下载音频流(.m4a) |
| GET | `/api/videos/<id>/file?type=thumbnail` | 下载封面图 |
| POST | `/api/videos/<id>/confirm-pulled` | 确认拉取，删除服务器文件并标记 pulled |
| DELETE | `/api/videos/<id>/files` | 管理员强制删除服务器文件并标记 expired |
| GET | `/api/stats` | 存储统计 |
| POST | `/api/discovery/run` | 手动触发发现下载 |
| POST | `/api/downloads` | 手动提交 URL 下载 |

## 配置

核心配置项（`.env`）：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| YTDLP_PROXY | (空) | socks5 代理 |
| YTDLP_VIDEO_FORMAT | bestvideo[ext=mp4] | 视频格式 |
| YTDLP_AUDIO_FORMAT | bestaudio[ext=m4a] | 音频格式 |
| DISCOVERY_TOPIC_TYPES | pets,beauty,funny | 分类 |
| DISCOVERY_TOP_N | 5 | 每日选取数 |
| DISCOVERY_INTERVAL_MINUTES | 1440 | 发现周期 |
| DISCOVERY_DB_PATH | runtime/discovery/discovery.db | SQLite 路径 |
| DISK_MAX_STORAGE_GB | 50 | 存储上限 |
| DISK_MAX_RETENTION_DAYS | 7 | 保留天数 |
| DOWNLOAD_INTERVAL_SEC | 180 | 下载间隔 |
| API_PORT | 8503 | 端口 |

Stage 3 新增配置：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| DISCOVERY_CACHE_PATH | runtime/discovery/candidates_cache.json | 候选缓存路径 |
| DISCOVERY_CACHE_TTL_SEC | 86400 | 候选缓存 TTL |

Stage 3 已删除配置：

| 配置项 | 原因 |
|--------|------|
| DISCOVERY_DAYS_BACK | yt-dlp 搜索路径无法可靠按日期过滤 |
| DISCOVERY_MIN_COMMENTS | yt-dlp 搜索结果没有可靠评论数 |
| DISCOVERY_TOPIC_{X}_LANGUAGES | 当前语言字段通常为空，过滤约束力弱 |

## 数据库状态

当前实现：

```text
videos.status
```

状态集合：

```text
pending -> downloading -> downloaded
pending -> downloading -> failed
downloaded -> pulled
downloaded -> expired
```

`language_hint`、`comment_count`、`like_count` 等不可靠字段已从核心视频表移除。

## 数据流

```
YouTube → ytsearchN → 评分→TopN → SQLite → yt-dlp 双流下载
                                              │
                                     runtime/downloads/<cat>/<id>/
                                     ├── <id>.mp4     视频流
                                     ├── <id>.m4a     音频流
                                     ├── <id>.video_info.json  元信息
                                     └── <id>.thumbnail.jpg    封面
```

本地拉取后用 ffmpeg 合并:
```bash
ffmpeg -i video.mp4 -i audio.m4a -c copy merged.mp4
```

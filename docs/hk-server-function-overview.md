# hk-server 功能梳理与概览

本文只梳理 `hk-server/` 目录。按当前目标，它是远程香港服务器上的“搜索 + 下载 + 文件中转”服务：负责从 YouTube 找视频、下载视频/音频/封面/元数据，并通过 HTTP API 让本地服务拉取。

当前是第一版开发阶段，不需要保留历史兼容包袱。后续发现设计或实现不合理，可以直接删除、重构、简化。

阶段 3（DB/config 简化）已完成：当前代码以 `videos.status` 为核心状态字段；语言、评论数、点赞数等 yt-dlp 搜索路径无法可靠提供的字段已从模型、DB 和评分逻辑中移除。

## 1. 当前定位

`hk-server` 是一个独立 Python 包，依赖较少：

- `yt-dlp`：搜索 YouTube、下载视频流和音频流。
- `pydantic-settings` / `python-dotenv`：读取 `.env` 配置。
- `certifi`：修复 SSL CA。
- Python 标准库 `http.server`：提供 HTTP API。
- SQLite：保存视频发现和下载状态。

它不负责：

- 本地平台发布。
- B 站上传。
- 音视频合并。
- 转写、翻译、字幕、配音。
- 前端页面。

这些能力应放在本地端或其他独立服务里。

## 2. 目录结构

```text
hk-server/
  pyproject.toml
  README.md
  app/
    __init__.py
    _ssl_patch.py
    settings.py
    logging_utils.py
    scheduler.py
    api.py
    downloader.py
    download_service.py
    disk_cleaner.py
    discovery/
      __init__.py
      models.py
      scoring.py
      service.py
      youtube_discovery.py
      repository.py
```

主要模块分工：

| 模块 | 功能 |
| --- | --- |
| `app/settings.py` | 所有运行配置和默认值 |
| `app/scheduler.py` | 命令入口，启动单次任务或常驻 API 服务 |
| `app/api.py` | HTTP API，供本地服务查询和拉取文件 |
| `app/download_service.py` | 发现、缓存、入库、下载、清理的主编排 |
| `app/downloader.py` | 单视频下载，保存视频流、音频流、封面、元数据 |
| `app/disk_cleaner.py` | 按容量和保留天数清理旧文件 |
| `app/discovery/service.py` | 解析分类、关键词、语言配置 |
| `app/discovery/youtube_discovery.py` | 使用 `yt-dlp ytsearchN:<keyword>` 搜索候选 |
| `app/discovery/scoring.py` | 过滤候选、计算热度分、去重排序 |
| `app/discovery/repository.py` | SQLite 建表、查询、状态更新 |

## 3. 运行入口

`pyproject.toml` 暴露两个命令：

| 命令 | 入口 | 说明 |
| --- | --- | --- |
| `hk-server` | `app.scheduler:run_server` | 常驻服务，启动 HTTP API 和后台定时发现下载 |
| `hk-scheduler` | `app.scheduler:run_scheduler` | 执行一次发现、下载、清理后退出 |

常驻模式：

```bash
cd hk-server
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
hk-server
```

单次模式：

```bash
cd hk-server
source .venv/bin/activate
hk-scheduler
```

`hk-server` 启动后会：

1. 初始化 SQLite。
2. 启动 HTTP API，默认 `0.0.0.0:8503`。
3. 启动后台线程，每隔 `DISCOVERY_INTERVAL_MINUTES` 执行一次 `run_discovery_and_download()`。

## 4. 功能总览

### 4.1 视频搜索发现

当前搜索方式：

```text
yt-dlp extract_info("ytsearchN:<keyword>", download=False)
```

特点：

- 不依赖 YouTube Data API Key。
- 没有 API 配额限制。
- 依赖 YouTube 网页搜索结果，稳定性取决于 `yt-dlp` 和 YouTube 页面结构。
- `extract_flat='in_playlist'` 得到的是扁平搜索结果，字段有限。

支持分类：

| 分类 | 默认是否启用 | 默认关键词示例 |
| --- | --- | --- |
| `pets` | 是 | cute pets, funny cats, funny dogs |
| `beauty` | 是 | beauty, makeup tutorial, fashion |
| `funny` | 是 | funny videos, comedy, pranks |
| `ai` | 否 | AI, LLM, OpenAI |
| `tech` | 否 | technology, tech news |
| `digital` | 否 | gadgets, smartphone review |

默认启用：

```text
DISCOVERY_TOPIC_TYPES=pets,beauty,funny
```

可额外配置：

```text
DISCOVERY_KEYWORDS=keyword1,keyword2
```

发现结果字段来自 `VideoCandidate`：

| 字段 | 说明 |
| --- | --- |
| `video_id` | YouTube 视频 ID |
| `url` | YouTube URL |
| `title` | 标题 |
| `channel_title` | 频道名 |
| `published_at` | 上传日期，来自 `upload_date` 转 ISO |
| `duration_sec` | 时长 |
| `view_count` | 播放量 |
| `keyword` | 命中的搜索关键词 |
| `category` | 分类 |
| `score` | 热度分 |
| `raw_json` | yt-dlp 原始搜索结果 JSON |

旧实现曾保留 `language_hint`、`comment_count`、`like_count` 等字段，但这些值在
yt-dlp 扁平搜索结果里通常为空或固定为 0；阶段 3 已将它们从核心模型、DB 和评分逻辑中删除。

### 4.2 候选过滤和评分

过滤逻辑在 `app/discovery/scoring.py::should_keep_candidate()`：

- 播放量必须 >= `DISCOVERY_MIN_VIEWS`。
- 时长必须在 `DISCOVERY_MIN_DURATION_SEC` 和 `DISCOVERY_MAX_DURATION_SEC` 之间。



评分逻辑：

```text
score = log10(max(10, view_count)) + freshness
```

当前评分只依赖播放量和新鲜度，不再依赖搜索结果中不可靠的评论数、点赞数或语言字段。

去重逻辑：

- 按 `video_id` 去重。
- 同一个视频如果由多个关键词命中，保留 score 更高的记录。
- 按 score 倒序取 `DISCOVERY_TOP_N`。

### 4.3 候选缓存

`download_service.py` 有一层发现缓存：

```text
runtime/discovery/candidates_cache.json
```

当前缓存策略：

- TTL 由 `DISCOVERY_CACHE_TTL_SEC` 控制。
- 如果缓存新鲜，跳过 YouTube 搜索，直接从缓存候选重新评分并取 TopN。
- 如果缓存过期或不存在，执行完整搜索，并将 raw candidates 保存到缓存。
- 缓存文件包含 `provider`、`keywords`、`search` 和 `items`。
- 如果关键词、分类或搜索过滤参数变化，旧缓存不会被复用。

缓存路径和 TTL 由配置驱动：

```text
DISCOVERY_CACHE_PATH=runtime/discovery/candidates_cache.json
DISCOVERY_CACHE_TTL_SEC=86400
```

### 4.4 自动下载

主流程：

```text
run_discovery_and_download()
  -> init_db()
  -> 读取或刷新候选缓存
  -> upsert_candidates()
  -> get_pending_downloads(score >= DISCOVERY_DOWNLOAD_MIN_SCORE)
  -> download_media()
  -> mark_downloaded() / mark_download_failed()
  -> cleanup_if_needed()
```

下载条件：

- `status='pending'`
- `score >= DISCOVERY_DOWNLOAD_MIN_SCORE`
- 每轮最多取 50 条 pending。

下载目录：

```text
runtime/downloads/{category}/{video_id}/
```

保存文件：

```text
{video_id}.mp4
{video_id}.m4a
{video_id}.thumbnail.{jpg|png|webp}
{video_id}.video_info.json
```

当前服务刻意不合并音视频。它下载视频流和音频流，本地端拉取后再用 ffmpeg 合并。

下载间隔：

```text
DOWNLOAD_INTERVAL_SEC=180
```

用于降低 YouTube 限流风险。

### 4.5 单 URL 手动下载

API 支持手动提交一个 YouTube URL：

```http
POST /api/downloads
Content-Type: application/json

{
  "url": "https://www.youtube.com/watch?v=xxxxxxxxxxx",
  "category": "manual"
}
```

行为：

1. API 立即返回 `{started: true, video_id, url}`。
2. 后台线程从 URL 中提取 11 位 `video_id`。
3. 如果 DB 中没有该视频，插入最小记录。
4. 下载视频流、音频流、封面和元数据。
5. 下载完成后标记为 `downloaded`。

限制：

- URL 解析使用正则 `(?:v=|/)([a-zA-Z0-9_-]{11})`，能覆盖常见链接，但不够严格。
- 手动下载和发现下载共用进程内任务锁，同一时间只允许一个后台任务运行。
- 如果后台下载失败，当前代码会调用 `mark_download_failed()` 落库。

### 4.6 HTTP API

认证方式：

```http
Authorization: Bearer <API_TOKEN>
```

如果 `API_TOKEN` 为空，则不做认证。

当前实际实现的端点：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/videos` | 查询视频列表 |
| `GET` | `/api/videos/<id>` | 查询视频详情 |
| `GET` | `/api/videos/<id>/meta` | 读取下载目录中的 `.video_info.json` |
| `GET` | `/api/videos/<id>/file?type=video` | 下载 `.mp4` 视频流 |
| `GET` | `/api/videos/<id>/file?type=audio` | 下载 `.m4a` 音频流 |
| `GET` | `/api/videos/<id>/file?type=thumbnail` | 下载封面图 |
| `POST` | `/api/videos/<id>/pull-lock` | 拉取前锁定视频，状态变为 `pulling` |
| `POST` | `/api/videos/<id>/release-pull-lock` | 拉取失败释放锁，状态回到 `downloaded` |
| `POST` | `/api/videos/<id>/confirm-pulled` | 确认本地已拉取，删除磁盘目录并标记 `pulled` |
| `POST` | `/api/videos/<id>/mark-published` | 本地发布成功后回写 `published` |
| `DELETE` | `/api/videos/<id>/files` | 管理员强制删除磁盘目录并标记 `expired` |
| `GET` | `/api/stats` | 查询统计 |
| `GET` | `/api/metrics` | Prometheus 文本指标 |
| `GET` | `/api/admin/disk` | 磁盘和下载存储状态 |
| `POST` | `/api/admin/cleanup/run` | 手动执行磁盘清理 |
| `POST` | `/api/admin/tasks/<id>/force-fail` | 强制标记任务失败 |
| `POST` | `/api/discovery/preview` | 只搜索和评分，不写入 DB、不下载 |
| `POST` | `/api/discovery/run` | 后台触发一次发现 + 下载 |
| `POST` | `/api/downloads` | 后台下载指定 URL |

`GET /api/videos` 查询参数：

| 参数 | 说明 |
| --- | --- |
| `category` | 分类过滤 |
| `status` | 状态过滤，推荐使用 |
| `download_status` | 旧参数，兼容别名 |
| `min_score` | 最低 score |
| `limit` | 分页大小，最多 500 |
| `offset` | 分页偏移 |

文件下载能力：

- 支持 `Range: bytes=start-end`。
- 返回 `Accept-Ranges: bytes`。
- Linux 上优先使用 `os.sendfile()`，失败后回退到 1 MiB chunk 读取。

### 4.7 磁盘清理

清理入口：

```text
app/disk_cleaner.py::cleanup_if_needed()
```

触发时机：

- 自动下载每个视频后触发。
- 手动下载成功后触发。

清理规则：

1. 找出超过 `DISK_MAX_RETENTION_DAYS` 的 downloaded 记录。
2. 如果 downloaded 总大小超过 `DISK_MAX_STORAGE_GB`，按 `downloaded_at` 从旧到新清理。
3. 删除磁盘目录或文件。
4. 标记为 `expired`，清空 `file_dir` 和 `file_size`。

## 5. 数据库概览

SQLite 默认路径：

```text
runtime/discovery/discovery.db
```

当前唯一核心表：

```text
videos
```

字段：

| 字段 | 说明 |
| --- | --- |
| `video_id` | 主键 |
| `discovered_at` | 入库/刷新时间 |
| `url` | YouTube URL |
| `title` | 标题 |
| `channel_title` | 频道名 |
| `published_at` | 发布时间 |
| `duration_sec` | 时长 |
| `view_count` | 播放量 |
| `keyword` | 命中关键词 |
| `category` | 分类 |
| `score` | 热度分 |
| `status` | 唯一视频状态字段 |
| `raw_json` | 原始搜索 JSON |
| `file_dir` | 下载目录 |
| `file_size` | 下载目录总大小 |
| `downloaded_at` | 下载完成或失败时间 |
| `error` | 下载失败原因 |

下载状态流转：

```text
pending -> downloading -> downloaded
pending -> downloading -> failed
downloaded -> pulled
downloaded -> expired
```

手动下载失败已在当前代码中调用 `mark_download_failed()` 落库。

## 6. 配置概览

核心配置在 `app/settings.py`，从 `.env` 读取。

### 6.1 下载配置

| 配置 | 默认值 | 说明 |
| --- | --- | --- |
| `COOKIE_FILE` | 空 | yt-dlp cookie 文件 |
| `YTDLP_PROXY` | 空 | 代理，例如 socks5 |
| `PLAYLIST_STRATEGY` | `first` | 当前只支持 `first` |
| `YTDLP_VIDEO_FORMAT` | `bestvideo[ext=mp4][vcodec^=avc1]` | 视频流选择器 |
| `YTDLP_AUDIO_FORMAT` | `bestaudio[ext=m4a]` | 音频流选择器 |
| `DOWNLOAD_MEDIA_DIR` | `runtime/downloads` | 下载目录 |
| `DOWNLOAD_INTERVAL_SEC` | `180` | 自动下载间隔 |
| `PULL_LOCK_TTL_MINUTES` | `120` | 本地端拉取锁有效期 |

### 6.2 发现配置

| 配置 | 默认值 | 说明 |
| --- | --- | --- |
| `DISCOVERY_PROVIDER` | `ytdlp` | 搜索 provider；当前可用 `ytdlp`，`youtube_api` 为预留入口 |
| `DISCOVERY_TOPIC_TYPES` | `pets,beauty,funny` | 启用分类 |
| `DISCOVERY_MAX_RESULTS_PER_KEYWORD` | `15` | 每个关键词搜索数量，最多 50 |
| `DISCOVERY_TOP_N` | `5` | 每轮保留候选数量 |
| `DISCOVERY_MIN_VIEWS` | `10000` | 最低播放量 |
| `DISCOVERY_MIN_DURATION_SEC` | `60` | 最短时长 |
| `DISCOVERY_MAX_DURATION_SEC` | `1800` | 最长时长 |
| `DISCOVERY_CHANNEL_ALLOWLIST` | 空 | 频道白名单，逗号分隔，空值不限制 |
| `DISCOVERY_CHANNEL_BLOCKLIST` | 空 | 频道黑名单，逗号分隔 |
| `DISCOVERY_TITLE_BLOCKLIST` | 空 | 标题关键词黑名单，逗号分隔 |
| `DISCOVERY_DOWNLOAD_MIN_SCORE` | `5.0` | 自动下载最低分 |
| `DISCOVERY_INTERVAL_MINUTES` | `1440` | 定时发现间隔 |

阶段 3 新增：

| 配置 | 默认值 | 说明 |
| --- | --- | --- |
| `DISCOVERY_CACHE_PATH` | `runtime/discovery/candidates_cache.json` | 候选缓存路径 |
| `DISCOVERY_CACHE_TTL_SEC` | `86400` | 候选缓存 TTL |

### 6.3 API 和存储配置

| 配置 | 默认值 | 说明 |
| --- | --- | --- |
| `DISCOVERY_DB_PATH` | `runtime/discovery/discovery.db` | SQLite 路径 |
| `DISK_MAX_STORAGE_GB` | `50.0` | downloaded 总大小上限 |
| `DISK_MAX_RETENTION_DAYS` | `7` | 最大保留天数 |
| `DISK_MIN_FREE_GB` | `2.0` | 下载前要求的最小磁盘剩余空间 |
| `API_TOKEN` | 空 | Bearer token，空则无认证 |
| `API_HOST` | `0.0.0.0` | 监听地址 |
| `API_PORT` | `8503` | 监听端口 |
| `LOG_LEVEL` | `INFO` | 日志等级 |
| `LOG_FILE` | `runtime/logs/hk-server.log` | 日志文件 |

## 7. 当前已有功能清单

### 已具备

- 独立安装和启动。
- 标准库 HTTP API。
- Bearer Token 认证。
- 分类关键词配置。
- yt-dlp 搜索候选。
- 播放量、时长过滤。
- 热度评分和 TopN。
- 候选缓存，路径、TTL 和关键词匹配由配置控制。
- SQLite 去重和状态记录。
- 自动下载 pending 高分视频。
- 下载视频流 `.mp4`。
- 下载音频流 `.m4a`。
- 下载最佳封面。
- 保存 `.video_info.json`。
- 文件流式下载。
- HTTP Range 断点续传支持。
- 本地拉取后删除远程文件。
- 手动触发发现下载。
- 手动提交 URL 下载。
- 按时间和容量清理磁盘。
- 基础统计接口。
- 统一 JSON 响应 envelope。
- 健康检查 `/api/health`。
- 持久化任务记录 `/api/tasks` 和任务事件 `task_events`。
- 任务取消和重试 API。
- 视频级事件 `video_events`。
- 拉取确认和管理员强制删除分离。
- 离线 pytest 覆盖 repository、scoring、disk_cleaner、API helper 和 task_state。
- 部署后 smoke、systemd 示例和日志轮转建议文档。

### 部分具备但需要校正

- 手动下载后台编排已抽到 service 层；当前已支持任务持久记录、列表、详情、取消、重试、视频事件、下载实时进度和启动时中断任务恢复。
- yt-dlp 搜索 provider 仍只有一个，搜索质量和字段完整度有限。

### 当前不具备

- 搜索任务队列。
- 下载任务队列。
- 任务取消、暂停、重试接口。
- 下载进度查询。
- API 级错误码规范。
- OpenAPI 文档。
- 结构化日志。
- Range 多段请求支持。
- 频道黑名单/白名单。
- 视频去重策略之外的内容相似去重。
- 合并后视频产物。
- 发布状态回调。
- 本地端拉取确认的两阶段确认机制。

## 8. 第一版重构时应重点处理的问题

这些不是兼容性问题，可以直接删改：

1. 明确 `hk-server` 是唯一远程中转服务，删除或隔离与 `youtobe-parser` 重叠的旧思路。
2. 删除无效配置或让配置生效，例如 `DISCOVERY_ENABLED`、`DISCOVERY_DAYS_BACK`、语言过滤。
3. 重构发现层，明确只走 yt-dlp，或者引入 YouTube Data API 作为可选 provider；不要保留半兼容签名。
4. 给自动发现、手动触发、手动 URL 下载加全局任务锁或任务表，避免并发写同一视频目录。
5. 手动下载失败必须写入 `failed` 状态。
6. 缓存路径应从配置派生，或去掉缓存改为明确的任务表。
7. DB 字段已统一为 `videos.status`，后续可继续收敛 API 兼容别名。
8. 不可靠的 `language_hint`、`comment_count`、`like_count` 字段及相关配置已删除。
9. 缓存路径和 TTL 已改为 `DISCOVERY_CACHE_PATH` / `DISCOVERY_CACHE_TTL_SEC`。
10. `GET /api/videos` 推荐 `status` 查询；如代码保留旧参数，则 `download_status` 只作为兼容别名。

## 9. 建议的第一版边界

为了保持远程服务简单，建议 `hk-server` 第一版只保留这些边界：

```text
远程只做：
  1. 搜索候选
  2. 下载原始 video/audio/thumbnail/meta
  3. 存储状态
  4. 提供可断点续传 API
  5. 清理磁盘

远程不做：
  1. 合并
  2. 转码
  3. 翻译
  4. 配音
  5. 发布
  6. 平台账号管理
```

这样本地端可以稳定地把它当作“素材中转仓库”，后续优化优先围绕搜索质量、下载稳定性、API 契约和状态机展开。

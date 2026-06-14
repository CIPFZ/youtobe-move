# youtobe-move 项目梳理

本文档基于当前仓库代码梳理，说明系统结构、数据流、关键模块、运行方式和当前需要注意的实现差异。

## 1. 项目定位

`youtobe-move` 是一个 YouTube 视频搬运流水线 monorepo，核心目标是：

1. 在远程香港服务器发现、筛选、下载 YouTube 视频。
2. 通过 HTTP API 暴露已下载视频、音频、封面和元数据。
3. 本地服务定时从香港服务器拉取素材，合并音视频。
4. 本地侧调用 B 站上传能力完成发布，同时保留抖音、小红书、快手、视频号等多平台上传入口。

当前仓库里存在三个主要目录：

| 目录 | 角色 | 说明 |
| --- | --- | --- |
| `youtobe-parser/` | HK 端主服务 | 当前功能最完整，包含发现、下载、API、转写、翻译、字幕/配音处理 |
| `hk-server/` | HK 端轻量服务 | 另一个 HK 服务实现，偏向 yt-dlp 搜索和双流下载，已有独立设计文档 |
| `social-auto-upload/` | 本地发布端 | 拉取 HK 视频、ffmpeg 合并、B 站发布、多平台自动化上传、Flask/Vue 管理界面 |

## 2. 端到端数据流

```text
YouTube
  |
  | YouTube Data API v3 / yt-dlp
  v
youtobe-parser 或 hk-server（香港服务器）
  |
  | 发现候选 -> 评分排序 -> SQLite 去重 -> yt-dlp 下载
  | 存储 video/audio/thumbnail/meta -> HTTP API :8503
  v
social-auto-upload（本地服务器）
  |
  | 定时 GET /api/videos?download_status=downloaded
  | 下载 video/audio/thumbnail/meta -> ffmpeg 合并
  | DELETE /api/videos/<id> 清理 HK 端文件
  v
Bilibili / 抖音 / 小红书 / 快手 / 视频号
```

本地自动发布到 B 站的实际链路在 `social-auto-upload/hk_puller.py`：

```text
sync_hk_videos()
  -> fetch_hk_videos()
  -> download_hk_file(video)
  -> download_hk_file(audio)
  -> download_hk_file(thumbnail)
  -> download_hk_meta()
  -> merge_video_audio()
  -> delete_hk_video()

publish_pending()
  -> 读取本地 hk_videos 待发布记录
  -> 生成中文标题/简介/标签
  -> upload_to_bilibili()
  -> 调用 biliup CLI
  -> 标记 upload_status
  -> 清理本地视频文件
```

## 3. HK 端：`youtobe-parser`

### 3.1 职责

`youtobe-parser` 是当前更完整的远程端实现，职责包括：

- 使用 YouTube Data API v3 按关键词发现候选视频。
- 按播放量、评论数、发布时间、时长、语言等条件过滤并评分。
- 将候选写入 SQLite `discovered_videos`。
- 使用 `yt-dlp` 下载独立视频流 `.mp4`、音频流 `.m4a` 和封面。
- 通过标准库 `ThreadingHTTPServer` 暴露 API，默认端口 `8503`。
- 下载后可继续执行转写、翻译、字幕合成、中文配音等后处理。
- 按容量和保留天数滚动清理磁盘。

### 3.2 关键入口

| 命令 | 入口 | 作用 |
| --- | --- | --- |
| `yp-run <url>` | `main:main` | 单视频下载、转写、翻译、合成流程 |
| `yp-dub` | `dub_main:main` | 独立配音流程 |
| `yp-scheduler` | `app.scheduler:run_scheduler` | 单次发现、下载、清理、可选后处理 |
| `yp-server` | `app.scheduler:run_server` | API 服务 + 发现定时器 + 后处理轮询器 |

`yp-server` 启动后：

1. 调用 `run_api_server()` 启动 HTTP API。
2. 后台线程按 `DISCOVERY_INTERVAL_MINUTES` 调用 `run_discovery_and_download()`。
3. 若 `PROCESS_ENABLED=True`，后台线程按 `PROCESS_POLL_INTERVAL_SEC` 调用 `run_process_pipeline()`。

### 3.3 发现模块

主要文件：

| 文件 | 作用 |
| --- | --- |
| `app/discovery/service.py` | 读取 topic 配置，组织关键词和语言限制 |
| `app/discovery/youtube_discovery.py` | 调用 YouTube Data API `search` 和 `videos` |
| `app/discovery/scoring.py` | 候选过滤、热度评分、去重排序 |
| `app/discovery/repository.py` | SQLite 建表、迁移、查询和状态更新 |

当前 `TOPIC_REGISTRY` 支持 6 类：

| 分类 | 默认语言限制 | 默认关键词示例 |
| --- | --- | --- |
| `ai` | `en` | AI, OpenAI, Anthropic, Google DeepMind |
| `tech` | `en` | technology, tech news, software engineering |
| `digital` | `en` | gadgets, consumer tech, smartphone review |
| `pets` | 不限 | funny cats, cute dogs, pet videos |
| `beauty` | 不限 | makeup tutorial, skincare routine |
| `funny` | 不限 | funny videos, comedy clips, pranks |

候选过滤条件来自 `.env`：

- `DISCOVERY_MIN_VIEWS`
- `DISCOVERY_MIN_COMMENTS`
- `DISCOVERY_MIN_DURATION_SEC`
- `DISCOVERY_MAX_DURATION_SEC`
- `DISCOVERY_TOPIC_{TYPE}_LANGUAGES`

评分逻辑在 `compute_hot_score()`：

```text
score = log10(view_count) + 1.3 * log10(comment_count) + freshness
freshness = 24 / age_hours
```

### 3.4 下载和清理

主编排函数：`app/download_service.py::run_discovery_and_download()`

流程：

1. 调用 `run_discovery_once()` 发现候选。
2. `upsert_candidates()` 写入 SQLite。
3. 查询 `download_status='pending'` 且 `score >= DISCOVERY_DOWNLOAD_MIN_SCORE` 的记录。
4. 每条视频下载到：

```text
runtime/downloads/{category}/{video_id}/
```

5. `download_media()` 分别下载：

```text
{video_id}.mp4
{video_id}.m4a
{video_id}.thumbnail.{jpg|png|webp}
```

6. 成功后标记 `download_status='downloaded'`。
7. 每次下载后调用 `cleanup_if_needed()`，按 `DISK_MAX_STORAGE_GB` 和 `DISK_MAX_RETENTION_DAYS` 清理最旧文件。

### 3.5 下载后处理

后处理入口：`app/process_service.py`

处理条件：

```sql
download_status = 'downloaded'
AND (
  process_status = 'pending'
  OR (process_status = 'failed' AND process_retries < PROCESS_MAX_RETRIES)
)
```

处理流程由 `app/pipeline.py::Pipeline` 负责，目标是：

```text
video + audio
  -> fast-whisper 转写
  -> LLM 翻译
  -> 双语字幕视频
  -> 可选中文配音视频
```

处理结果写回 `discovered_videos`：

- `process_status`
- `process_retries`
- `process_error`
- `bilingual_video`
- `dubbed_video`

### 3.6 HTTP API

实现文件：`youtobe-parser/app/api.py`

认证：

```text
Authorization: Bearer <API_TOKEN>
```

如果 `API_TOKEN` 为空，则不校验认证。

当前实现的端点：

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| `GET` | `/api/videos` | 查询视频列表 |
| `GET` | `/api/videos/<id>` | 查询单条视频详情 |
| `GET` | `/api/videos/<id>/file?type=video` | 下载 `.mp4` 视频流 |
| `GET` | `/api/videos/<id>/file?type=audio` | 下载 `.m4a` 音频流 |
| `GET` | `/api/videos/<id>/file?type=thumbnail` | 下载封面 |
| `DELETE` | `/api/videos/<id>` | 删除磁盘文件并标记 `cleaned` |
| `POST` | `/api/trigger-discovery` | 后台触发发现和下载 |
| `GET` | `/api/stats` | 存储统计 |

`GET /api/videos` 支持查询参数：

| 参数 | 说明 |
| --- | --- |
| `category` | 按分类过滤 |
| `download_status` | 按下载状态过滤 |
| `min_score` | 最低评分 |
| `limit` | 分页大小，最多 500 |
| `offset` | 分页偏移 |

注意：`social-auto-upload/hk_puller.py` 当前会调用 `/api/videos/<id>/meta`，但 `youtobe-parser/app/api.py` 暂未实现该端点。

### 3.7 远程端数据库

SQLite 默认路径：

```text
runtime/discovery/discovery.db
```

核心表：`discovered_videos`

| 字段 | 说明 |
| --- | --- |
| `video_id` | YouTube 视频 ID，主键 |
| `url` / `title` / `description` | 原始视频信息 |
| `channel_id` / `channel_title` | 频道信息 |
| `published_at` / `discovered_at` | 发布时间和发现时间 |
| `language_hint` | YouTube 语言提示 |
| `duration_sec` | 视频时长 |
| `view_count` / `comment_count` / `like_count` | 热度指标 |
| `keyword` / `category` | 命中的关键词和分类 |
| `score` | 热度评分 |
| `download_status` | `pending/downloading/downloaded/failed/cleaned` |
| `file_path` / `file_size` | 下载目录和大小 |
| `downloaded_at` / `download_error` | 下载时间和失败原因 |
| `process_status` | `pending/processing/processed/failed` |
| `bilingual_video` / `dubbed_video` | 后处理产物 |

另有 `processing_jobs` 表保留兼容用途。

## 4. HK 端：`hk-server`

仓库还存在独立目录 `hk-server/`，它和 `youtobe-parser` 的发现下载服务职责相近，但实现侧重点不同：

| 维度 | `youtobe-parser` | `hk-server` |
| --- | --- | --- |
| 发现方式 | YouTube Data API v3 | 设计文档描述为 yt-dlp 搜索 |
| 默认 topic | `ai,tech,digital` | `pets,beauty,funny` |
| 后处理 | 有转写、翻译、字幕、配音 | 无后处理 |
| 包名/命令 | `youtobe-parser`, `yp-server` | `hk-server`, `hk-server` |
| 设计文档 | 本文档 | `docs/hk-server-design.md` |

如果后续要简化部署，建议明确一个 HK 端主线：

- 需要转写/翻译/配音：以 `youtobe-parser` 为主。
- 只需要发现/下载/API：可以考虑以 `hk-server` 为主，或把缺失能力合并回 `youtobe-parser`。

## 5. 本地端：`social-auto-upload`

### 5.1 职责

本地端负责：

- 定时从 HK API 拉取已下载视频列表。
- 下载远程视频流、音频流、封面、元数据。
- 使用 ffmpeg 合并音视频，必要时将 AV1/VP9/VP8 转 H.264。
- 将本地素材写入 SQLite `hk_videos`。
- 调用 `biliup` 上传 B 站。
- 提供 Flask API 和 Vue 前端管理上传、账号、素材和 HK 拉取记录。
- 保留抖音、小红书、快手、视频号等平台自动化上传入口。

### 5.2 HK 拉取模块

核心文件：`social-auto-upload/hk_puller.py`

关键函数：

| 函数 | 作用 |
| --- | --- |
| `fetch_hk_videos()` | 请求 HK `/api/videos?download_status=downloaded` |
| `download_hk_file()` | 下载 `video/audio/thumbnail`，支持 Range 续传头 |
| `download_hk_meta()` | 请求 HK `/api/videos/<id>/meta` |
| `merge_video_audio()` | ffmpeg 合并双流，必要时 GPU 转码 H.264 |
| `delete_hk_video()` | 本地拉取成功后请求 HK 删除远程文件 |
| `sync_hk_videos()` | 完整同步流程 |
| `publish_pending()` | 发布本地待发布视频到 B 站 |
| `run_hk_poller()` | 后台定时同步线程 |

下载目录：

```text
social-auto-upload/videoFile/{HK_DOWNLOAD_DIRNAME}/{category}/{video_id}/
```

合并产物：

```text
{video_id}_merged.mp4
```

发布完成后，`publish_pending()` 会删除本地合并文件所在目录以节省空间。

### 5.3 B 站发布

B 站发布依赖 `biliup` 运行时：

```text
uploader/bilibili_uploader/runtime.py
```

自动发布入口：

```text
hk_puller.py::publish_pending()
  -> upload_to_bilibili()
  -> run_biliup_command()
```

CLI 手动发布入口：

```bash
sau bilibili login --account <name>
sau bilibili check --account <name>
sau bilibili upload-video \
  --account <name> \
  --file <video.mp4> \
  --title <title> \
  --desc <description> \
  --tid <bilibili_tid> \
  --tags tag1,tag2
```

B 站分区映射在 `hk_puller.py`：

| YouTube 分类 | B 站 tid | 说明 |
| --- | ---: | --- |
| `pets` | `217` | 动物圈 |
| `beauty` | `163` | 时尚 |
| `funny` | `138` | 搞笑 |
| 默认 | `174` | 生活 |

注意：当前只映射了 `pets/beauty/funny`。如果 HK 端启用 `ai/tech/digital`，需要补 B 站分区映射和标签策略。

### 5.4 Flask 路由

主文件：`social-auto-upload/sau_backend.py`

服务端口：

```text
0.0.0.0:5409
```

HK 相关路由：

| 方法 | 路由 | 说明 |
| --- | --- | --- |
| `GET` | `/hk/videos` | 查询本地已同步 HK 视频 |
| `POST` | `/hk/sync` | 后台触发一次 HK 同步 |
| `GET` | `/hk/stats` | 查询本地同步统计 |
| `GET` | `/hk/file/<video_id>` | 返回本地已下载视频文件 |
| `POST` | `/hk/publish` | 后台触发 B 站发布 |
| `POST` | `/hk/upload-status` | 手动标记上传状态 |

原有通用路由包括：

| 路由 | 说明 |
| --- | --- |
| `/upload` / `/uploadSave` | 上传本地视频素材 |
| `/getFiles` / `/getFile` / `/deleteFile` | 素材列表、读取、删除 |
| `/getAccounts` / `/getValidAccounts` / `/deleteAccount` | 平台账号管理 |
| `/login` | SSE 登录流程 |
| `/postVideo` | 调用多平台发布 |

注意：`/hk/file/<video_id>` 当前把 `file_path` 当目录处理并查找 `{video_id}.*`，但 `hk_puller._mark_downloaded()` 写入的是合并后的文件路径 `{video_id}_merged.mp4`。这会导致该路由可能找不到文件，需要后续修正为兼容文件路径和目录路径。

### 5.5 本地数据库

SQLite 路径：

```text
social-auto-upload/db/database.db
```

建表脚本：

```bash
cd social-auto-upload
python db/createTable.py
```

核心表：

| 表 | 说明 |
| --- | --- |
| `user_info` | 多平台账号和 cookie 文件记录 |
| `file_records` | 手动上传素材记录 |
| `hk_videos` | 从 HK 同步的视频状态 |
| `hk_sync_log` | 每次同步日志 |

`hk_videos` 关键字段：

| 字段 | 说明 |
| --- | --- |
| `video_id` | YouTube 视频 ID，唯一 |
| `title` / `url` / `category` | 视频基础信息 |
| `view_count` / `score` | 热度指标 |
| `download_status` | 本地下载状态 |
| `file_path` / `file_size` | 本地合并视频路径和大小 |
| `thumbnail_path` / `meta_path` | 封面和元数据路径 |
| `upload_status` | B 站或其他平台上传状态 |
| `uploaded_at` / `upload_platform` / `upload_account` | 上传记录 |
| `error` | 最近一次错误 |

## 6. 配置汇总

### 6.1 `youtobe-parser/.env`

| 配置 | 说明 |
| --- | --- |
| `YOUTUBE_API_KEY` | YouTube Data API Key |
| `DISCOVERY_TOPIC_TYPES` | 启用分类，逗号分隔 |
| `DISCOVERY_TOPIC_{X}_KEYWORDS` | 分类关键词 |
| `DISCOVERY_TOPIC_{X}_LANGUAGES` | 分类语言白名单，空值表示不限 |
| `DISCOVERY_DAYS_BACK` | 搜索最近 N 天 |
| `DISCOVERY_TOP_N` | 每轮保留候选数量 |
| `DISCOVERY_DOWNLOAD_MIN_SCORE` | 自动下载最低评分 |
| `DOWNLOAD_MEDIA_DIR` | 下载目录 |
| `DISK_MAX_STORAGE_GB` | 磁盘容量阈值 |
| `DISK_MAX_RETENTION_DAYS` | 文件保留天数 |
| `API_HOST` / `API_PORT` | HK API 监听地址 |
| `API_TOKEN` | API Bearer Token |
| `PROCESS_ENABLED` | 是否启用下载后处理 |
| `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `OPENAI_MODEL` | 翻译和处理用 LLM 配置 |
| `TTS_PROVIDER` / `TTS_OPENAI_MODEL` / `TTS_EDGE_VOICE` | 配音配置 |

### 6.2 `social-auto-upload/conf.py`

由 `conf.example.py` 复制生成。

| 配置 | 说明 |
| --- | --- |
| `HK_SERVER_URL` | HK API 地址 |
| `HK_API_TOKEN` | HK API Bearer Token |
| `HK_POLL_INTERVAL_MINUTES` | 本地同步轮询间隔 |
| `HK_AUTO_DOWNLOAD` | 是否自动下载新视频 |
| `HK_DOWNLOAD_DIRNAME` | `videoFile/` 下的 HK 下载目录名 |
| `HK_DOWNLOAD_INTERVAL_SEC` | 每个视频下载之间的间隔 |
| `LOCAL_CHROME_PATH` | Playwright 可选本地 Chrome 路径 |
| `LOCAL_CHROME_HEADLESS` | 浏览器自动化是否 headless |

## 7. 启动流程

### 7.1 HK 端：`youtobe-parser`

```bash
cd youtobe-parser
python -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
# 编辑 .env，至少配置 YOUTUBE_API_KEY
yp-server
```

单次执行：

```bash
cd youtobe-parser
source .venv/bin/activate
yp-scheduler
```

### 7.2 本地端：`social-auto-upload`

```bash
cd social-auto-upload
pip install -r requirements.txt
playwright install chromium
cp conf.example.py conf.py
python db/createTable.py
python3 sau_backend.py
```

B 站账号登录：

```bash
cd social-auto-upload
sau bilibili login --account default
```

## 8. 当前实现差异和风险点

1. `youtobe-parser` 和 `hk-server` 两套 HK 端实现并存，部署前需要明确主线。
2. `docs/hk-server-design.md` 描述的是 `hk-server`，不是 `youtobe-parser`；其中部分接口和实现与 `youtobe-parser` 不一致。
3. 本地 `hk_puller.download_hk_meta()` 调用 `/api/videos/<id>/meta`，但 `youtobe-parser/app/api.py` 当前未实现该端点。
4. 本地 `/hk/file/<video_id>` 路由把 `hk_videos.file_path` 当目录使用，但同步时写入的是合并文件路径，可能导致取文件失败。
5. `hk_puller.download_hk_file()` 带了 `Range` 续传头，但 `youtobe-parser` API 的 `_stream_file()` 当前不处理 Range，断点续传不会真正生效。
6. B 站分类映射目前只覆盖 `pets/beauty/funny`，而 `youtobe-parser` 默认启用 `ai/tech/digital`，需要统一业务分类。
7. HK API 的删除语义是拉取后 `DELETE /api/videos/<id>` 即删除远程磁盘文件并标记 `cleaned`，如果本地发布失败，远程端已无法重新拉取同一份文件。
8. `process_status='processed'` 的双语/配音产物目前没有通过 HK API 暴露给本地端，本地端拉取的仍是原始下载双流并自行合并。

## 9. 建议后续整理方向

1. 确认远程端只保留一个主实现，减少 `hk-server` 与 `youtobe-parser` 的重复维护。
2. 补齐或移除 `/api/videos/<id>/meta` 约定，使 HK API 与本地拉取模块一致。
3. 修正 `/hk/file/<video_id>` 的本地文件路径处理。
4. 为 `ai/tech/digital` 增加 B 站分区、标签和中文标题生成策略。
5. 明确本地拉取的是原始合并视频、双语字幕视频还是配音后视频，并据此调整 API 字段。
6. 如果需要断点续传，在 HK API `_stream_file()` 中实现 HTTP Range。

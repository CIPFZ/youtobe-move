# hk-server 优化实施方案

本文档面向 `hk-server/` 的第一版重构。当前原则是：不考虑历史迁移兼容；如果字段、接口、模块设计不合理，可以直接删除、重建或重命名。

## 1. 优化目标

`hk-server` 应定位为远程香港服务器上的稳定素材中转服务，只负责：

1. 搜索 YouTube 候选视频。
2. 下载原始视频流、音频流、封面和元数据。
3. 记录视频和任务状态。
4. 通过 HTTP API 提供列表、详情、文件下载和拉取确认。
5. 控制磁盘占用并清理过期素材。

第一版不在 `hk-server` 做：

- 音视频合并。
- 转码。
- 字幕、翻译、配音。
- B 站或其他平台发布。
- 平台账号管理。
- 前端页面。

后续 V2、V3 以及更长期版本的演进设计见：

```text
docs/hk-server/version-roadmap.md
```

## 2. 当前代码问题摘要

基于当前代码梳理，主要问题如下。

| 编号 | 问题 | 影响 | 涉及文件 |
| --- | --- | --- | --- |
| P1 | 定时发现、手动触发、手动 URL 下载没有统一任务锁 | 可能并发下载、并发清理、状态互相覆盖 | `app/api.py`, `app/scheduler.py`, `app/download_service.py` |
| P2 | `/api/download` 后台失败只写日志，不落库 | 视频可能长期卡在 `downloading` | `app/api.py` |
| P3 | `cleaned` 同时表达磁盘清理和本地已拉取删除 | 状态语义混乱，后续排查困难 | `app/api.py`, `app/disk_cleaner.py`, `app/discovery/repository.py` |
| P4 | `DISCOVERY_ENABLED` 配置未生效 | 配置误导，服务启动后仍会定时发现 | `app/settings.py`, `app/scheduler.py` |
| P5 | `DISCOVERY_DAYS_BACK` 基本未生效 | 配置误导，无法按发布时间过滤 | `app/discovery/youtube_discovery.py` |
| P6 | 语言、评论、点赞字段不可靠 | 评分和过滤逻辑有假有效字段 | `app/discovery/scoring.py`, `app/discovery/youtube_discovery.py`, `app/discovery/models.py` |
| P7 | 发现缓存路径写死 | 改 DB 或运行目录时缓存不可控 | `app/download_service.py` |
| P8 | API 响应格式不统一 | 本地端集成和错误处理复杂 | `app/api.py` |
| P9 | 缺少健康检查和任务状态接口 | 本地端无法可靠判断远程服务是否可用 | `app/api.py` |
| P10 | DB 表结构带有兼容迁移思路 | 第一版不需要保留复杂迁移和无效字段 | `app/discovery/repository.py` |
| P11 | 搜索 provider 代码保留 `api_key` 兼容参数 | 代码语义混乱，实际只支持 yt-dlp | `app/discovery/service.py`, `app/discovery/youtube_discovery.py` |
| P12 | 删除远程文件接口语义是 `DELETE`，但业务语义是“本地确认拉取” | 容易误删，接口意图不明确 | `app/api.py` |

## 3. 实施优先级

建议分 5 个阶段实施。

```text
阶段 1：稳定状态机和并发
阶段 2：明确 API 契约和健康检查
阶段 3：简化 DB 与配置
阶段 4：重构搜索和评分
阶段 5：补测试与运行文档
```

执行顺序不要跳过阶段 1。当前最容易导致生产事故的是并发任务和状态不落库。

## 4. 阶段 1：稳定状态机和并发

### 4.1 目标

- 任意时刻最多只有一个 discovery/download 主任务运行。
- 手动 URL 下载失败必须落库。
- 下载状态语义清楚。
- 自动磁盘清理和本地拉取确认状态分开。

### 4.2 建议状态设计

第一版可以重建表，不需要迁移旧状态。

视频下载状态：

```text
pending       已发现，等待下载
downloading   正在下载
downloaded    下载完成，可供本地拉取
pulled        本地已确认拉取，远程文件已删除
expired       因保留期或容量清理，远程文件已删除
failed        下载失败
```

说明：

- `pulled`：由本地端确认拉取后触发。
- `expired`：由磁盘清理触发。
- 删除 `cleaned`，避免语义混合。

### 4.3 代码改动点

| 文件 | 改动 |
| --- | --- |
| `app/discovery/repository.py` | 删除 `mark_cleaned()`，新增 `mark_pulled()`、`mark_expired()`、`reset_failed_to_pending()` 可选 |
| `app/disk_cleaner.py` | 清理后调用 `mark_expired()` |
| `app/api.py` | 拉取确认接口调用 `mark_pulled()` |
| `app/download_service.py` | 增加全局任务锁，避免重复运行 |
| `app/api.py` | `/api/trigger-discovery` 如果已有任务运行，返回明确状态 |
| `app/api.py` | `/api/download` 失败时调用 `mark_download_failed()` |

### 4.4 任务锁方案

第一版先用进程内锁，简单可靠：

```python
_discovery_lock = threading.Lock()
_manual_download_lock = threading.Lock()
```

建议进一步抽象为 `app/task_state.py`：

```text
app/task_state.py
  - try_start_task(name)
  - finish_task(name, summary=None, error='')
  - get_task_state()
```

第一版可只记录内存状态：

- `running`
- `task_name`
- `started_at`
- `last_finished_at`
- `last_summary`
- `last_error`

### 4.5 验收标准

- 连续调用两次 `/api/trigger-discovery`，第二次应返回“已有任务运行”，不会启动第二个后台线程。
- `/api/download` 下载失败后，DB 记录为 `failed`，`download_error` 有错误信息。
- 磁盘自动清理后状态为 `expired`。
- 本地确认拉取后状态为 `pulled`。
- `GET /api/videos?download_status=downloaded` 不返回 `pulled` 或 `expired` 记录。

## 5. 阶段 2：明确 API 契约和健康检查

### 5.1 目标

- API 响应结构统一。
- 本地端可以探测 HK 服务可用性。
- 拉取确认语义清楚。
- 保留当前本地端需要的文件下载能力。

### 5.2 API 响应格式

建议统一成功响应：

```json
{
  "ok": true,
  "data": {}
}
```

分页响应：

```json
{
  "ok": true,
  "data": {
    "items": [],
    "total": 0,
    "limit": 50,
    "offset": 0
  }
}
```

错误响应：

```json
{
  "ok": false,
  "error": {
    "code": "not_found",
    "message": "Video not found"
  }
}
```

第一版不考虑兼容，可以直接替换旧响应格式。

### 5.3 API 路由建议

保留：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/health` | 健康检查 |
| `GET` | `/api/tasks` | 当前和最近任务状态 |
| `GET` | `/api/videos` | 视频列表 |
| `GET` | `/api/videos/<id>` | 视频详情 |
| `GET` | `/api/videos/<id>/meta` | 元数据 JSON |
| `GET` | `/api/videos/<id>/file?type=video|audio|thumbnail` | 文件下载 |
| `POST` | `/api/discovery/run` | 手动触发发现下载 |
| `POST` | `/api/downloads` | 手动提交 URL 下载 |
| `POST` | `/api/videos/<id>/confirm-pulled` | 本地确认拉取并删除远程文件 |
| `DELETE` | `/api/videos/<id>/files` | 管理员强制删除远程文件 |
| `GET` | `/api/stats` | 统计 |

建议删除或替换：

| 旧接口 | 处理 |
| --- | --- |
| `POST /api/trigger-discovery` | 替换为 `POST /api/discovery/run` |
| `POST /api/download` | 替换为 `POST /api/downloads` |
| `DELETE /api/videos/<id>` | 替换为 `POST /api/videos/<id>/confirm-pulled` 或管理员删除接口 |

### 5.4 `/api/health`

返回建议：

```json
{
  "ok": true,
  "data": {
    "service": "hk-server",
    "db_ok": true,
    "download_dir_ok": true,
    "disk_free_gb": 123.4,
    "api_auth_enabled": true
  }
}
```

### 5.5 `/api/tasks`

返回建议：

```json
{
  "ok": true,
  "data": {
    "running": false,
    "task_name": "",
    "started_at": "",
    "last_finished_at": "2026-06-14T00:00:00+00:00",
    "last_summary": {},
    "last_error": ""
  }
}
```

### 5.6 验收标准

- 所有 JSON API 成功/失败格式一致。
- 本地端可通过 `/api/health` 判断服务是否可用。
- 本地端拉取完成后调用 `/api/videos/<id>/confirm-pulled`，远程文件删除且状态为 `pulled`。
- 强制删除和拉取确认语义分开。

## 6. 阶段 3：简化 DB 与配置

当前状态：已实施。`hk-server/app/discovery/repository.py` 已重建为 `videos` 表，内部状态字段统一为 `status`；`VideoCandidate`、DB 和评分逻辑已删除 `language_hint`、`comment_count`、`like_count` 等不可靠字段；发现缓存已改为 `DISCOVERY_CACHE_PATH` / `DISCOVERY_CACHE_TTL_SEC` 配置。

### 6.1 目标

- 删除第一版中无效或误导字段。
- 删除无效配置，或让配置真正生效。
- DB 表结构表达真实业务。
- 统一视频状态字段为 `status`，API 推荐使用 `status` 查询，同时在过渡期保留旧
  `download_status` 查询参数兼容本地端。
- 发现缓存路径和 TTL 配置化，避免运行目录或 DB 路径变化时缓存不可控。

### 6.2 建议 DB 表

重建 `videos` 表替代 `discovered_videos`：

```sql
CREATE TABLE videos (
  video_id TEXT PRIMARY KEY,
  url TEXT NOT NULL,
  title TEXT NOT NULL DEFAULT '',
  channel_title TEXT NOT NULL DEFAULT '',
  published_at TEXT NOT NULL DEFAULT '',
  duration_sec INTEGER,
  view_count INTEGER,
  keyword TEXT NOT NULL DEFAULT '',
  category TEXT NOT NULL DEFAULT '',
  score REAL NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'pending',
  file_dir TEXT NOT NULL DEFAULT '',
  file_size INTEGER NOT NULL DEFAULT 0,
  thumbnail_path TEXT NOT NULL DEFAULT '',
  meta_path TEXT NOT NULL DEFAULT '',
  discovered_at TEXT NOT NULL,
  downloaded_at TEXT NOT NULL DEFAULT '',
  pulled_at TEXT NOT NULL DEFAULT '',
  expired_at TEXT NOT NULL DEFAULT '',
  error TEXT NOT NULL DEFAULT '',
  raw_json TEXT NOT NULL DEFAULT '{}'
);
```

状态字段统一命名为 `status`，不再同时存在 `status` 和 `download_status`。

第一版应删除这些字段：

- `channel_id`
- `description`
- `language_hint`
- `comment_count`
- `like_count`

原因：yt-dlp 搜索路径中这些字段为空或不稳定。

下载状态统一写入 `videos.status`：

```text
pending       已发现，等待下载
downloading   正在下载
downloaded    下载完成，可供本地拉取
pulled        本地已确认拉取，远程文件已删除
expired       因保留期或容量清理，远程文件已删除
failed        下载失败
```

API 层查询规则：

- 推荐：`GET /api/videos?status=downloaded`
- 兼容：如果代码支持旧参数，`GET /api/videos?download_status=downloaded` 应映射到同一状态过滤。
- 响应字段应返回 `status`；如需兼容旧本地端，可以短期额外返回 `download_status`，但内部 DB 不再使用它。

### 6.3 建议任务表

如果阶段 1 只做内存任务状态，阶段 3 可以加任务表：

```sql
CREATE TABLE tasks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  type TEXT NOT NULL,
  status TEXT NOT NULL,
  input_json TEXT NOT NULL DEFAULT '{}',
  summary_json TEXT NOT NULL DEFAULT '{}',
  error TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  started_at TEXT NOT NULL DEFAULT '',
  finished_at TEXT NOT NULL DEFAULT ''
);
```

任务状态：

```text
pending -> running -> success
pending -> running -> failed
```

### 6.4 配置整理

建议保留：

| 配置 | 说明 |
| --- | --- |
| `COOKIE_FILE` | yt-dlp cookie |
| `YTDLP_PROXY` | yt-dlp 代理 |
| `YTDLP_VIDEO_FORMAT` | 视频格式选择 |
| `YTDLP_AUDIO_FORMAT` | 音频格式选择 |
| `DISCOVERY_TOPIC_TYPES` | 启用分类 |
| `DISCOVERY_TOPIC_{X}_KEYWORDS` | 分类关键词 |
| `DISCOVERY_MAX_RESULTS_PER_KEYWORD` | 每个关键词搜索数量 |
| `DISCOVERY_TOP_N` | 每轮候选数 |
| `DISCOVERY_MIN_VIEWS` | 最低播放量 |
| `DISCOVERY_MIN_DURATION_SEC` | 最短时长 |
| `DISCOVERY_MAX_DURATION_SEC` | 最长时长 |
| `DISCOVERY_DOWNLOAD_MIN_SCORE` | 自动下载阈值 |
| `DISCOVERY_INTERVAL_MINUTES` | 定时周期 |
| `DISCOVERY_DB_PATH` | DB 路径 |
| `DISCOVERY_CACHE_PATH` | 缓存路径 |
| `DISCOVERY_CACHE_TTL_SEC` | 缓存 TTL |
| `DOWNLOAD_MEDIA_DIR` | 下载目录 |
| `DOWNLOAD_INTERVAL_SEC` | 下载间隔 |
| `DISK_MAX_STORAGE_GB` | 存储上限 |
| `DISK_MAX_RETENTION_DAYS` | 保留天数 |
| `API_TOKEN` | API token |
| `API_HOST` / `API_PORT` | 监听配置 |
| `LOG_LEVEL` / `LOG_FILE` | 日志配置 |

建议删除：

| 配置 | 原因 |
| --- | --- |
| `DISCOVERY_ENABLED` | 如果需要停用，用 `DISCOVERY_INTERVAL_MINUTES=0` 或启动参数控制更清楚 |
| `DISCOVERY_DAYS_BACK` | yt-dlp 搜索无法可靠按日期过滤 |
| `DISCOVERY_MIN_COMMENTS` | yt-dlp 搜索结果没有评论数 |
| `DISCOVERY_TOPIC_{X}_LANGUAGES` | 当前语言字段为空，过滤基本无效 |

如果确实需要语言或日期过滤，应在阶段 4 引入更可靠 provider，而不是保留假配置。

### 6.5 代码改动点

| 文件 | 改动 |
| --- | --- |
| `app/settings.py` | 删除无效配置，新增 cache 配置 |
| `app/discovery/models.py` | 简化模型字段 |
| `app/discovery/repository.py` | 直接重建 DB schema 和 CRUD |
| `app/download_service.py` | 使用新字段名和 cache 配置 |
| `app/api.py` | 使用新 repository API |
| `app/disk_cleaner.py` | 使用 `status` 和 `file_dir` |

### 6.6 验收标准

- 删除 `runtime/discovery/discovery.db` 后，服务能创建新表并正常运行。
- SQLite 中核心视频表为 `videos`，不再创建新的 `discovered_videos`。
- `GET /api/videos` 返回字段和新表一致，主状态字段为 `status`。
- `GET /api/videos?status=downloaded` 能过滤待拉取视频。
- 如果仍保留兼容层，`GET /api/videos?download_status=downloaded` 与 `status=downloaded` 结果一致。
- 所有状态只使用一个 `status` 字段。
- `language_hint`、`comment_count`、`like_count` 等不可靠字段从模型、DB 和评分逻辑中删除。
- `DISCOVERY_CACHE_PATH` 和 `DISCOVERY_CACHE_TTL_SEC` 生效。
- 无效配置从 `settings.py` 删除，或文档明确标注为已废弃。

## 7. 阶段 4：重构搜索和评分

当前状态：已实施。搜索入口已明确为 `yt-dlp` provider；`discover_candidates()` 不再保留
`api_key` 等 YouTube API 兼容参数；评分只依赖播放量和发布时间，时长只做过滤；
发现缓存已写入 `provider`、`keywords`、`search` 和 `items`，关键词或过滤配置变化时不会复用旧缓存。

V3 第一批状态：已实施。搜索实现已拆到 `app/discovery/providers/`，通过
`DISCOVERY_PROVIDER=ytdlp` 选择当前 provider；`youtube_api` provider 保留为明确
unsupported 的预留入口。新增 `POST /api/discovery/preview`，用于只搜索和评分，
不会写入 DB 或下载文件。

V3 第二批状态：已实施。`VideoCandidate` 和 `videos` 表新增 `score_json`，
provider 会输出并持久化评分明细；基础质量规则已支持标题黑名单、频道黑名单、
频道白名单配置。

V4 第一批状态：已实施。HK 端新增拉取锁生命周期：
`POST /api/videos/<id>/pull-lock`、`POST /api/videos/<id>/release-pull-lock`、
`POST /api/videos/<id>/mark-published`；`confirm-pulled` 会清理锁字段并标记
`pulled`。本地拉取端已改为下载前抢锁、失败释放锁、成功确认 pulled。

V4 第二批状态：已实施。本地 `social-auto-upload/hk_puller.py` 已新增
`mark_hk_video_published()`，`mark_uploaded()` 和 `publish_pending()` 会在本地
发布成功后尽力回写 HK `published` 状态；HK 回写失败不影响本地 uploaded 记录。

### 7.1 目标

- 明确搜索只走 yt-dlp，删除 YouTube API 兼容参数。
- 评分只依赖真实可用字段。
- 搜索质量可配置、可解释。

### 7.2 搜索模块重构

`discover_candidates()` 已使用 keyword-only 参数：

```python
def discover_candidates(
    *,
    keywords: list[SearchKeyword],
    max_results_per_keyword: int,
    min_views: int,
    min_duration_sec: int,
    max_duration_sec: int,
) -> list[VideoCandidate]:
    ...
```

其中：

```python
@dataclass(frozen=True)
class SearchKeyword:
    keyword: str
    category: str
```

### 7.3 评分公式建议

第一版只使用真实字段：

```text
score = view_score + freshness_score + duration_score
view_score = log10(max(10, view_count))
freshness_score = 24 / age_hours，如果 published_at 可用，否则 0
duration_score = 0，先只做过滤，不做加权
```

不要再使用评论数、点赞数、语言字段。

### 7.4 搜索缓存策略

已改为配置驱动：

```text
DISCOVERY_CACHE_PATH=runtime/discovery/candidates_cache.json
DISCOVERY_CACHE_TTL_SEC=86400
```

缓存内容建议包含：

```json
{
  "created_at": "2026-06-14T00:00:00+00:00",
  "provider": "yt-dlp",
  "keywords": [{"keyword": "funny cats", "category": "pets"}],
  "search": {
    "max_results_per_keyword": 15,
    "min_views": 10000,
    "min_duration_sec": 60,
    "max_duration_sec": 1800
  },
  "items": []
}
```

这样可以判断缓存是否与当前关键词配置一致。

### 7.5 验收标准

- 搜索代码不再出现无用 `api_key`。
- 评分公式不依赖 `comment_count`、`like_count`、`language_hint`。
- 修改关键词后，旧缓存不会被错误复用。
- 日志能显示每个关键词搜索到多少候选、过滤掉多少候选。

## 8. 阶段 5：测试、文档和运行保障

当前状态：已实施第一轮。已新增 `hk-server/tests/` 离线 pytest 测试，覆盖
repository、scoring、disk_cleaner、api helper 和 task_state；`pyproject.toml`
已增加 `dev` 测试依赖和 pytest 配置；新增 `docs/hk-server/smoke-test.md`
记录自动测试、健康检查、任务锁 smoke、手动下载 smoke、systemd 示例和日志轮转建议。

### 8.1 测试范围

优先写不依赖 YouTube 网络的测试。

| 测试 | 覆盖内容 |
| --- | --- |
| repository 测试 | 建表、插入、状态流转、查询过滤 |
| scoring 测试 | 播放量、时长过滤和评分排序 |
| disk_cleaner 测试 | 过期清理、容量清理、状态变更 |
| api helper 测试 | 响应格式、鉴权、Range 解析 |
| task_state 测试 | 同时启动任务时只允许一个运行 |

### 8.2 建议测试目录

```text
hk-server/tests/
  test_repository.py
  test_scoring.py
  test_disk_cleaner.py
  test_api_helpers.py
  test_task_state.py
```

### 8.3 文档更新

需要同步更新：

| 文档 | 处理 |
| --- | --- |
| `hk-server/README.md` | 改为新 API、新状态、新配置 |
| `docs/hk-server-design.md` | 如保留，更新为新设计；否则删除旧设计文档 |
| `docs/hk-server-function-overview.md` | 重构完成后更新功能现状 |
| `docs/hk-server/smoke-test.md` | 新增部署后 smoke 和运行保障步骤 |

### 8.4 运行保障

已补充第一版：

- systemd service 示例。
- `.env.example`。
- 日志轮转建议。
- 磁盘空间检查。
- `curl /api/health` 检查示例。

## 9. 建议执行顺序

### V2 第一批：持久化任务记录

当前状态：已实施。完成内容：

- 新增 `hk-server/app/tasks.py`。
- SQLite 新增 `tasks` 和 `task_events` 表。
- `task_state.py` 从进程内状态改为基于 SQLite 任务表的兼容外观。
- `POST /api/discovery/run` 返回 `task_id`。
- `POST /api/downloads` 返回 `task_id` 和 `video_id`。
- `GET /api/tasks?status=&type=&limit=&offset=` 返回任务分页列表和 `current` 快照。
- `GET /api/tasks/<id>` 返回任务详情和事件。
- discovery/download 主流程写入任务事件。
- API 服务启动时将遗留 `pending/running` 任务标记为失败，避免重启后任务状态悬挂。

### V2 第二批：取消、重试和视频事件

当前状态：已实施。完成内容：

- `POST /api/tasks/<id>/cancel`，支持阶段边界取消。
- `POST /api/tasks/<id>/retry`，基于原任务 `input` 创建新任务。
- SQLite 新增 `video_events` 表。
- `GET /api/videos/<id>/events` 返回视频级事件。
- `videos` 增加 `task_id`、`download_attempts`、`last_error_at`、`download_progress`。
- 下载状态流转会写入 `video_events`。

### V2 第三批：下载实时进度

当前状态：已实施。完成内容：

- `downloader.py` 接入 yt-dlp `progress_hooks`。
- video stream 进度映射到 `0-50`。
- audio stream 进度映射到 `50-95`。
- metadata/thumbnail 完成后写入 `100`。
- `videos.download_progress` 实时更新。
- `video_events` 和 `task_events` 记录节流后的 progress 事件。

下一批建议继续：

1. 视需要补 `video_events` 的分页和按 `task_id` 查询。

### V2 第四批：手动下载 service 化

当前状态：已实施。完成内容：

- 新增 `download_service.run_manual_download()`。
- API 层只负责参数校验、创建任务和启动后台线程。
- 手动下载成功、失败、取消、进度、清理都在 service 层处理。
- 新增离线测试覆盖手动下载成功和失败落库。

### V2 第五批：视频事件查询增强

当前状态：已实施。完成内容：

- `GET /api/videos/<id>/events?task_id=&limit=&offset=` 支持分页和任务过滤。
- 新增 `GET /api/video-events?video_id=&task_id=&limit=&offset=`。
- repository 新增 `count_video_events()`。
- 离线测试覆盖按 `task_id` 查询和分页。

### 第 1 批：稳定性最小闭环

1. 新增 `app/task_state.py`。
2. 给 `run_discovery_and_download()` 和 `/api/download` 加任务锁。
3. 修复 `/api/download` 失败不落库。
4. 拆分 `pulled` 和 `expired` 状态。
5. 新增 `/api/health` 和 `/api/tasks`。

这一批完成后，服务即使功能不变，也会更稳定。

### 第 2 批：API 契约

当前状态：已实施。完成内容：

- JSON API 成功响应统一为 `{"ok": true, "data": ...}`。
- JSON API 错误响应统一为 `{"ok": false, "error": {"code": "...", "message": "..."}}`。
- 分页视频列表改为 `data.items/total/limit/offset`。
- `GET /api/videos/<id>` 直接返回 `data` 中的视频对象。
- `GET /api/videos/<id>/meta` 直接返回 `data` 中的 metadata。
- `GET /api/stats`、`GET /api/health`、`GET /api/tasks` 使用统一 envelope。
- 文件下载接口继续返回裸文件流，不包 JSON。
- 主接口切换为：
  - `POST /api/discovery/run`
  - `POST /api/downloads`
  - `POST /api/videos/<id>/confirm-pulled`
  - `DELETE /api/videos/<id>/files`
- 本地拉取端 `social-auto-upload/hk_puller.py` 已适配新 envelope 和 confirm-pulled。

1. 统一 JSON 响应格式。
2. 替换旧接口：
   - `/api/trigger-discovery` -> `/api/discovery/run`
   - `/api/download` -> `/api/downloads`
   - `DELETE /api/videos/<id>` -> `/api/videos/<id>/confirm-pulled`
3. 更新本地端对接文档。

### 第 3 批：DB 和配置重构

当前状态：已实施。核心视频表已切换到 `videos`，状态字段为 `status`；发现缓存路径和 TTL 已配置化。

1. 重建 SQLite schema。
2. 删除无效字段和配置。
3. cache 路径和 TTL 配置化。
4. API 查询推荐 `status`，并在代码支持时兼容旧 `download_status` 参数。
5. 更新 README。

### 第 4 批：搜索质量

1. 删除 `api_key` 兼容参数。
2. 简化 `VideoCandidate`。
3. 重写评分公式。
4. 增加关键词维度日志和缓存配置校验。

### 第 5 批：测试

1. 补 repository、scoring、disk_cleaner 测试。
2. 补 API helper 和 task_state 测试。
3. 写一条手动 smoke test 文档。

## 10. 第一批实施的详细任务拆分

第一批建议下一步直接实施，具体任务如下。

当前状态：已实施。完成内容：

- 新增 `app/task_state.py`。
- `run_discovery_and_download()` 接入任务锁和任务状态。
- `/api/discovery/run` 在启动后台线程前抢占任务锁。
- `/api/downloads` 在 URL 无法解析 `video_id` 时直接返回 400。
- 手动下载失败会调用 `mark_download_failed()` 落库。
- 新增 `mark_pulled()` 和 `mark_expired()`。
- disk cleaner 清理后标记 `expired`。
- 拉取确认 `POST /api/videos/<id>/confirm-pulled` 删除文件后标记 `pulled`。
- 新增 `GET /api/health` 和 `GET /api/tasks`。
- 第二批已移除旧主接口，统一使用新 API 契约。

### 10.1 新增任务状态模块

新增文件：

```text
hk-server/app/task_state.py
```

能力：

- `try_start_task(name: str) -> bool`
- `finish_task(summary: dict | None = None, error: str = '') -> None`
- `get_task_state() -> dict`

### 10.2 修改 discovery 主流程

文件：

```text
hk-server/app/download_service.py
```

改动：

- 在 `run_discovery_and_download()` 开始时尝试获取任务锁。
- 如果已有任务运行，返回 `{"skipped": True, "reason": "task_running"}`。
- `finally` 中释放任务状态。

### 10.3 修改手动 URL 下载

文件：

```text
hk-server/app/api.py
```

改动：

- 手动下载也走任务状态。
- 解析出 `video_id` 后，在异常分支调用 `mark_download_failed(db_path, video_id, str(exc))`。
- 如果 video_id 解析失败，直接返回 400，不启动后台线程。

### 10.4 拆分文件删除状态

文件：

```text
hk-server/app/discovery/repository.py
hk-server/app/disk_cleaner.py
hk-server/app/api.py
```

改动：

- `mark_cleaned()` 改成两个函数：
  - `mark_pulled()`
  - `mark_expired()`
- API 拉取确认使用 `mark_pulled()`。
- disk cleaner 使用 `mark_expired()`。

### 10.5 新增健康和任务接口

文件：

```text
hk-server/app/api.py
```

新增：

- `GET /api/health`
- `GET /api/tasks`

### 10.6 第一批验收命令

启动：

```bash
cd hk-server
source .venv/bin/activate
hk-server
```

健康检查：

```bash
curl http://127.0.0.1:8503/api/health
```

任务状态：

```bash
curl http://127.0.0.1:8503/api/tasks
```

重复触发：

```bash
curl -X POST http://127.0.0.1:8503/api/discovery/run
curl -X POST http://127.0.0.1:8503/api/discovery/run
```

预期第二次不会启动第二个任务。

手动下载失败测试：

```bash
curl -X POST http://127.0.0.1:8503/api/downloads \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://www.youtube.com/watch?v=invalidxxxx","category":"manual"}'
```

预期：

- 无法解析合法 video_id 时返回 400。
- 如果解析合法但下载失败，DB 状态为 `failed`。

## 11. 决策建议

建议下一步就实施“第 1 批：稳定性最小闭环”。这一批不会大幅改变业务功能，但能先解决最危险的问题：

- 并发任务互相覆盖。
- 失败状态不落库。
- 删除状态语义混乱。
- 本地端缺少健康检查。

完成第一批后，再决定是否马上做 DB 重建。如果服务还未正式部署，建议直接在第二批或第三批重建 DB，避免继续维护 `discovered_videos` 里的无效字段。

# hk-server 版本演进设计

本文补充 `implementation-plan.md` 中没有展开的 V2、V3 以及后续版本设计。当前项目处于第一版从头开发阶段，不需要迁移兼容；每个版本都可以直接改 schema、接口和模块边界。

## 1. 总体版本目标

| 版本 | 主题 | 核心目标 |
| --- | --- | --- |
| V1 | 稳定中转服务 | 搜索、下载、API、状态、清理稳定可用 |
| V2 | 任务化和可观测 | 所有发现/下载都有任务记录、进度、重试和可查询状态 |
| V3 | 搜索质量和策略 | 提升候选质量，支持多搜索源、黑白名单、分类策略 |
| V4 | 分发协作 | 和本地端建立可靠拉取确认、保留策略、素材生命周期协作 |
| V5 | 运维和规模化 | 部署、监控、告警、限流、多实例或队列化扩展 |

## 2. V1：稳定素材中转服务

### 2.1 目标

V1 只解决“远程中转服务稳定可用”：

- 能定时搜索 YouTube。
- 能下载 video/audio/thumbnail/meta。
- 本地端能查询和拉取。
- 远程端能确认拉取和清理磁盘。
- 状态不会乱，失败能落库，并发不会互相覆盖。

### 2.2 范围

保留：

- `yt-dlp ytsearch` 搜索。
- SQLite 单库。
- 标准库 HTTP API。
- 单进程后台线程。
- 本地端拉取后合并。

不做：

- 不做任务持久队列。
- 不做搜索源扩展。
- 不做发布。
- 不做分布式。
- 不做复杂后台管理。

### 2.3 主要改动

| 模块 | 改动 |
| --- | --- |
| `api.py` | 增加 `/api/health`、`/api/tasks`、拉取确认接口 |
| `download_service.py` | 加任务锁，避免并发 discovery/download |
| `repository.py` | 拆分 `pulled`、`expired`、`failed` 状态 |
| `disk_cleaner.py` | 清理状态改成 `expired` |
| `settings.py` | 删除或修正明显无效配置 |

### 2.4 推荐 API

```text
GET  /api/health
GET  /api/tasks
GET  /api/videos
GET  /api/videos/<id>
GET  /api/videos/<id>/meta
GET  /api/videos/<id>/file?type=video|audio|thumbnail
POST /api/discovery/run
POST /api/downloads
POST /api/videos/<id>/confirm-pulled
GET  /api/stats
```

### 2.5 验收标准

- 并发触发 discovery 时只有一个任务运行。
- 手动下载失败后状态为 `failed`。
- 本地确认拉取后状态为 `pulled`，文件被删除。
- 自动清理后状态为 `expired`。
- `/api/health` 能反映 DB、下载目录和磁盘状态。
- 本地端可稳定拉取 `downloaded` 状态素材。

## 3. V2：任务化和可观测

当前状态：第二批已实施。已新增 `app/tasks.py`，在 SQLite 中创建 `tasks`
和 `task_events`；`POST /api/discovery/run`、`POST /api/downloads` 返回
`task_id`；`GET /api/tasks` 返回分页任务列表，`GET /api/tasks/<id>` 返回
任务详情和事件；服务启动时会把遗留 `pending/running` 任务标记为失败以完成重启恢复。
`POST /api/tasks/<id>/cancel`、`POST /api/tasks/<id>/retry`、`GET /api/videos/<id>/events`
已实现；`videos` 已记录 `task_id`、`download_attempts`、`last_error_at`、`download_progress`。
下载中实时进度作为下一批继续实现。

### 3.1 目标

V2 把后台行为从“临时线程 + 日志”升级为“可查询任务系统”。重点是可观测、可重试、可排障。

### 3.2 核心能力

新增：

- 持久化任务表。已完成第一批。
- discovery 任务记录。已完成第一批。
- 单 URL 下载任务记录。已完成第一批。
- 最近任务列表和详情 API。已完成第一批。
- 每个视频下载进度和错误记录。已完成基础字段和失败记录，实时进度下一批。
- 任务重试接口。已完成。
- 任务取消标记。已完成阶段边界取消。

### 3.3 建议 schema

新增 `tasks`：

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

当前实现字段名使用 `task_id`、`task_name`，语义分别对应 `id`、`type`。

当前第一批新增 `task_events`：

```sql
CREATE TABLE task_events (
  event_id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id INTEGER NOT NULL,
  event_type TEXT NOT NULL,
  message TEXT NOT NULL DEFAULT '',
  data_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);
```

当前第二批新增 `video_events`：

```sql
CREATE TABLE video_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  video_id TEXT NOT NULL,
  event_type TEXT NOT NULL,
  message TEXT NOT NULL DEFAULT '',
  data_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);
```

当前第二批扩展 `videos`：

```text
task_id
download_progress
download_attempts
last_error_at
```

### 3.4 任务状态

```text
pending
running
success
failed
cancel_requested
cancelled
```

### 3.5 API 设计

```text
GET  /api/tasks?status=&type=&limit=&offset=
GET  /api/tasks/<id>
POST /api/tasks/<id>/retry
POST /api/tasks/<id>/cancel
GET  /api/videos/<id>/events
```

当前已实现 `GET /api/tasks`、`GET /api/tasks/<id>`、retry、cancel 和 video events。

V1 的：

```text
POST /api/discovery/run
POST /api/downloads
```

在 V2 应返回 `task_id`：

```json
{
  "ok": true,
  "data": {
    "task_id": 123,
    "status": "running"
  }
}
```

### 3.6 代码改动

| 模块 | 改动 |
| --- | --- |
| 新增 `app/tasks.py` | 任务 CRUD、状态流转 |
| 新增 `app/events.py` | 视频事件记录 |
| `api.py` | 增加任务 API |
| `download_service.py` | 接收 `task_id`，每个阶段更新任务 |
| `downloader.py` | 支持进度 hook，把进度写入 task/video |

### 3.7 验收标准

- 手动触发 discovery 返回 `task_id`。
- 任务运行中可以查到 `running` 状态。
- 任务完成后可以看到 summary。
- 失败任务可以重试。
- 视频下载失败能看到失败事件和错误原因。

## 4. V3：搜索质量和策略

### 4.1 目标

V3 解决“找到的视频质量不稳定”的问题。当前 yt-dlp 搜索字段少，语言、评论、点赞、发布时间都不可靠，V3 要把搜索变成可解释、可调优的策略模块。

### 4.2 搜索 provider 设计

引入 provider 抽象：

```text
app/discovery/providers/
  base.py
  ytdlp_search.py
  youtube_api.py
```

Provider 接口：

```python
class DiscoveryProvider:
    name: str

    def search(self, query: SearchQuery) -> list[RawCandidate]:
        ...
```

支持两种 provider：

| Provider | 优点 | 缺点 |
| --- | --- | --- |
| `ytdlp` | 无 API key，无配额 | 字段少，搜索稳定性一般 |
| `youtube_api` | 字段更可靠，可按时间、语言、统计过滤 | 需要 API key，有配额 |

V3 不一定默认启用 YouTube API，但代码结构要允许切换。

### 4.3 搜索策略

新增策略配置：

```text
DISCOVERY_PROVIDER=ytdlp
DISCOVERY_REGION=US
DISCOVERY_RELEVANCE_LANGUAGE=en
DISCOVERY_QUERY_ORDER=viewCount
DISCOVERY_CHANNEL_ALLOWLIST=
DISCOVERY_CHANNEL_BLOCKLIST=
DISCOVERY_TITLE_BLOCKLIST=
DISCOVERY_MIN_CHANNEL_SUBSCRIBERS=
```

### 4.4 候选质量规则

新增规则：

- 标题关键词黑名单。
- 频道黑名单。
- 频道白名单。
- 最小时长、最大时长。
- 最低播放量。
- 是否排除 live / shorts。
- 是否排除儿童内容。
- 是否排除已拉取或已发布视频。

### 4.5 评分公式升级

V3 评分应拆成可解释字段：

```text
score_total
score_views
score_freshness
score_duration
score_channel
score_keyword
penalty_title
penalty_duplicate
```

DB 可保存评分详情：

```text
score_json TEXT NOT NULL DEFAULT '{}'
```

### 4.6 API 设计

```text
POST /api/discovery/preview
POST /api/discovery/run
GET  /api/discovery/runs/<task_id>/candidates
```

`/api/discovery/preview` 只搜索和评分，不下载，方便调关键词。

### 4.7 验收标准

- 可以切换 `ytdlp` 和 `youtube_api` provider。
- 每条候选能看到评分明细。
- 黑名单频道不会进入下载队列。
- preview 不会下载文件。
- 修改关键词后可以快速预览候选质量。

## 5. V4：分发协作和素材生命周期

### 5.1 目标

V4 重点不是搜索和下载，而是让 HK 端和本地端之间的协作更可靠，避免“本地下载一半，远程删了”“本地发布失败，远程也没了”等问题。

### 5.2 生命周期状态

建议状态：

```text
discovered
download_pending
downloading
downloaded
pulling
pulled
published
expired
failed
```

如果 HK 端不关心发布，也至少支持：

```text
downloaded -> pulling -> pulled
downloaded -> expired
```

### 5.3 两阶段拉取确认

新增流程：

```text
本地端 POST /api/videos/<id>/pull-lock
  -> HK 标记 pulling，返回过期时间

本地端下载 video/audio/meta/thumbnail

本地端 POST /api/videos/<id>/confirm-pulled
  -> HK 删除文件，标记 pulled

如果本地端失败：
  POST /api/videos/<id>/release-pull-lock
  -> HK 回到 downloaded

如果 pulling 超时：
  HK 自动回到 downloaded
```

### 5.4 API 设计

```text
POST /api/videos/<id>/pull-lock
POST /api/videos/<id>/release-pull-lock
POST /api/videos/<id>/confirm-pulled
POST /api/videos/<id>/mark-published
```

### 5.5 本地端协作字段

HK DB 可增加：

```text
pull_locked_by
pull_lock_expires_at
pulled_at
published_at
publish_platform
publish_ref
```

### 5.6 验收标准

- 同一个视频不能被两个本地端同时拉取。
- 拉取失败可以释放锁。
- 拉取锁超时后视频重新可拉取。
- 本地发布成功后可回写发布状态。

## 6. V5：运维和规模化

### 6.1 目标

V5 解决长期运行和规模化问题。重点是部署、监控、限流、告警和恢复。

### 6.2 运维能力

新增：

- systemd service 文件。
- `.env.example` 完整模板。
- `/api/metrics` Prometheus 风格指标。
- 日志结构化 JSON 可选。
- 日志轮转说明。
- 磁盘剩余空间告警。
- 下载失败率统计。
- YouTube 限流检测。

### 6.3 队列和 worker

如果下载量变大，V5 可以把任务执行从 API 进程拆出来：

```text
hk-server-api
hk-server-worker
```

第一步仍可使用 SQLite 任务表。

后续如果需要多 worker，再考虑：

- Redis Queue
- Celery
- PostgreSQL

不要在第一版提前引入这些复杂度。

### 6.4 API 设计

```text
GET /api/metrics
GET /api/admin/disk
POST /api/admin/cleanup/run
POST /api/admin/tasks/<id>/force-fail
```

### 6.5 验收标准

- 服务重启后能恢复 pending/running 异常任务。
- systemd 管理下能自动重启。
- 磁盘不足时不会继续下载新视频。
- metrics 能看到下载成功数、失败数、磁盘使用、任务状态。

## 7. 不建议提前做的内容

这些内容等业务跑通后再做：

- 多机部署。
- PostgreSQL 替换 SQLite。
- Celery/Redis 队列。
- Web 管理后台。
- 自动剪辑。
- HK 端合并转码。
- HK 端平台发布。
- 复杂推荐算法。

当前最重要的是先把“远程素材中转仓库”做稳。

## 8. 推荐里程碑

### M1：V1 稳定可用

完成：

- 任务锁。
- 失败落库。
- `pulled/expired` 状态。
- `/api/health`。
- `/api/tasks`。
- 拉取确认接口。

### M2：V1.5 API 清理

完成：

- 新 API 命名。
- 统一 JSON 格式。
- 删除旧接口。
- 更新本地端对接。

### M3：V2 任务化

完成：

- `tasks` 表。
- 任务详情 API。
- 重试和取消。
- 下载事件记录。

### M4：V3 搜索策略

完成：

- provider 抽象。
- preview 接口。
- 评分明细。
- 黑白名单。

### M5：V4 协作生命周期

完成：

- pull-lock。
- release-lock。
- published 回写。
- 锁超时恢复。

### M6：V5 运维化

完成：

- systemd。
- metrics。
- 磁盘保护。
- 任务恢复。

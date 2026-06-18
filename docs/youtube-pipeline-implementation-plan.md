# youtube-pipeline 阶段任务与实施方案

本文档基于 `docs/youtube-pipeline-architecture.md`，把后续功能按阶段拆解为可实施任务。

总原则：

- 先做稳定的数据和状态底座。
- 再把下载、发布改造成状态驱动。
- 再引入 worker 循环。
- 最后做自动发现和 Web。
- 每个阶段都必须可单独验收。

## 总体优先级

```text
P0 core 数据库和状态机
P1 downloader 下载模块状态化
P2 publisher 发布模块状态化
P3 worker 自动循环
P4 discovery 自动发现
P5 web API
P6 web 前端
```

## P0：core 数据库和状态机

### 目标

建立所有模块共享的数据底座。后续搜索、下载、发布、Web 都通过 SQLite 和 repository 协作。

### 范围

新增目录：

```text
youtube-pipeline/app/core/
  __init__.py
  config.py
  db.py
  schema.py
  repository.py
  status.py
  events.py
  jobs.py
```

### 任务拆解

1. 配置迁移到 `core.config`
   - 统一解析 `.env`
   - 支持项目根目录路径
   - 相对路径按 `.env` 所在目录解析
   - 新增 `DB_PATH=runtime/data/pipeline.db`
   - 新增 `TMP_DIR=runtime/tmp`

2. SQLite 初始化
   - 新建 `core.db`
   - 提供 `connect()`
   - 开启 WAL
   - 行结果使用 dict/Row

3. Schema 第一版
   - `videos`
   - `video_metadata`
   - `media_files`
   - `publish_drafts`
   - `publish_records`
   - `jobs`
   - `events`

4. Repository 第一版
   - `upsert_video`
   - `get_video`
   - `list_videos`
   - `update_video_status`
   - `save_metadata`
   - `save_media_files`
   - `save_publish_draft`
   - `save_publish_record`
   - `create_event`

5. 状态机
   - 定义允许状态
   - 定义允许迁移
   - 非法迁移直接报错
   - 状态变化自动写 `events`

6. 基础 CLI
   - `youtube-pipeline init-db`
   - `youtube-pipeline add-url <url>`
   - `youtube-pipeline list`

### 验收标准

- `youtube-pipeline init-db` 能创建数据库。
- `youtube-pipeline add-url <url>` 能写入 `videos(status=selected)`。
- 重复 `add-url` 不产生重复视频。
- 状态变化写入 `events`。
- 单元测试覆盖 schema 初始化、upsert、状态迁移、事件写入。

### 风险点

- schema 一开始不要过度复杂。
- repository 不要直接混入 yt-dlp、LLM、biliup 逻辑。

## P1：downloader 下载模块状态化

### 目标

把当前单视频下载合并能力接入数据库状态，解决下载结果、错误和文件路径持久化问题。

### 范围

新增：

```text
youtube-pipeline/app/download_service.py
```

现阶段保留 `app/downloader.py` 作为底层 yt-dlp/ffmpeg 能力，不拆目录。`download_service.py` 只做 DB 状态、job、events、文件路径持久化编排。

### 任务拆解

1. 下载服务
   - 输入 `video_id`
   - 从 DB 读取视频记录
   - 状态 `selected -> downloading`
   - 下载完成后 `downloading -> downloaded`
   - 失败后写 `failed`
   - 已下载且 merged 文件存在时默认跳过
   - `--force` 允许重新下载，状态允许 `downloaded -> downloading`

2. yt-dlp 元数据
   - 获取完整 meta
   - 完整 JSON 只保存为 `runtime/downloads/<video_id>/meta.json`
   - DB 只保存基础字段：`title/channel/duration/view_count/category/source_url/status`
   - 不把完整 yt-dlp JSON 复制进 `video_metadata`

3. 下载覆盖策略
   - 第一版本不做兼容迁移和旧产物保护
   - 下载前允许覆盖同名 `video.*` / `audio.*`
   - 合并前允许覆盖 `<video_id>_merge.mp4`

4. 文件记录
   - `media_files.meta_path`
   - `media_files.video_path`
   - `media_files.audio_path`
   - `media_files.poster_path`
   - `media_files.merged_path`

5. Job 与 events
   - `add-url` 创建 pending download job
   - `download <video_id>` 没有 pending job 时自动创建
   - job 状态：`pending -> running -> succeeded/failed`
   - 阶段事件：`download_started`、`metadata_saved`、`video_downloaded`、`audio_downloaded`、`poster_downloaded`、`merge_done`、`download_done`、`download_failed`

6. CLI 接入
   - `youtube-pipeline download <video_id>`
   - `youtube-pipeline download-next`
   - `youtube-pipeline download-url <url>` 保留为无 DB 的调试入口

### 验收标准

- 已入库 URL 可以被下载。
- 下载完成后 DB 状态是 `downloaded`。
- 文件路径写入 `media_files`。
- 下载失败写 `events` 和 `last_error`。
- 合并文件包含 video/audio 流。
- 单元测试覆盖成功下载、已有文件跳过、失败落库、pending job 选择。

### 风险点

- yt-dlp 会产生不同扩展名，文件定位要稳定。
- ffmpeg 失败信息要保存，便于 Web 展示。
- 当前没有并发锁，P3 worker 阶段再补 lock/lease。

### 当前状态

已完成。使用以下链接完成真实下载验证：

- `https://www.youtube.com/watch?v=KsjVUJMWzks`
- `https://www.youtube.com/watch?v=dRVkQsZFISU`

两个 merged 文件均经 `ffprobe` 验证包含 H.264 video 和 AAC audio。

## P2：publisher 发布模块状态化

### 目标

把当前发布能力接入数据库状态，实现发布草稿、LLM tid 选择、重复发布保护。

### 范围

新增：

```text
youtube-pipeline/app/publish_service.py
```

现阶段保留 `app/publisher.py` 和 `app/ai_describe.py`，只新增服务层把草稿生成、发布和 DB 状态接起来。

### 任务拆解

1. 发布草稿生成
   - 状态 `downloaded -> describing`
   - LLM 生成标题、描述、标签
   - 保存规范化后的 payload 和 tid 选择结果
   - 规范化结果写入 `publish_drafts`
   - 状态 `describing -> ready_to_publish`
   - `ready_to_publish -> describing` 允许重新生成草稿

2. tid 选择
   - 输入包含 yt-dlp meta
   - LLM 从白名单选择 tid
   - 非白名单 tid 真实发布失败
   - `tid_source=fallback` 的草稿允许保存，但真实发布 fail-closed

3. 重复发布保护
   - 检查 `publish_records`
   - 同一 `video_id + platform + account` 已成功发布则阻止
   - 需要 `--force` 才允许重复发布

4. B 站发布
   - 复用 `social-auto-upload` 的 `upload_to_bilibili`
   - 发布前检查 merged 文件存在
   - 状态 `ready_to_publish -> publishing`
   - 成功后写 `publish_records`
   - 状态 `publishing -> published`
   - 失败写 `events` 和 `last_error`

5. CLI 接入
   - `youtube-pipeline describe <video_id>`
   - `youtube-pipeline publish <video_id>`
   - `youtube-pipeline publish-next`
   - `youtube-pipeline publish <video_id> --force`
   - `youtube-pipeline publish-dir <data_dir>` 保留为无 DB 的调试入口

### 验收标准

- 已下载视频能生成草稿。
- 草稿可重复生成但不自动重复发布。
- tid 选择结果保存 source/reason。
- tid 选择失败时真实发布被阻止。
- 已发布视频再次发布被阻止。
- 单元测试覆盖草稿生成、dry-run 发布、真实发布成功、重复发布阻断、fallback tid 阻断。

### 风险点

- LLM 输出不可控；当前保存 normalized payload，后续如需要更强审计再让 `ai_describe` 暴露 raw output。
- B 站返回错误需要原样保存。
- 当前 MiniMax Anthropic 接口可能返回 500；这种情况下会生成 fallback 草稿，但真实发布会被阻断，避免错误分区自动发布。

### 当前状态

已完成服务层和 CLI：

- `describe <video_id>`：读取 `media_files/meta.json`，生成草稿，写入 `publish_drafts`，状态到 `ready_to_publish`。
- `publish <video_id> --dry-run`：从 DB 草稿和媒体路径构造发布 payload。
- `publish <video_id>`：真实发布前检查重复发布、tid 白名单、fallback tid。
- `publish-next`：发布下一条 `ready_to_publish` 视频。
- `show <video_id>`：展示草稿、发布记录、describe/publish job。

使用 `dRVkQsZFISU` 完成真实 `describe` 和 `publish --dry-run` 验证。由于 MiniMax 返回 500，本次生成 fallback 草稿；不带 `--dry-run` 的真实发布被正确阻断。

## P3：worker 自动循环

### 目标

让流程从手动单步变成可持续运行的自动队列。

### 范围

新增：

```text
youtube-pipeline/app/worker/
  __init__.py
  runner.py
```

### 任务拆解

1. job runner
   - download job
   - describe job
   - publish job
   - cleanup job 预留

2. worker-run 一次性执行
   - `youtube-pipeline worker-run`
   - 每轮按顺序执行 `download-next`、`describe-next`、`publish-next`
   - 每个阶段最多处理一条
   - 单个阶段失败不阻断后续阶段
   - 写入 `worker_run_started`、`worker_run_finished` events

3. worker 循环
   - `youtube-pipeline worker`
   - 支持 `--once`
   - 支持 `--interval`
   - 使用 `WORKER_INTERVAL_SECONDS`

4. 发布安全开关
   - `WORKER_ENABLE_PUBLISH=false` 时 worker 不执行发布
   - `WORKER_PUBLISH_DRY_RUN=true` 时 worker 发布只 dry-run
   - CLI 可用 `--enable-publish`、`--publish-dry-run` 覆盖本轮行为

5. jobs 领取机制（后续增强）
   - 找到可执行 job
   - 设置 `locked_at`
   - 设置 `lock_owner`
   - 防止重复执行

6. 重试策略（后续增强）
   - `attempts`
   - `max_attempts`
   - 失败后延迟重试
   - 超过次数标记 failed

7. 操作命令
   - `youtube-pipeline retry <video_id>`
   - `youtube-pipeline skip <video_id>`
   - `youtube-pipeline status`

### 验收标准

- 添加 URL 后 worker 能自动下载、生成草稿。
- 发布在 env 明确开启后才会由 worker 执行。
- 任务失败后能记录并继续处理其它任务。
- 进程重启后能继续处理未完成任务。
- 第一版单 worker 运行；多 worker lock/lease 后续补。

### 风险点

- SQLite 并发写要保持简单，第一版单 worker 即可。
- 发布任务需要节流，避免短时间连续投稿。
- 自动发布必须默认关闭，避免未审核草稿被 worker 直接投递。

### 当前状态

已完成第一版：

- `worker-run`：执行一轮 download/describe/publish。
- `worker`：循环执行，支持 `--once` 和 `--interval`。
- `WORKER_ENABLE_PUBLISH`：控制 worker 是否允许发布。
- `WORKER_PUBLISH_DRY_RUN`：控制 worker 发布是否 dry-run。
- `status`：展示视频状态统计、job 状态统计、失败视频和最近事件。
- `retry`：将 failed 视频按最近失败 job 或当前产物推断回到 download/describe/publish 阶段。
- `skip`：手动跳过未发布视频；活跃状态需要 `--force`。
- 单元测试覆盖发布禁用、发布启用 dry-run、阶段失败继续运行。
- 单元测试覆盖 status/retry/skip 的主要规则。

未完成：

- 多 worker lock/lease。
- 失败延迟重试。

## P4：discovery 自动发现

### 目标

自动搜索候选视频，并根据规则过滤入库。

### 范围

新增：

```text
youtube-pipeline/app/discovery/
  __init__.py
  models.py
  service.py
  filters.py
  sources.py
```

### 任务拆解

1. 搜索配置
   - `DISCOVERY_SOURCES_JSON`
   - 支持 `search`
   - 支持 `trending`
   - 支持 `channel_uploads`
   - 每个 source 可单独设置 `max_results`

2. YouTube API sources
   - `search.list` 搜索关键词候选
   - `videos.list(chart=mostPopular)` 获取地区热门
   - `search.list(channelId, order=date)` 获取频道最新上传
   - 统一补齐 `videos.list` 详情

3. 过滤规则
   - video_id 去重
   - 时长范围
   - 播放量范围
   - 标题黑名单
   - 频道黑名单/白名单
   - 分类黑名单/白名单

4. 过滤原因
   - 每个 rejected candidate 写入 reason
   - 被选中写入 `videos(selected)`
   - 被选中创建 `download` job
   - discovery 开始、结束、拒绝、选中均写 events

5. CLI 接入
   - `youtube-pipeline discover`
   - `youtube-pipeline discover --source search|trending|channel_uploads`
   - `youtube-pipeline discover --dry-run`

### 验收标准

- discover 能产生候选。
- 已处理 video_id 不重复入队。
- dry-run 不写入视频和 job。
- 非 dry-run 写入 selected 视频和 pending download job。
- 单元测试覆盖 source 解析、过滤、dry-run、入库。

### 当前状态

已完成第一版：

- 配置项：
  - `DISCOVERY_SOURCES_JSON`
  - `DISCOVERY_MAX_RESULTS_PER_SOURCE`
  - `DISCOVERY_MIN_DURATION_SECONDS`
  - `DISCOVERY_MAX_DURATION_SECONDS`
  - `DISCOVERY_MIN_VIEW_COUNT`
  - `DISCOVERY_TITLE_BLOCKLIST`
  - `DISCOVERY_CHANNEL_ALLOWLIST`
  - `DISCOVERY_CHANNEL_BLOCKLIST`
  - `DISCOVERY_CATEGORY_ALLOWLIST`
  - `DISCOVERY_CATEGORY_BLOCKLIST`
- sources:
  - `search`
  - `trending`
  - `channel_uploads`，支持 `channel_id` 和 `handle`
- sorting:
  - 候选统一计算 `score`
  - score 基于 source 权重、播放量、时长区间
  - accepted 候选按 score 降序输出和入库
- CLI:
  - `discover`
  - `discover --dry-run`
  - `discover --source ...`
- 真实 YouTube API 验证：
  - `discover --dry-run --source search` 成功返回候选。
  - 临时 DB 下 `discover --source search` 成功入库并创建 download jobs。

未完成：

- 更细的评分策略。
- 更丰富的 discovery run 统计表。
- 过滤原因可查询。
- selected 视频能被 worker 后续处理。

### 风险点

- YouTube API 配额。
- 搜索质量需要后续迭代，不在第一版过度优化。

## P5：Web API

### 目标

提供 Web 可视化所需后端接口。

### 范围

可选择 Flask 或 FastAPI。第一版建议优先使用现有 Python 依赖最少的方案。

新增：

```text
youtube-pipeline/app/web/
  __init__.py
  api.py
  schemas.py
```

### API 草案

```text
GET  /api/videos
GET  /api/videos/<video_id>
GET  /api/videos/<video_id>/events
GET  /api/videos/<video_id>/metadata
GET  /api/videos/<video_id>/files
GET  /api/jobs
GET  /api/stats

POST /api/videos
POST /api/videos/<video_id>/download
POST /api/videos/<video_id>/describe
POST /api/videos/<video_id>/publish
POST /api/videos/<video_id>/retry
POST /api/videos/<video_id>/skip
PATCH /api/videos/<video_id>/draft

POST /api/discovery/run
```

### 验收标准

- 能通过 API 查看视频列表和详情。
- 能查看 events。
- 能触发下载、描述、发布。
- 能编辑发布草稿。
- API 不直接调用 yt-dlp/ffmpeg/biliup，而是调用 service 或创建 job。

### 风险点

- 不要让 Web 绕过状态机直接改状态。
- 操作接口需要防重复提交。

## P6：Web 前端

### 目标

提供可视化操作界面。

### 页面拆解

1. Dashboard
   - 总视频数
   - 各状态数量
   - 今日下载/发布数量
   - 最近错误

2. 视频列表
   - 状态过滤
   - 分类过滤
   - 搜索标题/频道
   - 快捷操作

3. 视频详情
   - 基础信息
   - meta 摘要
   - 下载文件
   - 发布草稿
   - tid 选择理由
   - events

4. 发布草稿编辑
   - title
   - description
   - tags
   - tid
   - 保存
   - 发布

5. Worker/任务页
   - jobs 列表
   - 重试
   - 跳过
   - 错误查看

### 验收标准

- 用户可以不使用 CLI 完成查看、编辑、发布、重试、跳过。
- 页面不隐藏错误。
- 发布前能看到 title/description/tags/tid。

### 风险点

- 第一版不要做复杂视觉设计。
- 操作型界面优先密度、清晰、可控。

## 第一阶段建议实施包

下一步建议只做：

```text
P0 + P1 的最小闭环
```

具体任务：

1. 新建 `core/`。
2. 新建 SQLite schema。
3. 实现 repository。
4. 实现 `init-db`。
5. 实现 `add-url`。
6. 把当前下载逻辑接入 DB。
7. 下载完成写 `media_files`。
8. 错误写 `events`。
9. 下载/合并改原子替换。

完成后验收：

```bash
youtube-pipeline init-db
youtube-pipeline add-url "https://www.youtube.com/watch?v=..."
youtube-pipeline download-next
youtube-pipeline list
```

预期：

- DB 中有视频记录。
- 状态从 `selected` 到 `downloaded`。
- 文件路径入库。
- 失败可查 events。

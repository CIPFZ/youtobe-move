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
P7 失败分类、延迟重试和队列自愈
P8 worker lock/lease 和运行态恢复
P9 Web 管理重构
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
   - 每轮按顺序执行 `discovery`、`download-next`、`describe-next`、`publish-next`
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

5. 发现低水位触发
   - `WORKER_ENABLE_DISCOVERY=true` 时 worker 可执行 discovery
   - `WORKER_DISCOVERY_MIN_QUEUE_SIZE` 控制 active queue 低水位
   - `WORKER_DISCOVERY_SOURCE` 可限制 worker 只跑某一类 discovery source
   - active queue 达到低水位时跳过 discovery，避免无限堆积候选

6. jobs 领取机制（后续增强）
   - 找到可执行 job
   - 设置 `locked_at`
   - 设置 `lock_owner`
   - 防止重复执行

7. 重试策略（后续增强）
   - `attempts`
   - `max_attempts`
   - 失败后延迟重试
   - 超过次数标记 failed

8. 操作命令
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

- `worker-run`：已接入 discovery 低水位补充，执行顺序为 discovery/download/describe/publish。
- `worker`：循环执行，支持 `--once` 和 `--interval`。
- `WORKER_ENABLE_DISCOVERY`：控制 worker 是否允许发现新候选。
- `WORKER_DISCOVERY_MIN_QUEUE_SIZE`：active queue 低于该值时触发 discovery。
- `WORKER_DISCOVERY_SOURCE`：可限制 worker 只执行 `search`、`trending` 或 `channel_uploads`。
- `WORKER_ENABLE_PUBLISH`：控制 worker 是否允许发布。
- `WORKER_PUBLISH_DRY_RUN`：控制 worker 发布是否 dry-run。
- `status`：展示视频状态统计、active queue 数量、job 状态统计、失败视频和最近事件。
- `retry`：将 failed 视频按最近失败 job 或当前产物推断回到 download/describe/publish 阶段。
- `skip`：手动跳过未发布视频；活跃状态需要 `--force`。
- 单元测试覆盖发布禁用、发布启用 dry-run、阶段失败继续运行。
- 单元测试覆盖 discovery 低水位跳过策略。
- 单元测试覆盖 status/retry/skip 的主要规则。

未完成：

- 多 worker 压力测试。

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
- discovery 已接入 worker 低水位补充，当前 active queue 达到阈值时会跳过 discovery，低于阈值时自动补充候选。

### 风险点

- YouTube API 配额。
- 搜索质量需要后续迭代，不在第一版过度优化。

## P5：Web 最小管理台

### 目标

提供本地 Web 可视化和受控操作入口，让队列、草稿、事件和发布状态可见。

### 范围

第一版使用标准库 `ThreadingHTTPServer`，不新增 Flask/FastAPI 依赖。

新增：

```text
youtube-pipeline/app/web.py
youtube-pipeline/app/web_static/index.html
```

### API

```text
GET  /
GET  /api/status
GET  /api/videos
GET  /api/videos/<video_id>
GET  /api/videos/<video_id>/file?type=meta|video|audio|poster|merged

POST /api/discover
POST /api/worker-run
POST /api/download-next
POST /api/publish-next
POST /api/videos/<video_id>/download
POST /api/videos/<video_id>/describe
POST /api/videos/<video_id>/publish-dry-run
POST /api/videos/<video_id>/publish
POST /api/videos/<video_id>/retry
POST /api/videos/<video_id>/skip
```

### 验收标准

- 能通过 API 查看视频列表和详情。
- 能查看 events。
- 能触发下载、描述、发布。
- API 不直接调用 yt-dlp/ffmpeg/biliup，而是调用 service 或创建 job。
- 真实发布必须传 `confirm=true`，前端必须二次确认。
- fallback tid 仍由 publish service 阻断真实发布。

### 当前状态

已完成最小版：

- `youtube-pipeline web`：启动本地管理台。
- `WEB_HOST`、`WEB_PORT`：控制 Web 绑定地址。
- 队列列表：展示状态、频道、时长、播放量、tid、tid source。
- 状态统计：展示 active queue、ready、published、publish mode。
- 视频详情：展示基础信息、原链接、发布草稿、tid 选择理由、标签、发布记录、最近事件。
- 文件入口：poster、merged 视频、meta。
- 操作按钮：运行一轮、发现预览、下载、生成文案、通过、拒绝、发布预览、真实发布、重试、跳过。
- 安全保护：真实发布需要前端确认和 API `confirm=true`；worker 自动发布仍默认关闭。
- 浏览器验证：页面加载真实队列、详情可展示、发布预览不改变发布状态。

未完成：

- 草稿编辑。
- 登录认证。
- 更细的筛选和搜索。
- Web 上的批量操作。

### 风险点

- 不要让 Web 绕过状态机直接改状态。
- 操作接口需要防重复提交。

## P6：发布审核和自动发布调度

### 目标

在 P5 可视化基础上增加审核状态、节流策略和受控自动发布。

### 任务拆解

1. 草稿审核
   - `pending`
   - `approved`
   - `rejected`
   - 只有 approved 才允许自动发布

2. 自动发布模式
   - `manual`
   - `approved_auto`
   - `full_auto`

3. 发布节流
   - 每日发布上限
   - 最小发布间隔
   - 可发布时间窗口

4. 草稿编辑
   - title
   - description
   - tags
   - tid
   - 保存
   - approve/reject

5. Worker/任务页
   - jobs 列表
   - 重试
   - 跳过
- 错误查看

### 当前状态

已完成最小版：

- `PUBLISH_MODE=manual|approved_auto|full_auto`。
- `manual`：worker/publish-next 不自动发布。
- `approved_auto`：只自动发布 `approved` 草稿。
- `full_auto`：允许自动发布非 rejected、非 fallback 的有效草稿。
- 生成草稿时：
  - `manual`、`approved_auto` 默认写入 `pending`
  - `full_auto` 默认写入 `approved`
- 发布节流：
  - `PUBLISH_MIN_INTERVAL_SECONDS`
  - `PUBLISH_DAILY_LIMIT`
  - `PUBLISH_WINDOW_START`
  - `PUBLISH_WINDOW_END`
- Web/API：
  - `POST /api/videos/<video_id>/approve`
  - `POST /api/videos/<video_id>/reject`
  - `/api/status` 返回当前发布模式和节流配置
- CLI：
  - `youtube-pipeline review <video_id> pending|approved|rejected`
- 测试覆盖：
  - manual 模式跳过自动发布
  - approved_auto 只发布 approved 草稿
  - full_auto 可发布 pending 有效草稿
  - 日发布上限
  - Web 真实发布必须 confirm

未完成：

- 草稿内容编辑。
- 发布日历/时间计划。

### 验收标准

- 用户可以不使用 CLI 完成查看、编辑、发布、重试、跳过。

## P7：失败分类、延迟重试和队列自愈

### 目标

让 worker 遇到临时失败时不会把队列卡死；同时把不可恢复失败明确标记，便于 Web 和 CLI 判断下一步操作。

### 任务拆解

1. 失败分类
   - `youtube_403`：不可重试
   - `youtube_unavailable`：不可重试
   - `login_required`：不可重试
   - `fallback_tid`：不可重试
   - `merge_failed`：不可重试
   - `publish_failed`：可重试
   - `llm_failed`：可重试
   - `network_error`：可重试
   - `download_incomplete`：可重试
   - `unknown`：不可重试

2. 延迟重试
   - `jobs.next_run_at` 保存下一次可执行时间。
   - `jobs.error_type` 保存结构化错误类型。
   - `get_pending_job` 自动跳过未来才可执行的 job。
   - 重试间隔使用指数退避，受 `JOB_RETRY_BASE_SECONDS` 和 `JOB_RETRY_MAX_SECONDS` 控制。

3. 队列自愈
   - download 可重试失败：视频状态回到 `selected`，job 保持 `pending`。
   - describe 可重试失败：视频状态回到 `downloaded`，job 保持 `pending`。
   - publish 可重试失败：视频状态回到 `ready_to_publish`，job 保持 `pending`。
   - 不可重试失败：视频和 job 均进入 `failed`。

4. Web 展示
   - 视频详情展示最近 job。
   - 展示 `attempts/max_attempts`。
   - 展示 `error_type`。
   - 展示 `next_run_at`。

### 当前状态

已完成：

- 新增 `app/error_policy.py`，集中维护错误分类。
- 新增 `app/job_retry.py`，集中处理失败后的状态回退、延迟重试和终态失败。
- `download_service`、`publish_service` 的 download/describe/publish 失败路径已接入统一处理。
- `jobs` 表已补充 `next_run_at` 和 `error_type`，旧数据库由 `init_schema()` 自动补列。
- `.env.example` 已新增 `JOB_RETRY_BASE_SECONDS` 和 `JOB_RETRY_MAX_SECONDS`。
- Web 详情已展示 job 错误类型、尝试次数和下次运行时间。
- 真实数据库已完成 schema 迁移验证。
- 单元测试覆盖 future `next_run_at` 跳过、可重试失败、不可重试 403 失败。

未完成：

- Web 上按 `error_type` 过滤失败项。
- 更细的 YouTube 限流、版权、地区限制分类。

### 验收标准

- 网络类下载失败不会进入永久 failed，而是按退避时间重新排队。
- YouTube 403 类错误直接进入 failed，不自动反复重试。
- `status` 和 Web 能看到错误类型和下一次执行时间。
- worker 后续轮次不会执行 `next_run_at` 未到的 pending job。

## P8：worker lock/lease 和运行态恢复

### 目标

让 worker 可以长期稳定运行，进程重启或异常退出后不会留下永久卡住的任务，并为后续多 worker 做基础。

### 任务拆解

1. job 领取
   - 使用 `locked_at` 和 `lock_owner` 标记任务归属。
   - 领取任务时只领取未锁定或锁超时的 pending job。
   - worker 写入稳定的 worker id。

2. lease 超时
   - 新增配置 `JOB_LEASE_SECONDS`。
   - 未超时的 job 不允许被其它 worker 领取。
   - 超时的 running/pending locked job 可被恢复。

3. 运行态恢复
   - 启动 worker 或执行 `worker-run` 前扫描卡住状态。
   - `running` job 超时后按 job_type 回到 pending。
   - 视频状态从 `downloading/describing/publishing` 回退到对应可执行状态。
   - 写入恢复事件，保留原错误信息。

4. CLI/Web 可见性
   - `status` 展示 locked/running/overdue job 数量。
   - Web 详情展示 lock owner、locked_at、是否超时。

### 当前状态

已完成：

- 新增 `JOB_LEASE_SECONDS`，控制 locked/running job 的 lease 超时时间。
- `Repository.claim_pending_job()`：领取 due pending job，写入 `locked_at` 和 `lock_owner`。
- `Repository.recover_stale_jobs()`：恢复过期 pending lock 和 running job。
- `worker-run/worker` 每轮第一步执行 `recover`。
- worker 调用 download/describe/publish 时传入 `worker_id`，服务层会先领取 job 再执行。
- succeeded/failed/cancelled/retry job 会释放 lock。
- `status` 增加 `job_lock_status`，Web 总览展示 running/locked 数。
- Web 视频详情展示 job 的 `lock_owner` 和 `locked_at`。
- Web 视频详情会根据 `JOB_LEASE_SECONDS` 标记 locked job 是否已超时。
- 新增独立 Jobs 管理区：
  - 新增 `GET /api/jobs`。
  - 支持按 `job_type`、`status`、`error_type` 筛选。
  - 支持 `limit` 和 `offset` 分页。
  - 页面展示 job id、job_type、status、error_type、attempts、错误/重试/锁信息。
  - 可从 job 记录进入对应视频详情。
- 单元测试覆盖：
  - job 领取后阻止第二个 worker 重复领取
  - stale running download job 恢复为 pending，视频回到 selected
  - download/describe/publish-next 尊重延迟重试
  - worker-run 增加 recover 步骤

未完成：

- 真正多进程 worker 的压力测试。

### 验收标准

- 正常领取的 job 不会被重复领取。
- lease 未超时不会被恢复。
- lease 超时后 worker 能恢复并继续执行。
- 进程中断后再次运行 worker 能把卡住状态恢复到队列。
- 单元测试覆盖 download/describe/publish 三类 job 的恢复路径。

## P9：Web 管理重构

### 目标

把当前验证型 Web 改成可长期使用的本地运营管理台。它仍然是内部工具，不做复杂权限系统和重视觉设计，但必须能高效管理发现、下载、文案、发布、失败处理。

详细功能设计见 `docs/youtube-pipeline-web-management-design.md`。

### 设计原则

- Web 不直接改数据库，所有操作走 service/repository。
- 页面围绕队列和状态管理，不做营销式首页。
- 先满足可控运营：筛选、查看、编辑、审核、重试、跳过、发布。
- 当前 `ThreadingHTTPServer` 可继续保留；如果页面复杂度明显上升，再迁移到更明确的后端结构。

### 任务拆解

1. 信息架构
   - 总览页：队列状态、今日发布、失败数、待审核数、worker 状态。
   - 视频列表页：按状态、来源、错误类型、草稿状态筛选。
   - 视频详情页：meta、媒体文件、草稿、jobs、events、发布记录。
   - 设置页：展示关键 env 配置的只读视图。

2. 草稿管理
   - 编辑 title。
   - 编辑 description。
   - 编辑 tags。
   - 编辑 tid。
   - 保存后可 approve/reject。
   - fallback tid 必须显著提示。

3. 队列操作
   - 单条 download/describe/publish dry-run/real publish。
   - 单条 retry/skip。
   - 批量 approve。
   - 批量 retry failed。
   - 操作必须有明确反馈和错误展示。

4. 失败管理
   - 按 `error_type` 筛选。
   - 显示 `next_run_at`。
   - 显示 attempts/max_attempts。
   - 支持不可重试失败的人工 retry。

5. Worker 管理
   - 展示当前 worker 配置。
   - 手动运行一轮。
   - 展示最近 worker events。
   - 展示 lease/lock 状态。

6. 配置管理
   - Web 查看和修改常用 `.env` 配置。
   - 配置按基础路径、YouTube API、下载、LLM、发布、worker/job 分组。
   - 敏感配置脱敏显示。
   - 修改配置必须校验并写审计事件。

7. 自动流程调度
   - 支持启用/暂停整条 pipeline。
   - 支持 interval 调度。
   - 支持 cron 调度设计。
   - 支持分别启用/禁用 discovery、download、describe、publish。

8. 存储管理
   - 展示下载目录占用。
   - 配置最大磁盘占用、保留天数、最小剩余空间。
   - 支持 cleanup dry-run。
   - 支持手动清理已发布/跳过/失败内容。

9. 手动添加任务
   - 支持单 URL 添加。
   - 支持批量 URL 添加。
   - 自动解析 video_id。
   - 已存在视频不重复插入，只提示当前状态。
   - 新任务进入统一队列。

10. 唯一性保护
    - Web 发布前检查成功发布记录。
    - 已发布视频禁用真实发布按钮。
    - `video_id + platform + account` 的成功发布唯一性不可绕过。
    - publish_records 默认只读，保留审计价值。

### 验收标准

- 不使用 CLI 也能完成单个视频从查看、草稿编辑、审核到发布预览。
- 能快速定位失败视频和失败原因。
- 能看到任务是否在等待延迟重试。
- 能在 Web 手动添加 YouTube URL 并进入统一队列。
- 能在 Web 修改常用配置，并对敏感配置脱敏。
- 能看到磁盘占用并执行清理预览。
- 已发布视频不能被误重复发布。
- 真实发布仍必须二次确认。
- 页面在移动端和桌面端都不出现文本重叠。

### 当前状态

P9.1 配置与开关已完成：

- 新增 `app/config_service.py`。
- 配置按 group 返回，覆盖 pipeline、publish、download、youtube、discovery、llm、jobs、paths、logging、web。
- 敏感配置脱敏显示：
  - `YOUTUBE_API_KEY`
  - `MINIMAX_ANTHROPIC_API_KEY`
- `PATCH /api/config` 支持白名单字段更新。
- 配置更新写回 `.env`。
- 配置更新写入 `events(config_updated)`。
- 配置更新后 Web server 重新加载 config。
- 新增流程开关：
  - `PIPELINE_ENABLED`
  - `WORKER_ENABLE_DOWNLOAD`
  - `WORKER_ENABLE_DESCRIBE`
  - `WORKER_CRON`
- worker-run 已遵守：
  - `PIPELINE_ENABLED=false` 时跳过 discovery/download/describe/publish。
  - `WORKER_ENABLE_DOWNLOAD=false` 时跳过 download。
  - `WORKER_ENABLE_DESCRIBE=false` 时跳过 describe。
- Web 当前页面新增最小配置面板，可编辑常用配置：
  - pipeline 开关
  - worker interval/cron
  - discovery/download/describe/publish 开关
  - proxy/retries
  - publish mode/limit/interval
- 单元测试覆盖：
  - 配置分组和敏感字段脱敏。
  - 合法更新写回 `.env` 并写 audit event。
  - 非法字段、非法值、masked sensitive value 拒绝保存。
  - worker 遵守 pipeline/download/describe 开关。

P9.1 未完成：

- 真正的 cron 调度执行器；当前只保存 `WORKER_CRON` 配置。
- 配置页最终交互设计；当前是最小可用面板。
- 运行中 worker 的热重载机制；当前 Web server 会重载自身 config，worker 进程下一轮是否读取取决于启动方式。

P9.2 队列管理已完成基础版：

- 前端已切换为 Vite + React + lucide-react。
- `web-dev` 现在同时启动 Python API 和 Vite dev server，Vite 负责前端 HMR。
- `web/dist` build 产物可由普通 `youtube-pipeline web` 托管。
- 新增 `add_video_url()` / `add_video_urls()`，统一处理手动 URL 入队。
- CLI `add-url` 已切换到同一套入队逻辑。
- 手动添加时规范化 source URL 为 `https://www.youtube.com/watch?v=<video_id>`。
- `video_id` 已存在时返回 `exists`，不重复创建视频和 download job。
- 新视频进入 `selected` 并创建 pending download job。
- `videos` 新增队列字段：
  - `priority`
  - `source_label`
- 手动添加 URL 支持设置 priority 和 source_label。
- discovery 入库会使用 source priority 和 source name。
- 队列查询和下载 fallback 会按 priority 升序处理。
- 新增 Web API：
  - `POST /api/videos/add-url`
  - `POST /api/videos/add-urls`
- Web 队列页新增批量 URL 输入框。
- Web 手动添加任务支持填写 priority 和 source_label。
- Web 队列页新增筛选：
  - `status`
  - `draft_status`
  - `error_type`
- 新增批量操作 API：
  - `POST /api/videos/batch`
- 批量操作当前支持：
  - `approve`
  - `reject`
  - `retry`
  - `skip`
- 批量操作逐条执行，单条失败不阻断整批，返回 success/error 明细。
- Web 队列页新增多选、全选、清空、批量通过、批量重试、批量跳过。
- Web 队列页新增批量拒绝。
- 单元测试覆盖：
  - 单 URL 入队。
  - 重复 URL 不重复建 job。
  - 批量 URL 部分失败。
  - Web 列表按 draft/error 筛选。
  - 批量操作部分失败。
  - 不支持的批量动作拒绝执行。
  - priority 排序。

P9.2 未完成：

- 更完整的批量操作，如批量 real publish 预览；真实发布仍不建议批量。
- 列表筛选目前是 Web 层基础实现，后续数据量变大时需要下沉到 repository SQL。

P9.3 草稿编辑和发布策略已完成基础版：

- 新增 `Repository.update_publish_draft()`，草稿更新统一走 repository/service，不直接在 Web 拼 SQL。
- 新增 `publish_service.update_publish_draft()`：
  - 校验标题不能为空。
  - 校验描述不能为空。
  - 校验 tid 必须在 `BILIBILI_TID_OPTIONS` 白名单内。
  - tags 复用发布侧规范化逻辑。
  - 保存后 `tid_source=manual`。
  - 保存后重置 review note/reviewed_at。
- 新增 Web API：
  - `PATCH /api/videos/<id>/draft`
- React 详情页支持编辑：
  - title
  - description
  - tags
  - tid
  - draft status
- 分区下拉从 `BILIBILI_TID_OPTIONS` 读取，不在前端硬编码。
- 保存草稿后刷新当前视频详情，真实发布仍走原有 publish 校验。
- 单元测试覆盖：
  - 草稿保存后标记 manual。
  - 草稿保存后重置审核信息。
  - 非白名单 tid 拒绝保存。
- 修正每日发布限制统计：
  - `publish_records.created_at` 和真实发布 `published_at` 按 UTC 存储。
  - 本地日开始时间会转换为 UTC 后再查询，避免本地 00:00 后漏计当天发布记录。

P9.3 未完成：

- 草稿历史版本。
- 更细的字段级校验，如标题长度、B 站标签数量上限提示。

P9.4 存储监控和清理已完成基础版：

- 新增存储配置：
  - `STORAGE_MAX_GB`
  - `STORAGE_WARN_GB`
  - `STORAGE_MIN_FREE_GB`
  - `STORAGE_RETENTION_DAYS`
  - `STORAGE_CLEANUP_ENABLED`
  - `STORAGE_CLEANUP_STATUSES`
- 新增 `app/storage.py`：
  - 统计 `OUTPUT_DIR` 目录占用。
  - 统计磁盘总量、已用、剩余。
  - 按视频状态聚合媒体文件占用。
  - 按状态和保留天数生成清理候选。
  - 支持 cleanup dry-run。
  - 支持确认后删除媒体文件。
- 清理策略：
  - 只删除 `OUTPUT_DIR` 内存在的媒体文件。
  - 默认候选状态为 `published,skipped,failed`。
  - 不删除 `videos/jobs/events/publish_records` 等数据库记录。
  - 删除后清空 `media_files` 中对应路径。
  - 写入 `storage_media_cleaned` 事件。
- worker 集成：
  - `STORAGE_CLEANUP_ENABLED=false` 时 worker 记录 skipped。
  - `STORAGE_CLEANUP_ENABLED=true` 时 worker 在 discovery/download/describe/publish 后执行 cleanup。
  - `PIPELINE_ENABLED=false` 时 cleanup 同样跳过。
- 新增 Web API：
  - `GET /api/storage`
  - `POST /api/storage/cleanup`
  - `POST /api/videos/<id>/cleanup-media`
- 真实清理要求 `confirm=true`。
- 单视频媒体清理：
  - 默认只允许清理 `STORAGE_CLEANUP_STATUSES` 中的状态。
  - 可通过 service 层 `force=True` 覆盖，但 Web 默认不暴露 force。
  - 保留数据库主记录和发布记录。
  - 清理后清空对应 `media_files` 路径。
- React 页面新增存储面板：
  - 下载目录占用。
  - 磁盘剩余。
  - 清理候选数量。
  - 可释放空间。
  - 按状态占用。
  - 清理候选预览。
  - 清理预览/执行清理按钮。
- React 视频详情页新增单视频“清理媒体”按钮。
- 单元测试覆盖：
  - 存储统计和清理候选。
  - dry-run 不删除文件。
  - 真实清理删除文件并清空媒体路径。
  - 单视频 dry-run。
  - 单视频非 eligible 状态默认阻断。
  - worker cleanup 开关。

P9.4 未完成：

- 清理策略更细分，如只清理已发布且发布超过 N 天。
- 大数据量场景下的 SQL 聚合优化。

P9.5 发现源管理已完成基础版：

- 新增 `app/discovery/source_config.py`。
- 发现源仍以 `DISCOVERY_SOURCES_JSON` 持久化，不新增表。
- 新增发现源校验和规范化：
  - 支持 `search`。
  - 支持 `trending`。
  - 支持 `channel_uploads`。
  - `enabled` 默认为 `true`。
  - `priority` 默认为 `100`。
  - 支持 source 级过滤覆盖：
    - `min_duration_seconds`
    - `max_duration_seconds`
    - `min_view_count`
    - `title_blocklist`
    - `channel_allowlist`
    - `channel_blocklist`
    - `category_allowlist`
    - `category_blocklist`
  - `max_results` 限制为 1-50。
  - `search` 必须有 keyword。
  - `channel_uploads` 必须有 channel_id 或 handle。
  - handle 自动补齐 `@`。
- discovery 执行时会跳过 `enabled=false` 的 source，并按 `priority` 升序执行。
- source 级过滤只覆盖已配置字段，未配置字段继续使用全局 discovery filter。
- 新增 Web API：
  - `GET /api/discovery/sources`
  - `POST /api/discovery/sources`
  - `PATCH /api/discovery/sources`
  - `PATCH /api/discovery/sources/<index>`
  - `DELETE /api/discovery/sources/<index>`
  - `POST /api/discovery/sources/<index>` with `{"action":"preview"}`
- 发现源变更复用 `config_service.update_config()` 写回 `.env`，并写入配置审计事件。
- 单个 source preview 复用发现过滤逻辑，但不写 events、不入库。
- Web 页面新增发现源管理面板：
  - 列表查看现有 source。
  - 新增 source。
  - 编辑 source。
  - 删除 source。
  - 单 source dry-run 预览。
  - 启用/禁用 source。
  - 修改 source priority。
  - 配置 source 级过滤覆盖。
  - 表单按 source type 显示不同字段。
- 单元测试覆盖：
  - 类型字段校验。
  - 列表 index。
  - 新增、更新、删除写回 `.env`。
  - 单 source preview 不入库。
  - disabled source 不参与发现。
  - source 按 priority 排序。
  - source 级过滤覆盖全局过滤。

P9.5 未完成：

- source 权重。
- preview 结果分页和更完整的候选详情展示。

P9.6 Web 页面重构已完成基础版：

- React 页面已按管理域拆分：
  - 总览
  - 队列
  - Worker
  - 详情
  - 配置
  - 存储
  - 发现源
- 总览页新增运行态首屏信息：
  - 自动发布状态
  - 活跃队列
  - 待发布数量
  - job lock/running 数
  - 下载目录占用
  - 失败视频数量
- 总览页新增最近失败视频入口：
  - 展示失败视频标题、video_id、last_error。
  - 可一键筛选失败队列。
  - 可直接点选失败视频进入详情。
- 总览页新增最近事件：
  - 展示 event_type、module、created_at、message。
  - 用于快速判断 worker 最近执行了哪些动作。
- 详情页草稿面板已优化：
  - 审核状态、发布分区、分区来源前置展示。
  - `fallback` 分区来源有明确阻断提示。
  - 当前标签独立展示。
- 详情页媒体预览已优化：
  - 有合并视频时直接内嵌视频播放器。
  - 无合并视频但有海报时展示海报。
  - 展示 merged/video/audio/poster/meta 是否已生成。
  - 对已生成媒体提供直接打开入口。
- 页面已补充响应式布局，避免移动端摘要面板挤压。
- 新增 Worker 管理区：
  - 展示 pipeline 总开关。
  - 展示 discovery/download/describe/publish 阶段开关。
  - 展示 publish dry-run 状态。
  - 展示 interval、cron、job lease、发现队列阈值、限定发现源。
  - 展示 running/locked job 数。
  - 展示 job_type/status 分布。
  - 展示最近 worker 事件。
  - 可从该区手动运行一轮 worker。
- `/api/status.settings` 已补充 Worker 管理区需要的运行参数。
- 新增事件管理区：
  - 新增 `GET /api/events`。
  - 支持按 `module` 筛选。
  - 支持 `limit` 和 `offset` 分页。
  - 页面可切换模块、调整页大小、上一页/下一页。
  - 事件列表展示 event_type、module、created_at、message、video_id、job_id。
- `Repository.list_events()` 已支持 module/offset 参数。
- `events` 表已补充 `module,id` 查询索引。
- 新增失败管理区：
  - 新增 `GET /api/failures`。
  - 支持按 `job_type` 筛选。
  - 支持按 `error_type` 筛选。
  - 支持 `limit` 和 `offset` 分页。
  - 页面展示失败视频、最新失败 job、错误类型、尝试次数、错误信息、下次重试时间。
  - 可从失败记录直接选择视频进入详情。
  - 可从失败记录直接触发重试。
- `Repository.list_failures()` 已支持失败记录专用查询，避免 Web 继续用视频列表做临时过滤。

P9.6 未完成：

- 暂无。后续可继续做 Web 交互细节优化和生产运行观测增强。

### 风险点

- 不要在 P9 过早引入复杂前端工程。
- 不要让 Web 绕过状态机。
- Web 重构应在 P8 后做，否则 worker 状态展示会缺关键字段。

# youtube-pipeline Web 管理台功能设计

本文档用于指导 P9 Web 管理重构。目标不是做一个漂亮页面，而是做一个能长期运行、能监控全流程、能安全操作队列的本地运营后台。

## 1. 设计目标

Web 管理台需要覆盖完整链路：

```text
发现配置 -> 自动发现 -> 手动加任务 -> 下载 -> 文案生成 -> 审核 -> 发布 -> 失败处理 -> 存储清理
```

核心目标：

- 全流程可观测：知道系统是否启用、当前在做什么、哪里失败、下一步什么时候执行。
- 全流程可控制：能启动/暂停自动流程，能手动触发每个阶段，能人工修正数据。
- 配置可管理：常用 `.env` 配置可以在 Web 上查看和修改。
- 数据可治理：发现、下载、发布数据支持 CRUD 和状态流转，不靠直接改数据库。
- 安全发布：同一视频、同一平台、同一账号不能重复发布。
- 存储可控：防止下载内容无限增长撑爆磁盘。

## 2. 功能模块

### 2.1 总览 Dashboard

展示系统当前状态：

- 自动流程是否启用。
- worker 是否运行。
- 当前调度策略。
- active queue 数量。
- 待下载、下载中、待文案、待审核、待发布、发布中、已发布、失败数量。
- running/locked job 数量。
- 下一个计划执行时间。
- 今日已发布数量、今日发布上限。
- 磁盘占用、下载目录大小、剩余空间。
- 最近错误。
- 最近 worker run 结果。

建议总览页提供操作：

- 启用/暂停自动流程。
- 立即运行一轮 worker。
- 立即执行 discovery。
- 立即执行下载队列。
- 立即执行发布队列，真实发布仍必须二次确认。

### 2.2 自动流程与调度管理

用户提到的 `corn` 应理解为 `cron`。当前系统是 `WORKER_INTERVAL_SECONDS` 轮询，后续 Web 应支持两类调度方式：

- interval：每 N 秒/分钟运行一轮。
- cron：按 cron 表达式运行，例如每天 09:00-23:00 每 30 分钟。

建议配置：

- `PIPELINE_ENABLED`：是否启用整条自动流程。
- `WORKER_INTERVAL_SECONDS`：轮询间隔。
- `WORKER_CRON`：cron 表达式，空值则使用 interval。
- `WORKER_ENABLE_DISCOVERY`：是否自动发现。
- `WORKER_ENABLE_DOWNLOAD`：是否自动下载。
- `WORKER_ENABLE_DESCRIBE`：是否自动生成文案。
- `WORKER_ENABLE_PUBLISH`：是否自动发布。
- `WORKER_PUBLISH_DRY_RUN`：自动发布是否只 dry-run。

设计要求：

- Web 可以修改这些配置。
- 修改后要能看到“待生效/已生效”状态。
- 如果后续作为长期服务运行，配置变更需要触发 worker reload 或在下一轮自动读取。
- 不允许只改前端状态，最终配置必须持久化。

### 2.3 配置管理

`.env` 配置最好能在 Web 管理，但必须分级，不是所有配置都适合直接裸改。

建议分组：

1. 基础路径
   - `OUTPUT_DIR`
   - `DB_PATH`
   - `TMP_DIR`
   - `LOG_LEVEL`
   - `LOG_FILE`

2. YouTube API
   - `YOUTUBE_API_KEY`
   - `YOUTUBE_API_BASE`
   - discovery sources/filter 相关配置

3. 下载配置
   - `VIDEO_FORMAT`
   - `AUDIO_FORMAT`
   - `PROXY`
   - `COOKIE_FILE`
   - `SOCKET_TIMEOUT`
   - `RETRIES`
   - `FRAGMENT_RETRIES`
   - `RETRY_BACKOFF_FACTOR`

4. LLM 配置
   - MiniMax endpoint/model/key
   - request timeout
   - max tokens

5. 发布配置
   - `BILIBILI_ACCOUNT`
   - `BILIBILI_TID_OPTIONS`
   - `PUBLISH_MODE`
   - `PUBLISH_MIN_INTERVAL_SECONDS`
   - `PUBLISH_DAILY_LIMIT`
   - `PUBLISH_WINDOW_START`
   - `PUBLISH_WINDOW_END`

6. worker/job 配置
   - `JOB_LEASE_SECONDS`
   - `JOB_RETRY_BASE_SECONDS`
   - `JOB_RETRY_MAX_SECONDS`

安全要求：

- API key、LLM key、cookie 路径等敏感配置默认脱敏显示。
- 修改敏感配置需要显式输入新值，不回显旧值。
- 配置保存前做类型校验和范围校验。
- 配置修改要写 `events` 或单独的 audit log。
- Web 不应把 `.env` 当普通文本随意编辑；应通过结构化配置服务读写。

### 2.4 磁盘占用与清理策略

需要防止下载内容越来越大。

建议新增配置：

- `STORAGE_MAX_BYTES` 或 `STORAGE_MAX_GB`
- `STORAGE_WARN_BYTES` 或 `STORAGE_WARN_GB`
- `STORAGE_MIN_FREE_BYTES`
- `STORAGE_RETENTION_DAYS`
- `STORAGE_CLEANUP_ENABLED`
- `STORAGE_CLEANUP_POLICY`

清理策略建议：

- 默认不删除未发布内容。
- 已发布内容优先清理。
- skipped/failed 且超过保留时间的内容可清理。
- 保留 `videos/jobs/events/publish_records` 等数据库记录。
- 删除媒体文件前写入事件。
- `media_files` 中被删除的路径需要标记为 missing/cleaned，而不是让页面误以为文件还存在。

Web 功能：

- 展示当前下载目录大小。
- 展示各状态占用空间。
- 展示最大容量和剩余空间。
- 手动执行清理预览 dry-run。
- 手动执行清理。
- 支持单个视频删除媒体文件，但不删除发布记录。

### 2.5 发现数据管理

发现不应该只等同于搜索，应支持多个 source：

- search
- trending
- channel_uploads
- 手动添加 URL

Web 功能：

- discovery source CRUD：
  - 新增搜索关键词。
  - 新增热门地区/分类。
  - 新增频道。
  - 启用/禁用 source。
  - 设置每个 source 的 max_results、权重、过滤规则。
- 发现结果列表：
  - accepted。
  - rejected。
  - rejected reason。
  - score。
  - source 信息。
- 手动触发发现：
  - dry-run。
  - 入库。
  - 指定 source。

后续建议增加 discovery run 表，保存每次发现批次，而不是只依赖 events。

### 2.6 手动添加任务

这是必须做的功能。

使用场景：

- 用户手动找到一个 YouTube 链接。
- 在 Web 输入链接。
- 系统解析 video_id。
- 获取基础 meta。
- 入库为 `selected`。
- 创建 download job。
- 后续仍走统一队列。

要求：

- 支持单条 URL。
- 支持批量 URL，一行一个。
- 添加前检查 `video_id` 是否已存在。
- 已存在时提示当前状态，不重复创建视频。
- 可选择是否强制创建新的 retry job，但不能破坏唯一性。
- 可选择初始状态：默认 `selected`。
- 可设置备注、来源标签、优先级，后续如果需要。

### 2.7 下载任务管理

Web 需要能管理下载参数和下载队列。

功能：

- 查看待下载、下载中、下载失败、已下载列表。
- 查看每个下载 job：
  - attempts/max_attempts。
  - error_type。
  - next_run_at。
  - locked_at/lock_owner。
  - 文件路径。
- 操作：
  - 立即下载。
  - 重试。
  - 跳过。
  - 强制重新下载。
  - 删除媒体文件后重新下载。

下载配置：

- 代理。
- cookie 文件。
- yt-dlp 格式。
- socket timeout。
- retries。
- fragment retries。
- backoff。

约束：

- 下载中任务不能被普通操作直接删除。
- force 操作必须二次确认。
- 下载配置修改只影响新任务或下一次重试，不应破坏正在运行的任务。

### 2.8 文案与发布草稿管理

功能：

- 查看 LLM 生成的标题、描述、tags、tid。
- 编辑标题。
- 编辑描述。
- 编辑 tags。
- 编辑 tid。
- 查看 tid 选择理由。
- 查看原始视频信息和原始 YouTube 链接。
- 保存草稿。
- approve/reject。
- 重新生成文案。

要求：

- `tid_source=fallback` 必须显著提示。
- 手动修改 tid 后记录 `tid_source=manual`。
- 草稿每次修改需要写 events。
- 发布前必须展示最终 payload。

### 2.9 发布策略管理

用户需要自行更改自动/手动发布策略。

配置：

- `PUBLISH_MODE`
  - `manual`
  - `approved_auto`
  - `full_auto`
- `PUBLISH_DAILY_LIMIT`
- `PUBLISH_MIN_INTERVAL_SECONDS`
- `PUBLISH_WINDOW_START`
- `PUBLISH_WINDOW_END`
- `WORKER_ENABLE_PUBLISH`
- `WORKER_PUBLISH_DRY_RUN`

Web 功能：

- 修改发布模式。
- 修改每日上限。
- 修改时间窗口。
- 修改发布间隔。
- 查看今日发布记录。
- 查看下次允许发布时间。
- 手动发布单个视频。
- 自动发布队列预览。

安全要求：

- 真实发布必须二次确认。
- `full_auto` 开启时必须显示风险提示。
- fallback tid 不允许真实发布。
- 非白名单 tid 不允许真实发布。

### 2.10 数据 CRUD 管理

需要对发现、下载、发布数据进行 CRUD，但不能变成“直接改 DB”的后台。

建议按对象拆：

1. videos
   - 查看。
   - 修改基础信息：标题、频道、分类、备注。
   - 修改状态只允许通过受控动作：retry、skip、restore。
   - 删除视频：默认软删除或 skipped，不建议物理删除发布记录。

2. jobs
   - 查看。
   - 取消 pending job。
   - 重试 failed job。
   - 恢复 stale running job。
   - 不建议随意编辑 attempts。

3. media_files
   - 查看文件是否存在。
   - 删除本地媒体文件。
   - 重新生成/重新下载。

4. publish_drafts
   - 查看。
   - 编辑。
   - approve/reject。

5. publish_records
   - 查看。
   - 不建议编辑。
   - 不建议删除。
   - 如必须修正，应走 audit 操作。

6. events
   - 只读。
   - 用于审计。

### 2.11 唯一性与防重复发布

这是强约束。

现有约束：

- `videos.video_id` 是主键。
- `publish_records` 对成功发布记录有唯一索引：
  - `video_id + platform + account`
  - `status='published'`

Web 需要继续强化：

- 手动添加任务时，video_id 已存在则不重复插入。
- 发布前检查是否已有成功发布记录。
- 自动发布前检查是否已有成功发布记录。
- 真实发布按钮如果已发布则禁用。
- `--force` 类能力不应在 Web 常规入口暴露；如要暴露必须二次确认并写 audit event。

建议补充：

- 对 source_url 做规范化，避免同一视频不同 URL 重复入库。
- publish dry-run 不写成功发布记录。
- publish_records 不允许随便删除，否则唯一性审计会被破坏。

## 3. 页面结构建议

### 3.1 顶部状态栏

- 自动流程开关。
- 当前发布模式。
- worker 状态。
- 磁盘占用。
- 最近错误。

### 3.2 左侧导航

- 总览
- 视频队列
- 发现源
- 下载任务
- 发布草稿
- 发布记录
- Jobs
- 配置
- 存储清理
- Events

### 3.3 视频队列页

筛选：

- status
- source type
- draft status
- error_type
- category
- channel
- published/not published

操作：

- 手动添加 URL。
- 批量 approve。
- 批量 retry。
- 批量 skip。

### 3.4 视频详情页

区域：

- 基础 meta。
- 原视频链接。
- 媒体文件。
- 播放预览。
- 草稿编辑。
- job 状态。
- events。
- publish records。

## 4. 后端 API 建议

第一批 API：

```text
GET  /api/status
GET  /api/config
PATCH /api/config

GET  /api/videos
POST /api/videos/add-url
POST /api/videos/add-urls
GET  /api/videos/<id>
PATCH /api/videos/<id>
POST /api/videos/<id>/retry
POST /api/videos/<id>/skip
POST /api/videos/<id>/download
POST /api/videos/<id>/describe

GET  /api/videos/<id>/draft
PATCH /api/videos/<id>/draft
POST /api/videos/<id>/approve
POST /api/videos/<id>/reject
POST /api/videos/<id>/publish-dry-run
POST /api/videos/<id>/publish

GET  /api/jobs
POST /api/jobs/<id>/cancel
POST /api/jobs/<id>/retry
POST /api/jobs/recover-stale

GET  /api/discovery/sources
POST /api/discovery/sources
PATCH /api/discovery/sources/<id>
DELETE /api/discovery/sources/<id>
POST /api/discover

GET  /api/storage
POST /api/storage/cleanup-preview
POST /api/storage/cleanup

GET  /api/events
```

## 5. 实施优先级

### P9.1 配置与开关

- `PIPELINE_ENABLED`
- interval/cron 配置
- publish mode 配置
- download retries/proxy 配置
- 配置读写 API
- 配置脱敏和校验

### P9.2 手动添加任务与队列管理

- Web 添加单个/批量 URL。
- 视频列表筛选。
- retry/skip/download/describe 操作整理。

### P9.3 草稿编辑和发布策略

- draft PATCH。
- tid 手动修改。
- approve/reject。
- publish dry-run/real publish。
- 防重复发布提示。

### P9.4 存储监控和清理

- 存储统计。
- 清理策略配置。
- cleanup dry-run。
- cleanup 执行。

### P9.5 发现源管理

- discovery source CRUD。
- dry-run preview。
- accepted/rejected 展示。

### P9.6 Web 页面重构

- 页面布局重构。
- 列表和详情分区。
- 操作反馈。
- 移动端适配。

## 6. 需要注意的问题

- 配置管理不能只改 `.env` 文件而不考虑运行中 worker 是否重新加载。
- 数据 CRUD 必须尊重状态机，不能让 Web 直接把任意状态改成任意状态。
- 发布记录必须保留审计价值，不能为了“重新发布”随便删除。
- 磁盘清理不能删除未发布内容，除非用户明确确认。
- cron 表达式需要校验，错误 cron 不能保存。
- 全自动发布必须默认关闭，至少第一版仍以 `manual` 或 `approved_auto` 为安全默认值。

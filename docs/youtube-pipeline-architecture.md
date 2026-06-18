# youtube-pipeline 架构设计与开发规范

本文档定义后续 `youtube-pipeline` 的主线架构、模块边界、持久化规范和实施方向。

## 1. 架构目标

当前项目已经跑通单视频链路：

```text
YouTube URL
  -> 获取元数据
  -> 下载 video/audio/poster
  -> ffmpeg 合并
  -> LLM 生成中文发布信息
  -> LLM 选择 B 站 tid
  -> 发布到 B 站
```

下一阶段目标是将单视频脚本升级为可长期运行的本地流水线：

```text
自动搜索/发现
  -> 自动过滤和去重
  -> 自动下载
  -> 自动生成发布信息
  -> 自动发布
  -> Web 可视化管理
```

核心原则：

- 四个业务模块解耦：搜索发现、下载、发布、Web。
- SQLite 统一接管数据和状态。
- 文件系统只保存配置、日志、数据库和媒体文件。
- Web 不直接做业务逻辑，只调用 service。
- 所有状态变化和错误都必须可追踪、可恢复。

## 2. 模块划分

推荐目录结构：

```text
youtube-pipeline/
  app/
    core/
      config.py
      db.py
      models.py
      repository.py
      status.py
      events.py
      locks.py

    discovery/
      service.py
      youtube_api.py
      filters.py
      scoring.py

    downloader/
      service.py
      ytdlp.py
      merger.py
      files.py

    publisher/
      service.py
      ai_describe.py
      tid_selector.py
      bilibili.py

    web/
      api.py
      schemas.py
      static/
```

### 2.1 core

共享基础层，禁止混入具体业务流程。

职责：

- 配置加载。
- SQLite 连接和 schema 初始化。
- Repository。
- 状态机。
- 事件记录。
- 锁和任务租约。
- 通用模型。

约束：

- 其它模块通过 `core.repository` 读写数据库。
- 状态迁移必须经过统一函数。
- 任何错误都写入 `events`。

### 2.2 discovery

搜索和发现模块。

职责：

- YouTube API 搜索。
- yt-dlp 搜索备用。
- 候选视频入库。
- 根据规则过滤。
- 记录过滤原因。
- 选择待下载视频。

输出：

```text
videos.status = discovered / selected / skipped
```

### 2.3 downloader

下载模块。

职责：

- 获取 yt-dlp meta。
- 下载视频流。
- 下载音频流。
- 下载封面。
- ffmpeg 合并。
- 原子替换产物。
- 记录下载进度和错误。

输出：

```text
videos.status = downloaded / failed
media_files 写入文件路径
video_metadata 写入原始元数据
```

### 2.4 publisher

发布模块。

职责：

- LLM 生成中文标题、描述、标签。
- LLM 选择 B 站 tid。
- 校验 tid 白名单。
- 生成发布草稿。
- 调用 B 站发布能力。
- 防重复发布。
- 记录发布结果。

输出：

```text
publish_drafts
publish_records
videos.status = ready_to_publish / publishing / published / failed
```

### 2.5 web

Web 可视化模块。

职责：

- 视频队列展示。
- 状态筛选。
- 视频详情。
- 元数据查看。
- 下载产物预览。
- 发布草稿查看和编辑。
- tid 选择理由展示和人工覆盖。
- 手动下载、发布、跳过、重试。
- 错误日志查看。

约束：

- Web 不直接调用 yt-dlp、ffmpeg、biliup。
- Web 只调用 service 或写入任务请求。

## 3. 持久化规范

后续持久化内容只分四类：

```text
1. 配置文件
2. 日志文件
3. 数据库文件
4. 下载/生成的媒体内容
```

推荐目录：

```text
youtube-pipeline/
  .env
  .env.example

  runtime/
    data/
      pipeline.db

    logs/
      youtube-pipeline.log

    downloads/
      <video_id>/
        meta.json
        video.mp4
        audio.m4a
        poster.jpg
        <video_id>_merge.mp4

    tmp/
      <job_id>/
```

### 3.1 配置文件

- `.env`：本地私有配置，不提交 git。
- `.env.example`：配置模板，提交 git。

所有配置必须通过 `core.config` 读取。

### 3.2 日志文件

- 默认位置：`runtime/logs/youtube-pipeline.log`
- 日志只记录运行过程和排错信息。
- 业务状态不能只存在日志里，必须写数据库。

### 3.3 数据库文件

- 默认位置：`runtime/data/pipeline.db`
- SQLite 是唯一业务状态来源。
- 所有视频、任务、发布、错误、过滤原因都必须入库。

禁止新增：

```text
publish_state.json
task_state.json
candidates_cache.json
*.lock 状态文件
散落的 result.json
```

如果需要缓存、任务锁、状态标记，都写 SQLite。

### 3.4 下载和生成内容

媒体文件保存到：

```text
runtime/downloads/<video_id>/
```

要求：

- 文件路径必须写入 `media_files`。
- `meta.json` 可以作为调试归档，但数据库必须保存完整 meta 或关键字段。
- 下载和合并必须使用临时文件，成功后原子替换。
- 失败时不能破坏已有成功产物。

## 4. 数据库设计草案

第一版建议表：

```text
videos
video_metadata
media_files
publish_drafts
publish_records
jobs
events
```

### 4.1 videos

核心视频表。

建议字段：

```text
id
video_id
source_url
title
channel
duration
view_count
category
status
discovered_at
updated_at
last_error
```

`video_id` 必须唯一。

### 4.2 video_metadata

保存原始和补充元数据。

```text
video_id
ytdlp_meta_json
youtube_api_meta_json
created_at
updated_at
```

### 4.3 media_files

保存下载产物路径。

```text
video_id
meta_path
video_path
audio_path
poster_path
merged_path
created_at
updated_at
```

### 4.4 publish_drafts

发布草稿。

```text
video_id
platform
title
description
tags_json
tid
tid_label
tid_reason
tid_source
llm_raw_output
status
created_at
updated_at
```

### 4.5 publish_records

发布记录，负责防重复发布。

```text
video_id
platform
account
external_id
status
published_at
error
created_at
updated_at
```

同一个 `video_id + platform + account` 默认只能成功发布一次。

### 4.6 jobs

任务表。

```text
id
video_id
job_type
status
attempts
max_attempts
locked_at
lock_owner
started_at
finished_at
error
payload_json
created_at
updated_at
```

`job_type` 示例：

```text
discover
download
describe
publish
cleanup
```

### 4.7 events

事件日志表。

```text
id
video_id
job_id
module
event_type
message
payload_json
created_at
```

所有状态迁移和错误都写入 events。

## 5. 状态机

视频生命周期建议：

```text
discovered
  -> selected
  -> downloading
  -> downloaded
  -> describing
  -> ready_to_publish
  -> publishing
  -> published
```

异常状态：

```text
failed
skipped
```

要求：

- 状态迁移必须统一封装。
- 失败必须记录 `last_error` 和 `events`。
- 已发布视频默认不能重复发布。
- 重试必须增加 attempts。

## 6. 模块协作方式

推荐数据流：

```text
discovery worker
  -> videos(discovered)

filter/selection
  -> videos(selected/skipped)

download worker
  -> selected -> downloading -> downloaded / failed

publisher worker
  -> downloaded -> describing -> ready_to_publish -> publishing -> published / failed

web
  -> 读取 DB
  -> 写入操作请求或调用 service
```

模块之间禁止直接依赖内部实现。

允许：

```text
discovery.service -> core.repository
downloader.service -> core.repository
publisher.service -> core.repository
web.api -> service
```

避免：

```text
web.api -> yt-dlp
web.api -> biliup
discovery -> downloader 内部函数
downloader -> publisher 内部函数
```

## 7. LLM 使用规范

LLM 当前承担两个任务：

1. 生成中文发布信息。
2. 选择 B 站 tid。

要求：

- LLM 原始输出必须保存。
- 规范化后的标题、描述、标签、tid 必须保存。
- tid 必须在白名单内。
- 真实发布不能在 tid 选择失败后静默回退默认 tid。
- 人工 `--tid` 或 Web 覆盖需要记录 `tid_source=manual`。
- 选择 tid 的输入应包含：
  - yt-dlp categories
  - yt-dlp tags
  - YouTube API categoryId
  - YouTube API topicCategories
  - channel/uploader
  - description
  - title

## 8. Worker 运行规范

后续 worker 可以先做单进程循环。

要求：

- 每次只领取可执行任务。
- 使用 DB lock 防止重复执行。
- 每个任务有最大重试次数。
- 下载和发布之间支持间隔。
- 单个任务失败不能中断整个 worker。
- 进程重启后可恢复未完成任务。

## 9. Web 第一版范围

Web 第一版不追求复杂功能，优先可控和可视化。

必须包含：

- 视频列表。
- 状态过滤。
- 视频详情。
- meta 查看。
- 下载文件路径查看。
- 发布草稿查看。
- 标题/描述/标签编辑。
- tid 选择理由查看。
- tid 手动覆盖。
- 发布、重试、跳过。
- 错误事件查看。

## 10. 实施顺序

第一批：基础状态化

1. 新建 `core/`。
2. 建 SQLite schema。
3. 建 repository。
4. 把当前单视频流程改为写 DB。
5. 增加重复发布保护。
6. 修下载/合并原子替换。
7. tid 选择 fail-closed。

第二批：队列和 worker

1. jobs 表。
2. download worker。
3. publish worker。
4. retry/skip。
5. 错误恢复。

第三批：自动发现

1. YouTube API search。
2. 发现结果入库。
3. 过滤规则。
4. 去重和跳过策略。

第四批：Web

1. Web API。
2. 视频列表。
3. 视频详情。
4. 发布草稿编辑。
5. 操作按钮和事件日志。

第五批：运维增强

1. 日志轮转。
2. 运行指标。
3. 清理策略。
4. 多平台发布扩展。

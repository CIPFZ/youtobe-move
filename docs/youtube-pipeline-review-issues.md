# youtube-pipeline Review Issues

本文记录当前单视频链路跑通后发现的问题。后续做自动发现、循环下载、自动发布、Web 可视化、存储和去重时，需要把这些问题纳入任务拆解一起解决。

## 当前阶段

已完成单视频流程：

```text
YouTube URL
  -> 获取 meta.json
  -> 下载 video/audio/poster
  -> ffmpeg 合并
  -> MiniMax-M3 生成中文标题/描述/标签
  -> LLM 选择 B 站 tid
  -> 复用 social-auto-upload 发布到 B 站
```

下一阶段目标：

```text
自动发现
  -> 自动过滤已处理内容
  -> 自动下载
  -> 自动生成发布信息
  -> 自动发布
  -> 存储状态和错误
  -> Web 界面可视化管理
```

## 必须纳入后续任务的问题

### 1. 下载和合并不能破坏已有成功产物

当前问题：

- 重新下载时会先删除已有 `video.*` / `audio.*`
- 重新合并时会先删除已有 `<video_id>_merge.mp4`
- 如果新下载或 ffmpeg 失败，已有成功产物会丢失

后续要求：

- 下载到临时文件，成功后原子替换
- 合并到临时文件，成功后原子替换
- 失败时保留旧产物和错误状态

### 2. LLM 选择 tid 不能静默错误发布

当前问题：

- LLM tid 选择失败会回退默认 `BILIBILI_TID`
- 真实发布时可能发错分区或触发 B 站 `21150`

后续要求：

- dry-run 可以回退
- 真实发布应要求 `source=llm` 或人工显式覆盖
- 非白名单 tid 必须阻止发布
- 记录 tid 选择理由和输入依据

### 3. tid 选择需要结合 YouTube API 强分类字段

当前问题：

- tid 选择主要使用 yt-dlp meta
- 还没有把 YouTube API 的 `snippet.categoryId` / `topicDetails.topicCategories` 纳入统一选择输入

后续要求：

- 自动发现和入库时保存 yt-dlp meta
- 如配置了 YouTube API key，补充保存 YouTube API meta
- LLM 分区选择输入包含：
  - yt-dlp `categories`
  - yt-dlp `tags`
  - YouTube API `categoryId`
  - YouTube API `topicCategories`
  - channel/uploader
  - description
  - title 仅兜底

### 4. 配置和路径需要脱离当前工作目录

当前问题：

- CLI 依赖在 `youtube-pipeline/` 目录下运行
- `.env`、`OUTPUT_DIR`、`LOG_FILE` 等相对路径容易受当前 shell 目录影响

后续要求：

- 支持 `--env-file`
- 默认按项目目录定位 `.env`
- 相对路径统一解析到 `.env` 所在目录
- Web 服务和定时任务必须使用同一套配置加载逻辑

### 5. LLM 文案解析需要更稳

当前问题：

- 当前三行格式解析简单可控，但如果 LLM 把描述换行，后续行可能丢失
- 已经出现过链接被放在描述开头、URL 冒号被截断、残留来源标签等问题

后续要求：

- 文案生成结果保存原始 LLM 输出和规范化后的输出
- 增强解析：
  - 支持描述跨行
  - 支持 JSON 或固定字段两种模式之一，必须有 schema 校验
  - 链接统一只在末尾保留一条
- 发布前可在 Web 界面预览和编辑标题/描述/标签

### 6. 需要发布状态存储和重复发布保护

当前问题：

- 单步 CLI 不记录 video_id 是否已经发布
- 重复执行可能重复投稿

后续要求：

- 引入 SQLite 或同等持久化存储
- 至少记录：
  - video_id
  - source_url
  - title
  - channel
  - discovered_at
  - download_status
  - publish_status
  - bilibili_tid
  - tid_selection_source
  - publish_account
  - publish_attempts
  - published_at
  - error
- 默认阻止重复发布
- 需要 `--force` 或 Web 界面确认才能重复发布

### 7. 自动循环需要任务状态机

当前问题：

- 现在只有一次性 CLI
- 失败后没有统一重试、跳过、恢复机制

后续要求：

定义视频生命周期状态，例如：

```text
discovered
  -> selected
  -> downloading
  -> downloaded
  -> describing
  -> ready_to_publish
  -> publishing
  -> published
  -> failed
  -> skipped
```

要求：

- 每个阶段可重试
- 每个阶段有错误记录
- 进程重启后能恢复未完成任务
- 下载和发布之间要有节流间隔
- 发布失败不能影响后续任务继续运行

### 8. 自动发现需要过滤和去重

当前问题：

- 还没有稳定的发现队列
- 已下载、已发布、已跳过内容没有统一过滤

后续要求：

- 发现时按 `video_id` 去重
- 已发布和已跳过默认不再进入下载队列
- 支持过滤：
  - 时长范围
  - 观看量范围
  - 频道白名单/黑名单
  - 标题关键词黑名单
  - 分类范围
  - 发布时间范围
- 保存每次发现输入、结果和过滤原因

### 9. Web 可视化必须覆盖关键人工决策点

后续 Web 界面至少需要：

- 视频列表
- 状态过滤
- 下载产物预览
- meta 查看
- LLM 标题/描述/标签预览和编辑
- LLM tid 选择结果和理由
- 手动修改 tid
- 手动发布/重试/跳过
- 错误日志查看
- 队列运行状态

### 10. 测试覆盖需要从单函数扩展到流程级

当前测试主要覆盖：

- 文案链接规范化
- 发布 payload 构建

后续需要补：

- 下载失败不破坏旧文件
- 合并失败不破坏旧文件
- tid LLM 返回非法值时阻止真实发布
- 已发布视频阻止重复发布
- 发现去重
- 任务状态迁移
- Web API 基础接口

## 优先级建议

第一批：

1. 引入 SQLite 状态库
2. 把单视频 CLI 改为写入/读取任务状态
3. 加重复发布保护
4. 修下载/合并原子替换
5. tid 选择 fail-closed

第二批：

1. 自动发现
2. 自动下载队列
3. 自动发布队列
4. 重试和错误恢复

第三批：

1. Web 后端 API
2. Web 前端列表和详情
3. 文案/tid 人工审核和发布控制

第四批：

1. 运行指标
2. 日志查看
3. 长期清理策略
4. 多平台发布扩展

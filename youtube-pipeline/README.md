# youtube-pipeline

本地 YouTube 搬运流水线，负责：

1. 根据 YouTube URL 获取 `meta.json`
2. 下载最佳兼容 MP4/H.264 视频流和 M4A 音频流
3. 下载封面图
4. 使用 ffmpeg 合并为 `<video_id>_merge.mp4`
5. 使用 MiniMax-M3 生成中文 B 站标题、描述、标签
6. 调用 `social-auto-upload` 已验证的 B 站发布能力上传

旧的远程 HK API、中转服务、定时发现逻辑不在本目录继续维护。

## 安装

```bash
cd youtube-pipeline
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
```

`.env` 中至少需要配置：

```text
PROXY=http://127.0.0.1:7897
SOCIAL_AUTO_UPLOAD_DIR=../social-auto-upload
BILIBILI_ACCOUNT=mybili
BILIBILI_TID=27
MINIMAX_ANTHROPIC_API_KEY=...
```

发布依赖 `social-auto-upload/cookies/bilibili_<account>.json`。

## 命令

启动本地管理台：

```bash
youtube-pipeline web
```

默认地址为 `http://127.0.0.1:8505`，可通过 `.env` 中的 `WEB_HOST`、`WEB_PORT` 修改。

运行一轮自动队列：

```bash
youtube-pipeline worker-run
```

worker 默认会按低水位补充 discovery，并推进 download/describe。真实发布默认关闭。

自动发布模式由 `.env` 中的 `PUBLISH_MODE` 控制：

```text
manual         # 不自动发布
approved_auto  # 只自动发布审核通过的草稿
full_auto      # 自动发布有效的非 fallback 草稿
```

所有自动发布模式都会受每日上限、发布时间窗口、最小发布间隔限制。

失败处理由 job 状态接管。网络、LLM、发布平台临时错误会按指数退避延迟重试；YouTube 403、视频不可用、需要登录、fallback tid、合并失败等会直接进入 `failed`，避免反复占用队列。重试间隔由 `.env` 中的 `JOB_RETRY_BASE_SECONDS` 和 `JOB_RETRY_MAX_SECONDS` 控制。

worker 会在每轮开始恢复超时任务，并用 `locked_at`/`lock_owner` 防止重复领取。超时时间由 `.env` 中的 `JOB_LEASE_SECONDS` 控制。

下载并合并：

```bash
youtube-pipeline add-url "https://www.youtube.com/watch?v=ppMXtTbNnCs"
youtube-pipeline download-next
```

对已下载视频生成发布草稿：

```bash
youtube-pipeline describe ppMXtTbNnCs
```

审核发布草稿：

```bash
youtube-pipeline review ppMXtTbNnCs approved
youtube-pipeline review ppMXtTbNnCs rejected --note "不适合发布"
```

发布预览，不上传：

```bash
youtube-pipeline publish ppMXtTbNnCs --dry-run
```

真实发布到 B 站：

```bash
youtube-pipeline publish ppMXtTbNnCs
```

旧的单 URL 直通链路仍保留用于临时验证：

```bash
youtube-pipeline run "https://www.youtube.com/watch?v=ppMXtTbNnCs" --dry-run-publish
```

## 输出结构

```text
runtime/downloads/<video_id>/
  meta.json
  video.mp4
  audio.m4a
  poster.jpg
  <video_id>_merge.mp4
```

## 分区说明

B 站分区错误会导致 `biliup` 返回：

```text
code: 21150, message: "投稿入口升级中，请重新编辑稿件"
```

已验证动画短片使用 `tid=27` 可以发布成功。

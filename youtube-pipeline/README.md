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

下载并合并：

```bash
youtube-pipeline add-url "https://www.youtube.com/watch?v=ppMXtTbNnCs"
youtube-pipeline download-next
```

对已下载视频生成发布草稿：

```bash
youtube-pipeline describe ppMXtTbNnCs
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

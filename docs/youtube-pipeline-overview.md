# youtube-pipeline 当前主线说明

`youtube-pipeline/` 是当前已跑通的本地 YouTube 搬运主线。

它替代原先的 `hk-server/` 命名和远程中转定位。后续优化优先围绕本目录进行。

## 当前职责

```text
YouTube URL
  -> yt-dlp 获取 meta.json
  -> 下载 video.mp4 / audio.m4a / poster
  -> ffmpeg 合并 <video_id>_merge.mp4
  -> MiniMax-M3 生成中文标题、描述、标签
  -> 复用 social-auto-upload 的 Bilibili biliup 能力发布
```

## 保留但不迁移的内容

以下内容没有进入 `youtube-pipeline` 主线：

- 原远程 HK API 服务
- 原 systemd / logrotate 部署模板
- 定时发现、远程拉取、HTTP 中转相关逻辑
- `social-auto-upload` 中的多平台历史代码
- `youtobe-parser` 旧实现

这些目录和历史文件仍保留在仓库中，后续如有需要可以继续参考。

## 主入口

```bash
cd youtube-pipeline
source .venv/bin/activate
youtube-pipeline download "<youtube-url>"
youtube-pipeline publish runtime/downloads/<video_id> --tid 27 --dry-run
youtube-pipeline publish runtime/downloads/<video_id> --tid 27
youtube-pipeline run "<youtube-url>" --tid 27
```

## 关键配置

配置统一在 `youtube-pipeline/.env`：

| 配置 | 说明 |
|------|------|
| `OUTPUT_DIR` | 下载输出目录 |
| `VIDEO_FORMAT` | yt-dlp 视频格式选择 |
| `AUDIO_FORMAT` | yt-dlp 音频格式选择 |
| `PROXY` | YouTube 下载代理 |
| `FFMPEG_BIN` | ffmpeg 命令 |
| `SOCIAL_AUTO_UPLOAD_DIR` | `social-auto-upload` 目录 |
| `BILIBILI_ACCOUNT` | B 站账号名 |
| `BILIBILI_TID` | 默认 B 站分区 |
| `MINIMAX_ANTHROPIC_*` | MiniMax-M3 文案生成配置 |

## 已验证样例

样例 URL：

```text
https://www.youtube.com/watch?v=ppMXtTbNnCs
```

验证结果：

- 下载成功
- 视频/音频合并成功
- MiniMax-M3 中文文案生成成功
- B 站分区 `tid=27` 发布成功并审核通过

注意：此前使用 `tid=174` 会触发 B 站 `21150` 错误，动画短片应使用更匹配的动画分区。

# youtobe-parser (纯 Python 重构版)

从 0 开始重构，仅保留核心业务流程：

1. 链接解析 + 下载音频/视频（`yt-dlp`）
2. `fast-whisper` 音频识别，生成 `SRT`
3. 翻译字幕并转换成 `ASS`
4. `ASS + 音频 + 视频` 合并成最终 `MP4`

独立配音流程（不影响上面 1-4）：

5. 输入已存在 `MP4 + M4A + SRT + ASS`
6. 人声分离（Demucs）
7. 英文段落语义合并后翻译为中文并进行 TTS
8. 依据原时间轴对齐中文语音，和伴奏混音后封装成配音版 `MP4`

## 设计目标

- **高效**：全链路纯 Python，减少多服务通信开销。
- **快捷**：单命令跑完整流程。
- **可迁移**：默认可使用 `imageio-ffmpeg` 自动下载项目专用二进制，也支持自定义 `ffmpeg` 路径。
- **GPU 兼容**：`faster-whisper` 原生支持 CUDA 场景。

## 安装

```bash
python -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e .
```

## 环境变量（可选）

复制 `.env.example` 到 `.env` 后按需修改：

- `WHISPER_MODEL`（默认 `large-v3`）
- `WHISPER_MODEL_SOURCE`（`huggingface` 或 `modelscope`，默认 `huggingface`）
- `WHISPER_MODELSCOPE_REPO`（当 source=modelscope 时必填）
- `WHISPER_MODEL_CACHE_DIR`（模型下载缓存目录，默认 `runtime/models`）
- `WHISPER_DOWNLOAD_TO_LOCAL`（默认 `true`，HF 模型先下载到本地目录再加载）
- `WHISPER_DOWNLOAD_PROXY`（Whisper 模型下载代理）
- `WHISPER_MODEL_FALLBACK_TO_MODELSCOPE`（默认 `true`，HF 失败时自动回退）
- `WHISPER_DEVICE`（默认 `auto`，会自动选择 GPU/CPU；可强制为 `cuda` 或 `cpu`）
- `WHISPER_COMPUTE_TYPE`（默认 `auto`）
- `WHISPER_LANGUAGE`（默认 `en`）
- `TRANSCRIBE_USE_VOCALS`（默认 `false`，为 `true` 时先做人声分离，再用 `vocals.wav` 进行 Whisper 转写）
- `TRANSCRIBE_VOCALS_FALLBACK_TO_ORIGINAL`（默认 `true`，人声分离失败时自动回退原始音频转写）
- `TRANSCRIBE_SEPARATION_DIRNAME`（默认 `transcribe_separated`，转写前分离产物目录）
- `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `OPENAI_MODEL`
- `TARGET_LANGUAGE`（默认 `zh-CN`）
- `TRANSLATION_BATCH_SIZE`（默认 `20`，LLM 批量翻译大小）
- `PIPELINE_ENABLE_DUBBING`（默认 `true`，主入口是否同时产出中文配音版）
- `DUBBING_WORK_DIRNAME`（默认 `dubbing`，配音流程产物目录）
- `DEMUCS_COMMAND` / `DEMUCS_MODEL`（默认 `demucs` / `htdemucs_ft`）
- `DEMUCS_DEVICE`（默认 `auto`：优先 `torch.cuda.is_available()`，其次 `nvidia-smi`，否则 `cpu`）
- `DEMUCS_CACHE_DIR`（默认 `models/demucs`，Demucs 权重缓存固定在项目内）
- `TTS_PROVIDER`（`openai` 或 `edge`）
- `TTS_VOICE_GENDER`（`female` / `male`，默认 `female`，用于 edge 语音默认选择）
- `TTS_EDGE_VOICE_FEMALE` / `TTS_EDGE_VOICE_MALE`
- `DUBBING_PRESET`（`default` / `natural`，`natural` 会使用更大的前移窗口和更低最小语速，进一步压缩“字幕先出但没声”的空白感）
- `DUBBING_TIMING_MODE`（`strict` / `relaxed`，建议 `relaxed`，减少“有字幕没声音”的段落空白）
- `DUBBING_REFLOW_SUBTITLES`（默认 `true`，将中文配音字幕按中文语句重新切分与重排，不再机械跟随英文分段）
- `DUBBING_SUBTITLE_MAX_CHARS`（默认 `20`，中文重排后单条字幕最大字数）
- `DUBBING_SUBTITLE_MAX_DURATION_SEC`（默认 `3.6`，中文重排后单条字幕最大时长）
- `DUBBING_SUBTITLE_MAX_GAP_SEC`（默认 `0.25`，相邻短语在此间隔内可合并成一条字幕）
- `DUBBING_TRIM_TTS_SILENCE`（默认 `true`，裁掉每段 TTS 首尾静音，减少“有字幕但没声”）
- `DUBBING_TTS_SILENCE_THRESHOLD` / `DUBBING_TTS_KEEP_LEAD_SEC` / `DUBBING_TTS_KEEP_TAIL_SEC`（TTS 静音裁剪阈值和保留首尾）
- `DUBBING_PRESERVE_FULL_TEXT`（默认 `true`，不再按语速上限截断中文文本）
- `DUBBING_DISABLE_TIME_STRETCH`（默认 `true`，不做 TTS 变速，宁可整体变慢/错位）
- `WORK_DIR`（默认 `runtime`）
- `OUTPUT_NAME`（默认 `final_output`）
- `METADATA_DIRNAME`（默认 `metadata`，保存视频基础信息 JSON）
- `FFMPEG_PATH`（可选，自定义 ffmpeg 可执行文件绝对路径）
- `YTDLP_PROXY`（可选，视频解析与下载代理，例如 `socks5://127.0.0.1:7897`）
- `PLAYLIST_STRATEGY`（默认 `first`，合集链接仅下载当前视频/首个视频）
- `YTDLP_VIDEO_FORMAT`（默认优先 `avc1` 的 mp4，避免旧 ffmpeg 无法解码 av1）
- `YTDLP_AUDIO_FORMAT`（默认 `bestaudio[ext=m4a]/bestaudio`）
- `LOG_LEVEL`（日志级别，默认 `INFO`）
- `LOG_FILE`（日志文件路径，默认 `runtime/logs/pipeline.log`）

> 不配置 `OPENAI_API_KEY` 时，翻译阶段会跳过（直接使用原文）。

## 运行

```bash
python main.py "https://www.youtube.com/watch?v=..."
# 或
yp-run "https://www.youtube.com/watch?v=..."
```

每日选题发现（抓取 + 评分 + 入库 + 下载 + 磁盘清理）：

```bash
# 单次运行（发现 -> 下载 -> 清理）
yp-scheduler
```

长期运行服务（HTTP API + 定时发现任务）：

```bash
yp-server
```
默认地址：`http://127.0.0.1:8503`（可通过 `API_HOST` / `API_PORT` 配置）

Discovery 类型配置（`.env`）：
- `DISCOVERY_TOPIC_TYPES=ai,tech,digital,pets,beauty,funny`：选择抓取类型，可组合
- 每类独立配置关键词和语言过滤：`DISCOVERY_TOPIC_<TYPE>_KEYWORDS` / `DISCOVERY_TOPIC_<TYPE>_LANGUAGES`（空 = 不限语言）
- `DISCOVERY_KEYWORDS`：额外补充关键词（可留空）
- `DISCOVERY_DOWNLOAD_MIN_SCORE`：自动下载的分数阈值（默认 10.0）
- `DISCOVERY_HTTP_RETRIES` / `DISCOVERY_HTTP_RETRY_BACKOFF_SEC`：YouTube API 请求重试

磁盘滚动删除（`.env`）：
- `DISK_MAX_STORAGE_GB=50`：最大存储空间 (GB)
- `DISK_MAX_RETENTION_DAYS=30`：视频最长保留天数
- 每次下载后自动检查，超出任一阈值即按时间从旧到新删除

API 认证（`.env`）：
- `API_TOKEN=`（空 = 不需认证；非空时需 `Authorization: Bearer <token>`）

API 端点：
| Method | Path | 说明 |
|--------|------|------|
| GET | `/api/videos?category=&status=&min_score=&limit=&offset=` | 视频列表（分页） |
| GET | `/api/videos/<id>` | 单条详情 |
| GET | `/api/videos/<id>/file?type=video\|audio\|thumbnail` | 下载文件 |
| DELETE | `/api/videos/<id>` | 删除视频 |
| POST | `/api/trigger-discovery` | 手动触发发现+下载 |
| GET | `/api/stats` | 存储统计 |

主入口会统一产出两份视频：
- 双语字幕原声版：`runtime/output/<id>.mp4`
- 中文字幕配音版：`runtime/dubbing/output/<id>.dubbed.mp4`

独立配音流程（可单独重跑配音阶段）：

```bash
yp-dub --video runtime/downloads/<id>.mp4 --audio runtime/downloads/<id>.m4a --srt runtime/subtitles/<id>.srt --ass runtime/subtitles/<id>.ass
```

预下载 Demucs 模型（首次建议先执行一次）：

```bash
python tests/download_demucs_model.py
```

输出目录：

- `runtime/downloads/`：下载的音视频
- `runtime/subtitles/*.srt`：识别字幕（按视频 `id` 命名）
- `runtime/subtitles/*.ass`：翻译后 ASS（按视频 `id` 命名）
- `runtime/output/*.mp4`：最终成片（默认 `OUTPUT_NAME.mp4`）
- `runtime/metadata/*.video_info.json`：视频解析基础信息（按视频 `id` 命名）
- `runtime/dubbing/`：独立配音流程中间产物与最终成片
- `runtime/discovery/discovery.db`：每日发现候选视频库（SQLite）

## 代码结构

- `app/pipeline.py`：总流程编排
- `app/downloader.py`：yt-dlp 下载与媒体定位
- `app/download_service.py`：发现 -> 下载 -> 清理 全流程编排
- `app/disk_cleaner.py`：磁盘滚动删除（大小 + 天数双阈值）
- `app/api.py`：HTTP API 服务（Token 认证 + CRUD）
- `app/scheduler.py`：统一入口（yp-scheduler / yp-server）
- `app/transcriber.py`：fast-whisper 封装
- `app/translator.py`：字幕翻译
- `app/subtitles.py`：SRT/ASS 读写
- `app/ffmpeg_tools.py`：项目内 ffmpeg 调用
- `app/discovery/`：YouTube Data API v3 发现模块（models / scoring / repository / service）

## 仓库清理说明

已删除历史遗留的 `server/`、`scripts/`、`docs/`、`docker-compose.yml`、旧 CI 工作流与旧 lock 文件，仅保留当前纯 Python 流程所需代码。


## 代理示例

如果你本地使用代理（如 clash/v2ray），可在 `.env` 中配置：

```env
YTDLP_PROXY=socks5://127.0.0.1:7897
```

该代理会用于 `yt-dlp` 的链接解析和媒体下载。


## 测试

分阶段测试脚本：

```bash
python tests/run_stage_checks.py
```

全量单元测试：

```bash
python -m unittest discover -s tests -v
```

说明：测试已覆盖下载、转写、翻译、字幕生成、ffmpeg 调用和整条 Pipeline 编排（通过 mock 进行端到端流程验证）。


## 日志

流程会输出到控制台并写入日志文件。

默认日志文件：`runtime/logs/pipeline.log`

你可以通过 `.env` 配置：

```env
LOG_LEVEL=INFO
LOG_FILE=runtime/logs/pipeline.log
```


## 合集链接策略

针对如下链接：

`https://www.youtube.com/watch?v=DFdh8BrzJ_Y&list=RDDFdh8BrzJ_Y&start_radio=1`

当前默认策略是 `PLAYLIST_STRATEGY=first`：
- 自动归一化为 `https://www.youtube.com/watch?v=DFdh8BrzJ_Y`
- 只处理当前视频（不整单播放列表）

这样可以保证主流程（单视频→单字幕→单输出）稳定可控。后续如果你要“整合集批处理”，我们可以再扩展 `all` 模式。


## Whisper 模型下载源

默认使用 HuggingFace（`WHISPER_MODEL_SOURCE=huggingface`）。

如果 HuggingFace 网络不稳定，可以切换到 ModelScope：

```env
WHISPER_MODEL_SOURCE=modelscope
WHISPER_MODELSCOPE_REPO=你的模型仓库ID
WHISPER_MODEL_CACHE_DIR=runtime/models
```

说明：
- `modelscope` 会先把模型下载到本地缓存目录，再由 `faster-whisper` 从本地路径加载。
- 如果你直接把 `WHISPER_MODEL` 设成本地目录路径，则优先使用本地模型路径。


### HF 网络失败建议

如果你遇到 `huggingface_hub ... Network is unreachable`：

1. 先配置下载代理（可与 `YTDLP_PROXY` 一致）：

```env
WHISPER_DOWNLOAD_PROXY=socks5://127.0.0.1:7897
```

2. 或直接改为 ModelScope：

```env
WHISPER_MODEL_SOURCE=modelscope
WHISPER_MODELSCOPE_REPO=你的模型仓库ID
```

3. 默认已开启 `WHISPER_MODEL_FALLBACK_TO_MODELSCOPE=true`，当 HF 拉取失败且配置了 ModelScope repo 时会自动回退。


## 下载命名与格式策略

- 文件名使用 `video_id`（例如 `abc123.mp4`、`abc123.m4a`），避免超长标题带来的路径问题。
- 视频默认优先下载 `bestvideo[ext=mp4][vcodec^=avc1]`（可通过 `YTDLP_VIDEO_FORMAT` 配置），音频优先下载 `bestaudio[ext=m4a]`。
- 若目标扩展不可用，会自动回退到该视频 ID 的可用格式并记录 warning 日志。

2. 或直接改为 ModelScope：

## 预下载 fast-whisper 模型

在正式跑主流程前，可以先执行：

```bash
python tests/download_fast_whisper_model.py
```

该脚本会按 `.env` 里的 `WHISPER_MODEL_SOURCE` / `WHISPER_MODELSCOPE_REPO` / `WHISPER_MODEL_CACHE_DIR` / `WHISPER_DOWNLOAD_PROXY` 进行模型下载并返回本地路径。

同时当 `WHISPER_DEVICE=auto` 时，程序会自动检测是否有 CUDA：
- 有 CUDA -> 使用 `cuda + float16`
- 无 CUDA -> 使用 `cpu + int8`


### SOCKS 代理依赖说明

若你使用 `socks5://` 代理下载 whisper 模型，需要安装：

```bash
pip install socksio
```

否则 `httpx` 会报错：`Using SOCKS proxy, but the socksio package is not installed.`


## 翻译策略

当前翻译采用 **批量翻译**（默认每批 20 条），通过“序号 + 制表符”的返回格式保证行数与顺序稳定，避免逐条翻译导致上下文残缺。


### FFmpeg 无法解码 AV1 的处理

如果你遇到 `Decoder (codec av1) not found`，说明本机 ffmpeg 对 AV1 解码支持不足。

本项目默认已优先下载 `avc1` 编码视频；你也可以在 `.env` 里强制：

```env
YTDLP_VIDEO_FORMAT=bestvideo[ext=mp4][vcodec^=avc1]/bestvideo[ext=mp4]/bestvideo
```

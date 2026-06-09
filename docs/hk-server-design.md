# hk-server 设计文档

## 概述

hk-server 是 YouTube 视频搬运系统的香港服务器端组件，负责：
1. **定时发现**热门视频并下载（视频流+音频流分离存储）
2. **提供 HTTP API** 供本地电脑拉取视频和元信息

采用 yt-dlp 全程驱动，不依赖 YouTube Data API，无 API 配额限制。

## 架构

```
hk-server (常驻进程)
│
├── 定时发现 & 下载 (后台线程)
│   ├── ytsearchN:keyword 搜索 YouTube
│   ├── 热度评分 + 去重 → 全量缓存 JSON (24h TTL)
│   ├── TopN 入库 SQLite
│   ├── yt-dlp 分离下载 bestvideo[ext=mp4] + bestaudio[ext=m4a]
│   └── 磁盘滚动删除 (超阈值/超期)
│
└── HTTP API :8503
    ├── GET  /api/videos                  查询视频列表(支持过滤/分页)
    ├── GET  /api/videos/<id>             视频详情
    ├── GET  /api/videos/<id>/meta        完整 .video_info.json 元信息
    ├── GET  /api/videos/<id>/file?type=video    下载 mp4 视频流
    ├── GET  /api/videos/<id>/file?type=audio    下载 m4a 音频流
    ├── GET  /api/videos/<id>/file?type=thumbnail 下载封面图
    ├── DELETE /api/videos/<id>           确认拉取，删除服务器文件
    ├── GET  /api/stats                   存储统计
    └── POST /api/trigger-discovery       手动触发发现+下载
```

## 数据流

```
┌──────────────────────────────────────────────────┐
│              第一次运行 (无缓存)                    │
│                                                    │
│  ytsearch15:keyword × N                           │
│       │                                            │
│       ▼                                            │
│  全量 raw 候选 → candidates_cache.json            │
│       │                                            │
│       ▼                                            │
│  评分排序 → TopN → SQLite discovered_videos       │
│       │                                            │
│       ▼                                            │
│  yt-dlp download → runtime/downloads/<cat>/<vid>/ │
│       │                                            │
│       └── <vid>.mp4      视频流(无音频)            │
│       └── <vid>.m4a      音频流                    │
│       └── <vid>.video_info.json  完整元信息        │
│       └── <vid>.thumbnail.jpg    封面图            │
└──────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────┐
│              后续运行 (有缓存，24h 内)              │
│                                                    │
│  跳过搜索 ──→ 读 candidates_cache.json             │
│       │                                            │
│       ▼                                            │
│  重新评分 → 重新选 TopN → 入库 → 下载              │
└──────────────────────────────────────────────────┘
```

## 文件结构

```
hk-server/
├── app/
│   ├── discovery/
│   │   ├── __init__.py            # SSL 补丁
│   │   ├── models.py              # VideoCandidate dataclass
│   │   ├── scoring.py             # 热度评分、过滤、去重
│   │   ├── youtube_discovery.py   # yt-dlp 搜索 (替代 YouTube API)
│   │   ├── repository.py          # SQLite CRUD
│   │   └── service.py             # 发现主流程 + 关键词注册表
│   ├── downloader.py              # yt-dlp 双流下载模块
│   ├── download_service.py        # 发现→缓存→下载→清理 编排
│   ├── disk_cleaner.py            # 滚动删除管理
│   ├── api.py                     # HTTP API (标准库)
│   ├── scheduler.py               # hk-server / hk-scheduler 入口
│   ├── settings.py                # Pydantic 配置
│   ├── logging_utils.py           # 日志
│   └── _ssl_patch.py              # certifi CA 补丁
├── .env                           # 运行配置
├── .env.example                   # 配置模板
├── pyproject.toml                 # Python 项目定义
└── README.md
```

## 数据库设计

### discovered_videos 表

| 字段 | 类型 | 说明 |
|------|------|------|
| video_id | TEXT PK | YouTube 视频 ID |
| discovered_at | TEXT | 发现时间 (ISO 8601) |
| url | TEXT | YouTube 完整 URL |
| title | TEXT | 视频标题 |
| description | TEXT | 视频描述 |
| channel_id | TEXT | 频道 ID |
| channel_title | TEXT | 频道名 |
| published_at | TEXT | 发布时间 |
| language_hint | TEXT | 语言提示 |
| duration_sec | INTEGER | 时长(秒) |
| view_count | INTEGER | 播放量 |
| comment_count | INTEGER | 评论数 |
| like_count | INTEGER | 点赞数 |
| keyword | TEXT | 搜索关键词 |
| category | TEXT | 分类(pets/beauty/funny) |
| score | REAL | 热度评分 |
| download_status | TEXT | pending/downloading/downloaded/failed/cleaned |
| file_path | TEXT | 本地存储路径 |
| file_size | INTEGER | 文件总大小(bytes) |
| downloaded_at | TEXT | 下载完成时间 |
| download_error | TEXT | 下载失败原因 |

## API 详情

### GET /api/videos

查询参数：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| download_status | (空=全部) | 按下载状态过滤 |
| category | (空=全部) | 按分类过滤 |
| min_score | 0 | 最低评分 |
| limit | 50 | 分页大小 |
| offset | 0 | 分页偏移 |

响应示例：
```json
{
  "videos": [
    {
      "video_id": "abc123",
      "url": "https://www.youtube.com/watch?v=abc123",
      "title": "Funny Cat Compilation",
      "category": "pets",
      "score": 11.5,
      "view_count": 11437719,
      "duration_sec": 320,
      "download_status": "downloaded",
      "file_path": "runtime/downloads/pets/abc123",
      "downloaded_at": "2026-06-09T10:00:00+00:00"
    }
  ],
  "total": 15,
  "limit": 50,
  "offset": 0
}
```

### GET /api/videos/{id}/meta

返回完整的 `.video_info.json` 内容，包含：
- 标题、描述、频道、标签、分类
- 技术参数：分辨率、fps、vcodec、acodec、码率
- 缩略图列表、时长、地区限制等 40+ 字段

### DELETE /api/videos/{id}

删除服务器端文件并标记 `download_status='cleaned'`。

## 本地端对接

本地电脑通过 `hk_puller` 拉取：

```
本地电脑                              香港服务器
    │                                    │
    ├─ GET /api/videos                   │
    │  (download_status=downloaded)       │
    │◄────────────────────────────────────┤
    │                                    │
    ├─ GET /api/videos/<id>/file?type=video
    │◄─────── 流式下载 .mp4 ──────────────┤
    │                                    │
    ├─ GET /api/videos/<id>/file?type=audio
    │◄─────── 流式下载 .m4a ──────────────┤
    │                                    │
    ├─ GET /api/videos/<id>/meta
    │◄─────── 完整元信息 JSON ────────────┤
    │                                    │
    ├─ ffmpeg -i video.mp4 -i audio.m4a
    │  -c copy merged.mp4               │
    │                                    │
    ├─ DELETE /api/videos/<id>           │
    │◄─────── 确认删除 ──────────────────┤
    │                                    │
    └─ biliup upload merged.mp4          │
```

## 配置说明

### .env 核心配置项

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| YTDLP_PROXY | (空) | socks5 代理地址，如 socks5://127.0.0.1:7897 |
| YTDLP_VIDEO_FORMAT | bestvideo[ext=mp4] | 视频流格式选择器 |
| YTDLP_AUDIO_FORMAT | bestaudio[ext=m4a] | 音频流格式选择器 |
| DISCOVERY_TOPIC_TYPES | pets,beauty,funny | 活跃分类 |
| DISCOVERY_TOP_N | 5 | 每日选取数量 |
| DISCOVERY_DAYS_BACK | 7 | 搜索范围(天) |
| DISCOVERY_MIN_VIEWS | 10000 | 最低播放量 |
| DISCOVERY_INTERVAL_MINUTES | 1440 | 发现周期(分钟) |
| DISCOVERY_DOWNLOAD_MIN_SCORE | 5.0 | 最低下载评分 |
| DOWNLOAD_INTERVAL_SEC | 180 | 下载间隔(秒) |
| DISK_MAX_STORAGE_GB | 50 | 最大存储容量 |
| DISK_MAX_RETENTION_DAYS | 7 | 最大保留天数 |
| API_PORT | 8503 | HTTP 监听端口 |
| API_TOKEN | (空) | API 鉴权 Token (空=无鉴权) |

## 部署

```bash
git clone git@github.com:CIPFZ/youtobe-move.git
cd youtobe-move/hk-server
cp .env.example .env
nano .env  # 配置 YTDLP_PROXY (如需代理)

python3 -m venv .venv
source .venv/bin/activate
pip install -e .

# 启动常驻服务
hk-server
```

## 依赖

```
certifi>=2024.0.0
yt-dlp>=2024.0.0
pydantic-settings>=2.0.0
python-dotenv>=1.0.0
socksio>=1.0.0     # socks5 代理支持(可选)
```

无需 ffmpeg、GPU、torch 等任何重型依赖。

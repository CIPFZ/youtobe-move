# youtobe-move — YouTube 视频搬运系统

两服务的 monorepo，实现 YouTube 视频自动发现、下载、跨平台分发的完整搬运流水线。

## 仓库结构

```
youtobe-move/
├── youtobe-parser/          香港服务器 — 发现 + 下载 + API
├── social-auto-upload/      本地服务器 — 拉取 + 多平台发布
├── .omc/                    共享 OMC 工作目录
└── AGENTS.md                本文件
```

## 整体数据流

```
YouTube  ──►  youtobe-parser (HK)  ──►  social-auto-upload (本地)  ──►  抖音/B站/小红书/...
              │                              │
              │ discovery (YouTube API)       │ hk_puller (HTTP 拉取)
              │ download (yt-dlp)             │ Flask 路由 + 手动发布
              │ HTTP API (port 8503)          │ Frontend (Vue.js)
              │ disk cleaner                  │
```

---

# youtobe-parser（香港服务器端）

## 职责

YouTube 视频候选发现 → 评分排序 → yt-dlp 下载 → HTTP API 对外暴露。

## 代码结构

```
youtobe-parser/
  main.py                   单视频全流程处理 (下载 → 转写 → 翻译 → 合成)
  dub_main.py               独立配音流程入口
  discovery_dashboard.py    本地 Web 面板 (遗留)

  app/
    _ssl_patch.py           SSL CA 补丁 (certifi)
    settings.py             Pydantic Settings (.env 驱动)
    downloader.py           yt-dlp 下载 (video + audio + thumbnail)
    download_service.py     发现 → 下载 → 清理 全流程编排
    disk_cleaner.py         磁盘滚动删除 (大小 + 天数双阈值)
    api.py                  HTTP API 服务 (ThreadingHTTPServer, port 8503)
    scheduler.py            统一入口 (yp-scheduler / yp-server)
    pipeline.py             转写+翻译+合成流程
    transcriber.py          fast-whisper
    translator.py           LLM 翻译
    logging_utils.py        日志配置

    discovery/
      __init__.py           导入 _ssl_patch
      models.py             VideoCandidate dataclass
      youtube_discovery.py  YouTube Data API v3 搜索
      scoring.py            热度评分 + 语言过滤 + 去重
      repository.py         SQLite 操作 (discovered_videos + processing_jobs)
      service.py            主流程 + TOPIC_REGISTRY
```

## 入口点

| 命令 | 功能 |
|------|------|
| `yp-run <url>` | 单视频全流程 |
| `yp-dub` | 独立配音 |
| `yp-scheduler` | 一次 发现+下载+清理 循环 |
| `yp-server` | HTTP API + 后台定时器 |

## 6 个视频分类

`TOPIC_REGISTRY` 定义在 `app/discovery/service.py`：

| 分类 | 语言限制 | 示例关键词 |
|------|---------|-----------|
| ai | en | AI, OpenAI, Anthropic, Google DeepMind, LLM |
| tech | en | technology, tech news, software engineering, cloud computing |
| digital | en | gadgets, consumer tech, smartphone review, laptop review |
| pets | 不限 | funny cats, cute dogs, pet videos, animal compilation |
| beauty | 不限 | makeup tutorial, skincare routine, beauty tips, hair styling |
| funny | 不限 | funny videos, comedy clips, pranks, fails |

语言限制在 `.env` 中通过 `DISCOVERY_TOPIC_{TYPE}_LANGUAGES` 独立配置，空值 = 不限。

## HTTP API 端点 (port 8503)

| Method | Path | Auth | 说明 |
|--------|------|------|------|
| GET | `/api/videos?category=&status=&min_score=&limit=&offset=` | token | 视频列表 |
| GET | `/api/videos/<id>` | token | 单条详情 |
| GET | `/api/videos/<id>/file?type=video\|audio\|thumbnail` | token | 流式下载 |
| DELETE | `/api/videos/<id>` | token | 删除 |
| POST | `/api/trigger-discovery` | token | 触发发现+下载 |
| GET | `/api/stats` | token | 存储统计 |

Auth: `Authorization: Bearer <API_TOKEN>`（空 token = 无认证）。

## 关键配置 (.env)

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `DISCOVERY_TOPIC_TYPES` | `ai,tech,digital,pets,beauty,funny` | 激活的分类 |
| `DISCOVERY_TOPIC_{X}_KEYWORDS` | (各分类独立) | 搜索关键词 |
| `DISCOVERY_TOPIC_{X}_LANGUAGES` | `en` / 空 | 语言白名单 |
| `DISCOVERY_DOWNLOAD_MIN_SCORE` | `10.0` | 下载阈值 |
| `DISK_MAX_STORAGE_GB` | `50.0` | 磁盘上限 |
| `DISK_MAX_RETENTION_DAYS` | `30` | 保留天数 |
| `API_TOKEN` | 空 | API 认证 token |
| `API_HOST` | `0.0.0.0` | API 绑定地址 |
| `DOWNLOAD_MEDIA_DIR` | `runtime/downloads` | 下载目录 |
| `YTDLP_PROXY` | 空 | yt-dlp 代理 |

---

# social-auto-upload（本地发布端）

## 职责

从 HK 服务器拉取视频 → 本地管理 → 手动分发到抖音/B站/小红书/快手/视频号。

## 代码结构

```
social-auto-upload/
  conf.py / conf.example.py   应用配置 (HK 地址/token/轮询间隔)
  hk_puller.py                HK 视频拉取核心模块
  sau_backend.py              Flask 后端 (port 5409)
  sau_cli.py                  多平台 CLI (Douyin/Bilibili/XHS/Kuaishou/Tencent)

  db/
    createTable.py            SQLite 建表 (user_info / file_records / hk_videos / hk_sync_log)

  uploader/                   各平台上传实现 (Playwright 浏览器自动化)
  myUtils/                    工具 (auth/login/postVideo)
  sau_frontend/               Vue.js 前端

  额外依赖:
    requests                  用于 HTTP 拉取
    playwright                浏览器自动化
    Flask                     后端框架
    biliup                    B站上传
```

## HK 拉取流程

```
hk_poller (后台线程, 每 N 分钟):
  →
  GET /api/videos?download_status=downloaded  (从 HK)
  →
  去重 (video_id) → 插入本地 hk_videos 表
  →
  下载文件 → videoFile/hk/{category}/{video_id}.mp4
  →
  用户在前端手动选择发布
```

## Flask 路由 (port 5409)

| 路由 | 方法 | 说明 |
|------|------|------|
| `/hk/videos` | GET | 已拉取的 HK 视频列表 |
| `/hk/sync` | POST | 手动触发拉取 |
| `/hk/stats` | GET | 拉取统计 |
| `/hk/file/<id>` | GET | 获取本地视频文件 |

原有路由 (`/upload`, `/postVideo`, `/login` 等) 保持不变。

## HK 拉取配置 (conf.py)

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `HK_SERVER_URL` | `http://192.168.1.5:8503` | HK 服务器地址 |
| `HK_API_TOKEN` | 空 | HK API 认证 token |
| `HK_POLL_INTERVAL_MINUTES` | `30` | 轮询间隔 |
| `HK_AUTO_DOWNLOAD` | `True` | 是否自动下载新视频 |
| `HK_DOWNLOAD_DIRNAME` | `hk` | 下载子目录 |

## 数据库

SQLite: `db/database.db`

| 表 | 说明 |
|----|------|
| `user_info` | 多平台账号信息 |
| `file_records` | 上传文件记录 |
| `hk_videos` | HK 拉取的视频元数据 |
| `hk_sync_log` | 同步日志 |

---

# 开发工作流

## 首次安装

```bash
# HK 服务器
cd youtobe-parser
python -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env  # 编辑配置

# 本地发布端
cd social-auto-upload
pip install -r requirements.txt
playwright install chromium
cp conf.example.py conf.py  # 编辑配置
python db/createTable.py
```

## 启动

```bash
# HK 端（发现 + 下载 + API）
cd youtobe-parser && yp-server

# 本地端（拉取 + 发布）
cd social-auto-upload && python3 sau_backend.py
```

## 注意事项

- `youtobe-parser` 使用 uv/pip 管理的 venv，依赖在 `pyproject.toml`
- `social-auto-upload` 使用系统 Python + `requirements.txt`
- 两项目的 Python 环境独立
- HK server SSL 问题已通过在 `_ssl_patch.py` 注入 certifi 修复
- disk_cleaner 在每次下载后自动触发，按时间和大小双阈值滚动删除
- HK API 返回的 video_id 用 `sqlite3.Row` 按名索引，不依赖列顺序

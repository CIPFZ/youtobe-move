# hk-server — YouTube 视频每日发现与下载服务

香港服务器端，定时从 YouTube 发现指定分类的热门视频并下载，提供 HTTP API 供本地拉取。

## 依赖

```
certifi>=2024.0.0
yt-dlp>=2024.0.0
pydantic-settings>=2.0.0
python-dotenv>=1.0.0
socksio>=1.0.0     # 可选: socks5 代理
```

## 快速部署

```bash
cd hk-server

# 1. 配置
cp .env.example .env
# 编辑 .env 填入你的 YOUTUBE_API_KEY

# 2. 安装
pip install -e .

# 3. 运行
hk-scheduler            # 单次执行: 发现 → 下载 → 清理
hk-server               # 长期运行: HTTP API + 定时发现
```

## 运行模式

### hk-scheduler (单次)

执行一次完整的发现+下载+清理循环后退出。适合 crontab 定时调度:

```
# crontab: 每天凌晨 3:00 执行
0 3 * * * cd /path/to/hk-server && hk-scheduler >> runtime/logs/cron.log 2>&1
```

### hk-server (常驻)

启动 HTTP API 服务 + 后台定时发现轮询。发现间隔由 `DISCOVERY_INTERVAL_MINUTES` 控制（默认 1440 分钟 = 每天一次）:

```bash
hk-server
# 输出: API server listening on http://0.0.0.0:8503
```

## HTTP API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/videos?download_status=downloaded` | 待拉取视频列表 |
| GET | `/api/videos/<id>` | 视频详情 |
| GET | `/api/videos/<id>/file?type=video` | 下载视频文件 |
| GET | `/api/videos/<id>/file?type=thumbnail` | 下载封面 |
| DELETE | `/api/videos/<id>` | 确认拉取完成，服务器删除 |
| GET | `/api/stats` | 存储统计 |
| POST | `/api/trigger-discovery` | 手动触发发现 |

## 配置说明

关键配置项（`.env`）:

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `DISCOVERY_TOPIC_TYPES` | pets,beauty,funny | 分类列表 |
| `DISCOVERY_TOP_N` | 5 | 每天选取 Top N |
| `DISCOVERY_DAYS_BACK` | 7 | 搜索近 N 天视频 |
| `DISCOVERY_DOWNLOAD_MIN_SCORE` | 5.0 | 最低下载分数 |
| `DISK_MAX_STORAGE_GB` | 50 | 最大存储容量 |
| `DISK_MAX_RETENTION_DAYS` | 7 | 最大保留天数 |
| `API_PORT` | 8503 | HTTP 监听端口 |

## 文件结构

```
hk-server/
├── app/
│   ├── discovery/           # YouTube 发现模块
│   │   ├── models.py        # VideoCandidate 数据模型
│   │   ├── scoring.py       # 热度评分、语言过滤、去重
│   │   ├── youtube_discovery.py  # YouTube Data API v3 搜索
│   │   ├── repository.py    # SQLite 数据库操作
│   │   └── service.py       # 发现主流程 + 关键词注册
│   ├── downloader.py        # yt-dlp 下载模块
│   ├── download_service.py  # 发现→下载→清理 编排
│   ├── disk_cleaner.py      # 滚动删除管理
│   ├── api.py              # HTTP API 服务
│   ├── scheduler.py         # 调度入口
│   ├── settings.py          # 配置管理
│   ├── logging_utils.py     # 日志工具
│   └── _ssl_patch.py        # SSL CA 补丁
├── .env.example             # 配置模板
├── pyproject.toml           # 项目元信息
└── README.md
```

## 数据流

```
hk-scheduler / crontab
    │
    ├── YouTube Data API v3
    │   ├── 按分类关键词搜索
    │   ├── 评分 + 过滤 + 去重
    │   └── Top 5 VideoCandidate
    │
    ├── SQLite (discovery.db)
    │   └── upsert_candidates(video_id 主键去重)
    │
    ├── yt-dlp 下载
    │   └── runtime/downloads/<category>/<video_id>/
    │
    ├── cleanup_if_needed()
    │   └── 超出 50GB 或 7 天 → 删除最旧
    │
    └── HTTP API :8503
        ├── GET  /api/videos          → 本地拉取
        ├── GET  /api/videos/<id>/file → 下载文件
        └── DELETE /api/videos/<id>    → 确认删除
```

# hk-server Smoke Test And Operations

本文档用于部署后快速确认 HK 中转服务可用，并给出最小 systemd 和日志轮转示例。

## Automated Tests

```bash
cd /home/ytq/work/youtobe-move/hk-server
python3 -m pip install -e ".[dev]"
python3 -m pytest
```

当前测试不访问 YouTube 网络，覆盖：

- repository 建表、查询和状态流转。
- scoring 播放量、时长过滤和去重排序。
- disk_cleaner 过期和容量清理。
- API JSON envelope、视频 ID 解析和 Range 文件流。
- task_state 任务锁和错误记录。

## Health Smoke

启动服务：

```bash
cd /home/ytq/work/youtobe-move/hk-server
hk-server
```

另开终端执行：

```bash
curl -s http://127.0.0.1:8503/api/health
curl -s http://127.0.0.1:8503/api/tasks
curl -s "http://127.0.0.1:8503/api/videos?status=downloaded&limit=5"
```

预期：

- `/api/health` 返回 `{"ok": true, "data": ...}`。
- `/api/tasks` 返回任务分页列表，`data.current` 返回当前任务快照。
- `/api/videos` 返回 `data.items`、`data.total`、`data.limit`、`data.offset`。

如果配置了 `API_TOKEN`：

```bash
curl -s -H "Authorization: Bearer $API_TOKEN" http://127.0.0.1:8503/api/health
```

## Task Lock Smoke

连续触发两次发现任务：

```bash
curl -s -X POST http://127.0.0.1:8503/api/discovery/run
curl -s -X POST http://127.0.0.1:8503/api/discovery/run
```

预期第二次在任务仍运行时返回 `409`，错误码为 `task_running`。
第一次响应会包含 `data.task_id`，可继续查询：

```bash
curl -s http://127.0.0.1:8503/api/tasks/<task_id>
curl -s -X POST http://127.0.0.1:8503/api/tasks/<task_id>/cancel
curl -s -X POST http://127.0.0.1:8503/api/tasks/<task_id>/retry
```

## Manual Download Smoke

非法 URL 应返回 `400`：

```bash
curl -s -X POST http://127.0.0.1:8503/api/downloads \
  -H "Content-Type: application/json" \
  -d '{"url":"not-a-youtube-url","category":"manual"}'
```

合法 URL 会立即返回 `started=true` 和 `task_id`，后台执行下载：

```bash
curl -s -X POST http://127.0.0.1:8503/api/downloads \
  -H "Content-Type: application/json" \
  -d '{"url":"https://www.youtube.com/watch?v=VIDEO_ID_HERE","category":"manual"}'
curl -s http://127.0.0.1:8503/api/tasks
curl -s http://127.0.0.1:8503/api/videos/VIDEO_ID_HERE/events
```

## Disk And Log Checks

磁盘清理由 `DISK_MAX_STORAGE_GB` 和 `DISK_MAX_RETENTION_DAYS` 控制。部署前至少确认：

```bash
df -h /home/ytq/work/youtobe-move/hk-server/runtime
```

日志默认写入：

```text
runtime/logs/hk-server.log
```

logrotate 示例：

```text
/home/ytq/work/youtobe-move/hk-server/runtime/logs/*.log {
  daily
  rotate 14
  compress
  missingok
  notifempty
  copytruncate
}
```

## Systemd Example

```ini
[Unit]
Description=hk-server YouTube discovery and download service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/home/ytq/work/youtobe-move/hk-server
EnvironmentFile=/home/ytq/work/youtobe-move/hk-server/.env
ExecStart=/home/ytq/work/youtobe-move/hk-server/.venv/bin/hk-server
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

部署后：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now hk-server
sudo systemctl status hk-server
```

"""Local web service for HK video pipeline: pull, merge, AI describe, publish."""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

from conf import BASE_DIR, HK_AUTO_DOWNLOAD, HK_POLL_INTERVAL_MINUTES, HK_SERVER_URL
from hk_puller import (
    sync_hk_videos,
    run_hk_poller,
    publish_pending,
    fetch_hk_stats as _fetch_hk_stats,
    download_hk_meta,
    _mark_uploaded,
    _get_conn,
)

app = Flask(__name__)
CORS(app)
logger = logging.getLogger(__name__)


@app.route("/")
def index():
    return send_from_directory(str(Path(__file__).parent / "static"), "dashboard.html")


def _hk_conn() -> sqlite3.Connection:
    db = Path(BASE_DIR) / "db" / "database.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


# ── HK videos CRUD ──

@app.route("/hk/videos", methods=["GET"])
def hk_list():
    category = request.args.get("category", "").strip()
    status = request.args.get("status", "").strip()
    upload_status = request.args.get("upload_status", "").strip()
    limit = int(request.args.get("limit", 50))
    offset = int(request.args.get("offset", 0))

    conn = _hk_conn()
    sql = "SELECT * FROM hk_videos WHERE 1=1"
    params: list = []
    if category:
        sql += " AND category = ?"
        params.append(category)
    if status:
        sql += " AND download_status = ?"
        params.append(status)
    if upload_status:
        sql += " AND upload_status = ?"
        params.append(upload_status)
    total = conn.execute(f"SELECT COUNT(*) FROM ({sql})", params).fetchone()[0]
    sql += " ORDER BY score DESC, synced_at DESC LIMIT ? OFFSET ?"
    params.extend([max(1, min(int(limit), 200)), max(0, int(offset))])
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return jsonify({"videos": [dict(r) for r in rows], "total": total, "limit": limit, "offset": offset})


@app.route("/hk/videos/<video_id>", methods=["GET"])
def hk_detail(video_id: str):
    conn = _hk_conn()
    row = conn.execute("SELECT * FROM hk_videos WHERE video_id=?", (video_id,)).fetchone()
    conn.close()
    if not row:
        return jsonify({"error": "Not found", "video_id": video_id}), 404
    return jsonify({"video": dict(row)})


@app.route("/hk/videos/<video_id>/meta", methods=["GET"])
def hk_meta(video_id: str):
    conn = _hk_conn()
    row = conn.execute("SELECT meta_path FROM hk_videos WHERE video_id=? AND download_status='downloaded'", (video_id,)).fetchone()
    conn.close()
    if not row or not row["meta_path"]:
        return jsonify({"error": "Meta not found"}), 404
    meta_path = Path(row["meta_path"])
    if not meta_path.exists():
        return jsonify({"error": "Meta file missing on disk"}), 404
    return jsonify(json.loads(meta_path.read_text(encoding="utf-8")))


@app.route("/hk/videos/<video_id>/file", methods=["GET"])
def hk_file(video_id: str):
    conn = _hk_conn()
    row = conn.execute("SELECT file_path FROM hk_videos WHERE video_id=? AND download_status='downloaded'", (video_id,)).fetchone()
    conn.close()
    if not row or not row["file_path"]:
        return jsonify({"error": "File not found"}), 404
    path = Path(row["file_path"])
    if not path.exists():
        return jsonify({"error": "File missing on disk"}), 404
    return send_from_directory(str(path.parent), path.name, as_attachment=True)


# ── Actions ──

@app.route("/hk/sync", methods=["POST"])
def hk_sync():
    def _bg():
        try:
            summary = sync_hk_videos()
            logger.info("HK sync complete: %s", summary)
        except Exception as exc:
            logger.error("HK sync failed: %s", exc)

    threading.Thread(target=_bg, daemon=True).start()
    return jsonify({"started": True, "message": "HK sync triggered in background"})


@app.route("/hk/publish", methods=["POST"])
def hk_publish():
    data = request.get_json(force=True, silent=True) or {}
    interval_min = int(data.get("interval_min", 30))

    def _bg():
        try:
            summary = publish_pending(interval_min=interval_min)
            logger.info("Publish complete: %s", summary)
        except Exception as exc:
            logger.error("Publish failed: %s", exc)

    threading.Thread(target=_bg, daemon=True).start()
    return jsonify({"started": True, "message": f"Publish triggered, interval={interval_min}min"})


@app.route("/hk/stats", methods=["GET"])
def hk_stats():
    conn = _hk_conn()
    total = conn.execute("SELECT COUNT(*) FROM hk_videos").fetchone()[0]
    by_status = {}
    for r in conn.execute("SELECT download_status, COUNT(*) FROM hk_videos GROUP BY download_status"):
        by_status[str(r[0])] = r[1]
    by_category = {}
    for r in conn.execute("SELECT category, COUNT(*) FROM hk_videos GROUP BY category"):
        by_category[str(r[0]) or "uncategorised"] = r[1]
    by_upload = {}
    for r in conn.execute("SELECT upload_status, COUNT(*) FROM hk_videos GROUP BY upload_status"):
        by_upload[str(r[0])] = r[1]
    last_sync = conn.execute(
        "SELECT synced_at, new_count, downloaded_count FROM hk_sync_log ORDER BY id DESC LIMIT 1"
    ).fetchone()
    remote = {}
    if HK_SERVER_URL:
        try:
            remote = _fetch_hk_stats()
        except Exception:
            pass
    conn.close()
    return jsonify({
        "total_videos": total,
        "by_status": by_status,
        "by_category": by_category,
        "by_upload": by_upload,
        "last_sync": dict(last_sync) if last_sync else None,
        "hk_server": remote,
    })


@app.route("/hk/generate-meta", methods=["POST"])
def hk_generate_meta():
    """Generate Chinese metadata for a specific video using AI."""
    data = request.get_json(force=True, silent=True) or {}
    video_id = (data.get("video_id") or "").strip()
    if not video_id:
        return jsonify({"error": "video_id required"}), 400

    conn = _hk_conn()
    row = conn.execute("SELECT meta_path, category FROM hk_videos WHERE video_id=?", (video_id,)).fetchone()
    conn.close()

    if not row or not row["meta_path"]:
        return jsonify({"error": "Meta not found"}), 404
    meta_path = Path(row["meta_path"])
    if not meta_path.exists():
        return jsonify({"error": "Meta file missing on disk"}), 404

    try:
        from ai_describe import generate_chinese_metadata
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        cn = generate_chinese_metadata(meta, row["category"] or "")
        return jsonify(cn)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/hk/upload-status", methods=["POST"])
def hk_mark_uploaded():
    data = request.get_json(force=True, silent=True) or {}
    video_id = (data.get("video_id") or "").strip()
    if not video_id:
        return jsonify({"error": "video_id is required"}), 400
    ok = _mark_uploaded(_get_conn(), video_id, data.get("platform", "bilibili"))
    return jsonify({"video_id": video_id, "uploaded": ok, "platform": data.get("platform", "")})


@app.route("/hk/server-stats", methods=["GET"])
def hk_remote_stats():
    try:
        return jsonify(_fetch_hk_stats())
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


# ── Start ──

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    print("=" * 60)
    print("  Local HK Pipeline Service")
    print(f"  HK Server: {HK_SERVER_URL}")
    print(f"  Port: 5409")
    print("=" * 60)

    if HK_AUTO_DOWNLOAD:
        try:
            run_hk_poller()
            print(f"HK poller started (interval={HK_POLL_INTERVAL_MINUTES}min)")
        except Exception as exc:
            print(f"HK poller warning: {exc}")

    # Auto-publish poller: periodically upload downloaded videos to Bilibili
    def _publish_loop():
        time.sleep(30)  # initial delay
        while True:
            try:
                from hk_puller import publish_pending
                summary = publish_pending(interval_min=10)
                logger.info("Auto-publish cycle: %s", summary)
            except Exception as exc:
                logger.error("Auto-publish failed: %s", exc)
            time.sleep(3600)  # check every hour

    pub_thread = threading.Thread(target=_publish_loop, daemon=True, name="auto-publish")
    pub_thread.start()
    print("Auto-publish poller started (interval=60min, upload gap=10min)")

    app.run(host="0.0.0.0", port=5409, debug=False)

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import os
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from app.discovery.repository import claim_next_job, complete_job, enqueue_processing_job, init_db, list_jobs, upsert_candidates
from app.discovery.service import run_discovery_once
from app.settings import settings


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description='Local web dashboard for discovery results')
    p.add_argument('--host', default='127.0.0.1', help='Bind host')
    p.add_argument('--port', type=int, default=8502, help='Bind port')
    p.add_argument('--db-path', default='', help='Override discovery db path')
    return p.parse_args()


def _query_rows(db_path: Path, min_score: float, language_prefix: str, limit: int) -> list[tuple]:
    with sqlite3.connect(db_path) as conn:
        sql = """
        SELECT video_id, title, channel_title, published_at, language_hint, view_count, comment_count, score, url
        FROM discovered_videos
        WHERE score >= ?
        """
        params: list[object] = [min_score]
        if language_prefix:
            sql += ' AND lower(language_hint) LIKE ?'
            params.append(f'{language_prefix.lower()}%')
        sql += ' ORDER BY score DESC, discovered_at DESC LIMIT ?'
        params.append(max(1, min(limit, 500)))
        cur = conn.execute(sql, params)
        return list(cur.fetchall())


def _parse_outputs(log_path: Path) -> tuple[str, str]:
    if not log_path.exists():
        return '', ''
    bilingual = ''
    dubbed = ''
    try:
        lines = log_path.read_text(encoding='utf-8', errors='ignore').splitlines()
        for ln in lines:
            if ln.startswith('双语原声视频:'):
                bilingual = ln.split(':', 1)[1].strip()
            elif ln.startswith('中文配音视频:'):
                dubbed = ln.split(':', 1)[1].strip()
    except Exception:
        return '', ''
    return bilingual, dubbed


def _worker_loop(db_path: Path, repo_root: Path) -> None:
    jobs_dir = (settings.work_dir.resolve() / 'discovery' / 'job_logs').resolve()
    jobs_dir.mkdir(parents=True, exist_ok=True)
    while True:
        job = claim_next_job(db_path)
        if not job:
            time.sleep(2.5)
            continue

        job_id = int(job['id'])
        video_id = str(job['video_id'])
        url = str(job['url'])
        log_path = jobs_dir / f'job_{job_id}_{video_id}.log'
        cmd = [sys.executable, 'main.py', url]

        try:
            with log_path.open('w', encoding='utf-8') as f:
                proc = subprocess.run(
                    cmd,
                    cwd=repo_root,
                    stdout=f,
                    stderr=subprocess.STDOUT,
                    check=False,
                    env=os.environ.copy(),
                )
            bilingual, dubbed = _parse_outputs(log_path)
            if proc.returncode == 0:
                complete_job(
                    db_path,
                    job_id=job_id,
                    success=True,
                    bilingual_video=bilingual,
                    dubbed_video=dubbed,
                    log_path=str(log_path),
                )
            else:
                complete_job(
                    db_path,
                    job_id=job_id,
                    success=False,
                    error=f'pipeline rc={proc.returncode}',
                    bilingual_video=bilingual,
                    dubbed_video=dubbed,
                    log_path=str(log_path),
                )
        except Exception as exc:
            complete_job(
                db_path,
                job_id=job_id,
                success=False,
                error=str(exc),
                log_path=str(log_path),
            )


def _html_page(rows: list[tuple], jobs: list[tuple], min_score: float, language: str, limit: int, msg: str) -> str:
    trs: list[str] = []
    query_filter = urlencode({'min_score': min_score, 'lang': language, 'limit': limit})
    for r in rows:
        vid, title, channel, published, lang, views, comments, score, url = r
        enqueue_link = f'/?action=enqueue&video_id={html.escape(str(vid))}&{query_filter}'
        trs.append(
            '<tr>'
            f'<td>{html.escape(str(vid))}</td>'
            f'<td><a href="{html.escape(str(url))}" target="_blank">{html.escape(str(title))}</a></td>'
            f'<td>{html.escape(str(channel))}</td>'
            f'<td>{html.escape(str(published))}</td>'
            f'<td>{html.escape(str(lang))}</td>'
            f'<td>{int(views):,}</td>'
            f'<td>{int(comments):,}</td>'
            f'<td>{float(score):.3f}</td>'
            f'<td><a href="{enqueue_link}">触发处理</a></td>'
            '</tr>'
        )
    rows_html = '\n'.join(trs) if trs else '<tr><td colspan="9">No data</td></tr>'

    jtrs: list[str] = []
    for j in jobs:
        jid, vid, status, created, started, finished, error, bilingual, dubbed = j
        jtrs.append(
            '<tr>'
            f'<td>{jid}</td>'
            f'<td>{html.escape(str(vid))}</td>'
            f'<td>{html.escape(str(status))}</td>'
            f'<td>{html.escape(str(created))}</td>'
            f'<td>{html.escape(str(started))}</td>'
            f'<td>{html.escape(str(finished))}</td>'
            f'<td>{html.escape(str(error or ""))}</td>'
            f'<td>{html.escape(str(bilingual or ""))}</td>'
            f'<td>{html.escape(str(dubbed or ""))}</td>'
            '</tr>'
        )
    jobs_html = '\n'.join(jtrs) if jtrs else '<tr><td colspan="9">No jobs</td></tr>'
    msg_html = f'<p style="color:#0b6;">{html.escape(msg)}</p>' if msg else ''

    refresh_link = f'/?action=refresh&{query_filter}'

    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Discovery Dashboard</title>
  <style>
    body {{ font-family: -apple-system, Segoe UI, Roboto, sans-serif; margin: 18px; }}
    h1 {{ margin: 0 0 12px; }}
    h2 {{ margin-top: 26px; }}
    form {{ margin-bottom: 14px; display: flex; gap: 8px; flex-wrap: wrap; }}
    input, button {{ padding: 6px 8px; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
    th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; vertical-align: top; }}
    th {{ background: #f7f7f7; }}
    a {{ color: #0056d6; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .actions {{ margin-bottom: 12px; display: flex; gap: 10px; align-items: center; }}
  </style>
</head>
<body>
  <h1>YouTube AI Discovery</h1>
  {msg_html}
  <div class="actions">
    <a href="{refresh_link}">手动刷新抓取</a>
  </div>
  <form method="get" action="/">
    <label>Min Score <input type="number" step="0.1" name="min_score" value="{min_score}" /></label>
    <label>Language Prefix <input name="lang" value="{html.escape(language)}" placeholder="en" /></label>
    <label>Limit <input type="number" name="limit" value="{limit}" /></label>
    <button type="submit">Filter</button>
  </form>
  <table>
    <thead>
      <tr>
        <th>Video ID</th><th>Title</th><th>Channel</th><th>Published</th><th>Lang</th>
        <th>Views</th><th>Comments</th><th>Score</th><th>Action</th>
      </tr>
    </thead>
    <tbody>{rows_html}</tbody>
  </table>

  <h2>Processing Jobs</h2>
  <table>
    <thead>
      <tr>
        <th>ID</th><th>Video ID</th><th>Status</th><th>Created</th><th>Started</th><th>Finished</th>
        <th>Error</th><th>Bilingual Output</th><th>Dubbed Output</th>
      </tr>
    </thead>
    <tbody>{jobs_html}</tbody>
  </table>
</body>
</html>
"""


def run_server(host: str, port: int, db_path: Path) -> None:
    repo_root = Path(__file__).resolve().parent
    init_db(db_path)

    worker = threading.Thread(target=_worker_loop, args=(db_path, repo_root), daemon=True)
    worker.start()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path not in {'/', ''}:
                self.send_response(404)
                self.end_headers()
                return

            q = parse_qs(parsed.query)
            min_score = float((q.get('min_score') or ['0'])[0] or 0)
            language = (q.get('lang') or ['en'])[0].strip()
            limit = int((q.get('limit') or ['100'])[0] or 100)
            msg = ''

            action = (q.get('action') or [''])[0].strip().lower()
            if action == 'refresh':
                try:
                    _raw, selected = run_discovery_once()
                    upsert_candidates(db_path, selected)
                    msg = f'刷新完成，新增/更新 {len(selected)} 条'
                except Exception as exc:
                    msg = f'刷新失败: {exc}'
            elif action == 'enqueue':
                video_id = (q.get('video_id') or [''])[0].strip()
                ok, m = enqueue_processing_job(db_path, video_id)
                msg = m if ok else f'入队失败: {m}'

            rows = _query_rows(db_path, min_score=min_score, language_prefix=language, limit=limit)
            jobs = list_jobs(db_path, limit=40)
            page = _html_page(rows, jobs, min_score=min_score, language=language, limit=limit, msg=msg).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(page)))
            self.end_headers()
            self.wfile.write(page)

        def log_message(self, fmt: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer((host, port), Handler)
    print(f'Dashboard running: http://{host}:{port}')
    print(f'Database: {db_path}')
    print('Worker: started (polling pending jobs)')
    server.serve_forever()


def main() -> None:
    args = parse_args()
    db_path = Path(args.db_path).expanduser().resolve() if args.db_path else settings.discovery_db_path.resolve()
    run_server(args.host, args.port, db_path)


if __name__ == '__main__':
    main()


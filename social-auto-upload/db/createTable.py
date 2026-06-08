import sqlite3
import os

# 数据库文件路径
db_file = os.path.join(os.path.dirname(__file__), 'database.db')

# 如果数据库已存在，则删除旧的表（可选）
# if os.path.exists(db_file):
#     os.remove(db_file)

# 连接到SQLite数据库（如果文件不存在则会自动创建）
conn = sqlite3.connect(db_file)
cursor = conn.cursor()

# 创建账号记录表
cursor.execute('''
CREATE TABLE IF NOT EXISTS user_info (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type INTEGER NOT NULL,
    filePath TEXT NOT NULL,  -- 存储文件路径
    userName TEXT NOT NULL,
    status INTEGER DEFAULT 0
)
''')

# 创建文件记录表
cursor.execute('''CREATE TABLE IF NOT EXISTS file_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT, -- 唯一标识每条记录
    filename TEXT NOT NULL,               -- 文件名
    filesize REAL,                     -- 文件大小（单位：MB）
    upload_time DATETIME DEFAULT CURRENT_TIMESTAMP, -- 上传时间，默认当前时间
    file_path TEXT                        -- 文件路径
)
''')

# ── HK puller tables ──

cursor.execute('''
CREATE TABLE IF NOT EXISTS hk_videos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT '',
    view_count INTEGER DEFAULT 0,
    score REAL DEFAULT 0.0,
    download_status TEXT DEFAULT 'pending',
    file_path TEXT DEFAULT '',
    file_size INTEGER DEFAULT 0,
    thumbnail_path TEXT DEFAULT '',
    hk_downloaded_at TEXT DEFAULT '',
    local_downloaded_at TEXT DEFAULT '',
    upload_status TEXT DEFAULT 'pending',
    uploaded_at TEXT DEFAULT '',
    upload_platform TEXT DEFAULT '',
    upload_account TEXT DEFAULT '',
    error TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now')),
    synced_at TEXT DEFAULT (datetime('now'))
)
''')

cursor.execute('CREATE INDEX IF NOT EXISTS idx_hk_videos_status ON hk_videos(download_status)')
cursor.execute('CREATE INDEX IF NOT EXISTS idx_hk_videos_category ON hk_videos(category)')
cursor.execute('CREATE INDEX IF NOT EXISTS idx_hk_videos_score ON hk_videos(score DESC)')

# ── migrate: add upload columns for existing tables ──

def _add_col(table: str, col: str, definition: str) -> None:
    existing = {r[1] for r in cursor.execute(f"PRAGMA table_info({table})").fetchall()}
    if col not in existing:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col} {definition}")

_add_col('hk_videos', 'upload_status', "TEXT DEFAULT 'pending'")
_add_col('hk_videos', 'uploaded_at', "TEXT DEFAULT ''")
_add_col('hk_videos', 'upload_platform', "TEXT DEFAULT ''")
_add_col('hk_videos', 'upload_account', "TEXT DEFAULT ''")
cursor.execute('CREATE INDEX IF NOT EXISTS idx_hk_videos_upload ON hk_videos(upload_status)')

cursor.execute('''
CREATE TABLE IF NOT EXISTS hk_sync_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    synced_at TEXT DEFAULT (datetime('now')),
    new_count INTEGER DEFAULT 0,
    downloaded_count INTEGER DEFAULT 0,
    error TEXT DEFAULT ''
)
''')


# 提交更改
conn.commit()
print("✅ 表创建成功（含 hk_videos / hk_sync_log）")
# 关闭连接
conn.close()
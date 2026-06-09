from pathlib import Path

BASE_DIR = Path(__file__).parent.resolve()
XHS_SERVER = "http://127.0.0.1:11901"  # only used by xhs-related flows
LOCAL_CHROME_PATH = ""  # optional, e.g. C:/Program Files/Google/Chrome/Application/chrome.exe
LOCAL_CHROME_HEADLESS = True  # default headless behavior for uploader/examples
DEBUG_MODE = True  # default debug behavior

# ── HK server pull configuration ──
HK_SERVER_URL = "http://103.118.198.49:8503"  # HK hk-server API address
HK_API_TOKEN = ""                               # Bearer token; empty = no auth
HK_POLL_INTERVAL_MINUTES = 30                   # background poll interval
HK_AUTO_DOWNLOAD = True                         # automatically download new videos
HK_DOWNLOAD_DIRNAME = "hk"                      # subdirectory under videoFile/
HK_DOWNLOAD_INTERVAL_SEC = 180                  # seconds between each download

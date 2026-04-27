from pathlib import Path

HOME = Path.home()

CORTEX_DIR = HOME / ".snowflake" / "cortex"
CONVERSATIONS_DIR = CORTEX_DIR / "conversations"

ARCHIVE_DIR = CORTEX_DIR / "archive"
ARCHIVE_DIR.mkdir(exist_ok=True)
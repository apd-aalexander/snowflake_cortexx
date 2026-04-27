import json
from pathlib import Path
import shutil
from config import CONVERSATIONS_DIR, ARCHIVE_DIR


def get_all_sessions():
    sessions = []

    for file in CONVERSATIONS_DIR.glob("*.json"):
        try:
            with open(file, encoding="utf-8") as f:
                data = json.load(f)

            sessions.append({
                "id": file.stem,
                "title": data.get("title", "Untitled"),
                "preview": extract_preview(data),
                "updated": data.get("last_updated"),
                "path": file
            })
        except Exception as e:
            print(f"Error reading {file}: {e}")

    return sorted(sessions, key=lambda x: x["updated"] or "", reverse=True)


def get_session(session_id):
    file = CONVERSATIONS_DIR / f"{session_id}.json"

    if not file.exists():
        raise ValueError("Session not found")

    with open(file, encoding="utf-8") as f:
        return json.load(f)


def rename_session(session_id, new_title):
    file = CONVERSATIONS_DIR / f"{session_id}.json"

    with open(file, encoding="utf-8") as f:
        data = json.load(f)

    data["title"] = new_title

    with open(file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def archive_session(session_id):
    src = CONVERSATIONS_DIR / f"{session_id}.json"
    dst = ARCHIVE_DIR / f"{session_id}.json"

    if src.exists():
        shutil.move(src, dst)

def extract_preview(data):
    try:
        for msg in data.get("history", []):
            if msg.get("role") == "user":
                for block in msg.get("content", []):
                    if block.get("type") == "text":
                        text = block.get("text", "").strip()

                        # skip system junk
                        if text.startswith("<system-reminder"):
                            continue

                        return text[:80]
    except Exception:
        pass

    return ""
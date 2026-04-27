import json
from config import CONVERSATIONS_DIR


def search_sessions(keyword):
    results = []

    for file in CONVERSATIONS_DIR.glob("*.json"):
        try:
            with open(file, encoding="utf-8") as f:
                data = json.load(f)

            content = json.dumps(data).lower()

            if keyword.lower() in content:
                results.append({
                    "id": file.stem,
                    "title": data.get("title", "Untitled"),
                })
        except Exception:
            continue

    return results
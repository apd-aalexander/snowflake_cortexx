import typer
from sessions import (
    get_all_sessions,
    rename_session,
    archive_session
)
from search import search_sessions
from utils import run_cortex_resume, run_cortex_continue

app = typer.Typer()


@app.command()
def list():
    sessions = get_all_sessions()

    for i, s in enumerate(sessions):
        preview = s.get("preview", "")
        print(f"{i+1}. {s['title']}")
        if preview:
            print(f"   → {preview}")


@app.command()
def open(index: int = None):
    sessions = get_all_sessions()

    if index is None:
        from utils import pick_session_with_fzf
        session = pick_session_with_fzf(sessions)
        if not session:
            return
    else:
        session = sessions[index - 1]

    run_cortex_resume(session["id"])


@app.command()
def last():
    run_cortex_continue()


@app.command()
def rename(index: int, title: str):
    sessions = get_all_sessions()
    session = sessions[index - 1]

    rename_session(session["id"], title)
    print("Renamed")


@app.command()
def delete(index: int):
    sessions = get_all_sessions()
    session = sessions[index - 1]

    archive_session(session["id"])
    print("Archived")


@app.command()
def search(keyword: str):
    results = search_sessions(keyword)

    for r in results:
        print(f"{r['title']} ({r['id']})")


if __name__ == "__main__":
    app()
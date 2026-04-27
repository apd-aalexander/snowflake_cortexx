import typer
from sessions import (
    get_all_sessions,
    rename_session,
    delete_session
)
from search import search_sessions
from utils import run_cortex_resume, run_cortex_continue

app = typer.Typer()


@app.command()
def list():
    sessions = get_all_sessions()

    for i, s in enumerate(sessions):
        print(f"{i+1}. {s['title']} ({s['id']})")


@app.command()
def open(index: int):
    sessions = get_all_sessions()

    try:
        session = sessions[index - 1]
        run_cortex_resume(session["id"])
    except IndexError:
        print("Invalid selection")


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

    delete_session(session["id"])
    print("Deleted")


@app.command()
def search(keyword: str):
    results = search_sessions(keyword)

    for r in results:
        print(f"{r['title']} ({r['id']})")


if __name__ == "__main__":
    app()
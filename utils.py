import subprocess


def run_cortex_resume(session_id):
    subprocess.run(["cortex", "--resume", session_id])


def run_cortex_continue():
    subprocess.run(["cortex", "--continue"])

def pick_session_with_fzf(sessions):
    lines = [
        f"{i+1}. {s['title']} :: {s.get('preview','')}"
        for i, s in enumerate(sessions)
    ]

    proc = subprocess.Popen(
        ["fzf"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True
    )

    selected, _ = proc.communicate("\n".join(lines))

    if not selected.strip():
        return None

    index = int(selected.split(".")[0]) - 1
    return sessions[index]
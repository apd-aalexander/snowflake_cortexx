import subprocess


def run_cortex_resume(session_id):
    subprocess.run(["cortex", "--resume", session_id])


def run_cortex_continue():
    subprocess.run(["cortex", "--continue"])
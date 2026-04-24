"""Lança o JARVIS como processo independente do terminal."""
import subprocess, sys, os

jarvis_dir = os.path.dirname(os.path.abspath(__file__))
python = sys.executable

proc = subprocess.Popen(
    [python, "hyperagent/run.py"],
    cwd=jarvis_dir,
    creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
    close_fds=True,
)
print(f"JARVIS iniciado! PID={proc.pid}  ->  http://localhost:8000")

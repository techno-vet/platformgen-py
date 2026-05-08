"""Restart the PlatformGen UI process. Run inside the runtime container."""
import os
import signal
import subprocess
import time

from platformgen.runtime import cli_name, state_dir


CLI_NAME = cli_name()
PROCESS_MARKERS = (
    f"{CLI_NAME} start",
    "python3 -m platformgen start",
    "python -m platformgen start",
    "python3 -m auger start",
    "python -m auger start",
)

for line in os.popen('ps aux').readlines():
    if any(marker in line for marker in PROCESS_MARKERS) and 'grep' not in line and 'restart' not in line:
        pid = int(line.split()[1])
        print(f"Stopping {CLI_NAME} start PID {pid}")
        os.kill(pid, signal.SIGTERM)
        time.sleep(2)
        break

log_path = state_dir() / 'ui.log'
env = dict(os.environ)
env.setdefault('DISPLAY', ':1')
log_path.parent.mkdir(parents=True, exist_ok=True)
log = open(log_path, 'a')
p = subprocess.Popen(
    [CLI_NAME, 'start'], env=env,
    stdout=log, stderr=log,
    start_new_session=True
)
print(f"Started {CLI_NAME} start PID {p.pid} — logs: {log_path}")

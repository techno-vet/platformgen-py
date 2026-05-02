"""Restart the auger start UI process. Run inside container."""
import os, signal, subprocess, time

for line in os.popen('ps aux').readlines():
    if 'auger start' in line and 'grep' not in line and 'restart' not in line:
        pid = int(line.split()[1])
        print(f"Stopping auger start PID {pid}")
        os.kill(pid, signal.SIGTERM)
        time.sleep(2)
        break

log_path = os.path.expanduser('~/.auger/ui.log')
env = dict(os.environ)
env.setdefault('DISPLAY', ':1')
env.setdefault('HOME', '/home/auger')
log = open(log_path, 'a')
p = subprocess.Popen(
    ['auger', 'start'], env=env,
    stdout=log, stderr=log,
    start_new_session=True
)
print(f"Started auger start PID {p.pid} — logs: {log_path}")

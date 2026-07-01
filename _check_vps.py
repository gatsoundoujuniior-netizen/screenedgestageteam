import paramiko, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("195.200.14.241", username="root", password="Abdelghan#2026", timeout=40)

cmds = [
    "ps aux | grep -E 'streamlit|pep_collector' | grep -v grep",
    "tail -30 /root/screen_edge/dashboard.log",
]
for cmd in cmds:
    print(f"\n=== {cmd} ===")
    _, o, e = ssh.exec_command(cmd)
    print(o.read().decode("utf-8", errors="replace"))
    err = e.read().decode("utf-8", errors="replace")
    if err.strip(): print("STDERR:", err)

ssh.close()

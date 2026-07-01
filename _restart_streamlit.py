import paramiko, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("195.200.14.241", username="root", password="Abdelghan#2026", timeout=20)

ssh.exec_command("pkill -f streamlit 2>/dev/null; sleep 2")
import time; time.sleep(3)

ssh.exec_command(
    "cd /root/screen_edge && PG_LOCAL=true nohup streamlit run dashboard_pep.py "
    "--server.port 8501 --server.headless true "
    "> /root/screen_edge/streamlit.log 2>&1 &"
)
time.sleep(4)

_, o, _ = ssh.exec_command("pgrep -a streamlit | head -3")
out = o.read().decode("utf-8", errors="replace").strip()
print("Process:", out or "non démarré")

_, o, _ = ssh.exec_command("tail -5 /root/screen_edge/streamlit.log 2>/dev/null")
print("Log:", o.read().decode("utf-8", errors="replace"))
ssh.close()

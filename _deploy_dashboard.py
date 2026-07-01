import paramiko, time, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("195.200.14.241", username="root", password="Abdelghan#2026", timeout=40)

sftp = ssh.open_sftp()
sftp.put(r"C:\Users\pc\Downloads\Screen_edge\agent_aml_pep\dashboard_pep.py", "/root/screen_edge/dashboard_pep.py")
print("Upload dashboard_pep.py OK")
sftp.close()

ssh.exec_command("pkill -f 'dashboard_pep.py' 2>/dev/null")
time.sleep(2)

ssh.exec_command(
    "cd /root/screen_edge && "
    "nohup python3 -m streamlit run dashboard_pep.py "
    "--server.port 8501 --server.address 0.0.0.0 "
    "> /root/screen_edge/dashboard.log 2>&1 &"
)
time.sleep(8)

_, o, _ = ssh.exec_command("ps aux | grep streamlit | grep -v grep | head -2")
procs = o.read().decode("utf-8", errors="replace").strip()
print("Streamlit:", "OK — " + procs[:80] if procs else "AUCUN PROCESS")

_, o, _ = ssh.exec_command("tail -15 /root/screen_edge/dashboard.log")
log = o.read().decode("utf-8", errors="replace")
print("Log:\n", log)

ssh.close()

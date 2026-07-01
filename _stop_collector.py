import paramiko, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("195.200.14.241", username="root", password="Abdelghan#2026", timeout=40)

_, o, _ = ssh.exec_command("pkill -f 'pep_collector.py'; echo 'Collector arrêté'")
print(o.read().decode("utf-8", errors="replace"))

_, o, _ = ssh.exec_command("ps aux | grep pep_collector | grep -v grep || echo 'Aucun process collector'")
print(o.read().decode("utf-8", errors="replace"))

ssh.close()

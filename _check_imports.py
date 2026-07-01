import paramiko, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("195.200.14.241", username="root", password="Abdelghan#2026", timeout=40)

_, o, _ = ssh.exec_command("grep -n 'def node_' /root/screen_edge/pep_agent.py 2>/dev/null")
print("Fonctions node_ dans pep_agent.py:")
print(o.read().decode("utf-8", errors="replace"))

_, o, _ = ssh.exec_command("cat /root/screen_edge/test_15.py")
print("\ntest_15.py:")
print(o.read().decode("utf-8", errors="replace")[:2000])

ssh.close()

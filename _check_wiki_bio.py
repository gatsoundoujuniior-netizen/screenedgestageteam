import paramiko, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("195.200.14.241", username="root", password="Abdelghan#2026", timeout=40)

# Lire le bloc _bio_incomplet actuel sur le VPS
_, o, _ = ssh.exec_command("sed -n '1155,1260p' /root/screen_edge/pep_agent.py")
print("Bloc _bio_incomplet actuel (lignes 1155-1260):")
print(o.read().decode("utf-8", errors="replace"))

ssh.close()

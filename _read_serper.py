import paramiko, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("195.200.14.241", username="root", password="Abdelghan#2026", timeout=40)

# Lire rechercher_google() complète
_, o, _ = ssh.exec_command("sed -n '668,760p' /root/screen_edge/search_tools.py")
print("=== rechercher_google() ===")
print(o.read().decode("utf-8", errors="replace"))

# Lire la partie Wikipedia slug dans rechercher_pep()
_, o, _ = ssh.exec_command("sed -n '865,930p' /root/screen_edge/search_tools.py")
print("=== rechercher_pep() début ===")
print(o.read().decode("utf-8", errors="replace"))

# Lire rechercher_opensanctions()
_, o, _ = ssh.exec_command("sed -n '763,860p' /root/screen_edge/search_tools.py")
print("=== rechercher_opensanctions() ===")
print(o.read().decode("utf-8", errors="replace"))

ssh.close()

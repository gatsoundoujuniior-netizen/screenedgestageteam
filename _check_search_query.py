import paramiko, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("195.200.14.241", username="root", password="Abdelghan#2026", timeout=40)

# Voir comment rechercher_google() construit sa requête
_, o, _ = ssh.exec_command("grep -n 'def rechercher_google\\|srsearch\\|query\\|payload\\|nom_complet\\|pertinent\\|résultat pertinent' /root/screen_edge/search_tools.py 2>/dev/null")
print("=== rechercher_google() — construction requête ===")
print(o.read().decode("utf-8", errors="replace"))

ssh.close()

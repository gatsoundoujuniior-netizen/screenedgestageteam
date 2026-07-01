import paramiko, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("195.200.14.241", username="root", password="Abdelghan#2026", timeout=40)

# Lire la définition de verifier_pep et l'init du state
_, o, _ = ssh.exec_command("sed -n '2120,2200p' /root/screen_edge/pep_agent.py")
print("verifier_pep + state init:")
print(o.read().decode("utf-8", errors="replace"))

# Voir comment pep_collector appelle verifier_pep
_, o, _ = ssh.exec_command("sed -n '1295,1345p' /root/screen_edge/pep_collector.py")
print("\nAppel dans pep_collector:")
print(o.read().decode("utf-8", errors="replace"))

ssh.close()

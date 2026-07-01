import paramiko, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("195.200.14.241", username="root", password="Abdelghan#2026", timeout=40)

# Voir comment pep_collector appelle pep_agent
_, o, _ = ssh.exec_command("grep -n 'import\\|node_\\|PEPState\\|TypedDict' /root/screen_edge/pep_collector.py 2>/dev/null | head -30")
print("pep_collector imports et appels:")
print(o.read().decode("utf-8", errors="replace"))

# Voir la définition PEPState dans pep_agent.py
_, o, _ = ssh.exec_command("grep -n 'PEPState\\|TypedDict\\|class PEP' /root/screen_edge/pep_agent.py 2>/dev/null | head -20")
print("\nPEPState dans pep_agent.py:")
print(o.read().decode("utf-8", errors="replace"))

ssh.close()

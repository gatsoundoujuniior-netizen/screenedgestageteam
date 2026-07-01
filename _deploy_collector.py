import paramiko, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("195.200.14.241", username="root", password="Abdelghan#2026", timeout=40)

sftp = ssh.open_sftp()
sftp.put(r"C:\Users\pc\Downloads\Screen_edge\agent_aml_pep\pep_collector.py", "/root/screen_edge/pep_collector.py")
print("Upload pep_collector.py OK")
sftp.close()

# Vérifier que --track-b-only n'existe plus
_, o, _ = ssh.exec_command("cd /root/screen_edge && python3 pep_collector.py --help")
print(o.read().decode("utf-8", errors="replace"))

ssh.close()

import paramiko, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("195.200.14.241", username="root", password="Abdelghan#2026", timeout=40)

sftp = ssh.open_sftp()
sftp.put(r"C:\Users\pc\Downloads\Screen_edge\agent_aml_pep\.env", "/root/screen_edge/.env")
print("Upload .env OK")
sftp.close()

# Vérifier que GROQ_KEY_2 est bien là (sans afficher la valeur)
_, o, _ = ssh.exec_command("grep -c 'GROQ_KEY_2' /root/screen_edge/.env")
count = o.read().decode().strip()
print(f"GROQ_KEY_2 trouvé : {'OUI' if count == '1' else 'NON'}")

# Vérifier les clés présentes (noms seulement, pas les valeurs)
_, o, _ = ssh.exec_command("grep -oP '^[A-Z_]+(?==)' /root/screen_edge/.env")
print("Variables dans .env :")
for line in o.read().decode("utf-8", errors="replace").strip().split("\n"):
    print(f"  {line}")

ssh.close()

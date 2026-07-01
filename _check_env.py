import paramiko, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("195.200.14.241", username="root", password="Abdelghan#2026", timeout=40)

# Vérifier les clés Groq (noms seulement)
_, o, _ = ssh.exec_command("grep -o '^GROQ[^=]*' /root/screen_edge/.env")
groq_keys = o.read().decode().strip()
print("Clés Groq présentes :", groq_keys if groq_keys else "AUCUNE")

# Tester que pep_agent charge bien Groq-2
_, o, e = ssh.exec_command("""cd /root/screen_edge && python3 -c "
import os; from dotenv import load_dotenv; load_dotenv()
k1 = os.getenv('GROQ_KEY_1','')
k2 = os.getenv('GROQ_KEY_2','')
k3 = os.getenv('GROQ_KEY_3','')
print('GROQ_KEY_1:', 'OK ('+k1[:8]+'...)' if k1 else 'ABSENT')
print('GROQ_KEY_2:', 'OK ('+k2[:8]+'...)' if k2 else 'ABSENT')
print('GROQ_KEY_3:', 'OK ('+k3[:8]+'...)' if k3 else 'ABSENT')
"
""")
print(o.read().decode("utf-8", errors="replace"))

ssh.close()

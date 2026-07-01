import paramiko, sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("195.200.14.241", username="root", password="Abdelghan#2026", timeout=20)

# Écrire le script sur VPS
sftp = ssh.open_sftp()
script_content = '''import sys
sys.path.insert(0, '/root/screen_edge')
from pep_agent import verifier_pep
r = verifier_pep("Fatou", "Diallo", stocker=False)
print("RESULT_START")
print(f"est_pep     : {r.est_pep}")
print(f"code_iso    : {r.code_iso}")
print(f"pays        : {r.pays}")
print(f"fonction    : {r.fonction}")
print(f"raisonnement: {(r.raisonnement or '')[:150]}")
print("RESULT_END")
'''
with sftp.open('/tmp/test_fatou_script.py', 'w') as f:
    f.write(script_content)
sftp.close()

# Lancer en background
ssh.exec_command("cd /root/screen_edge && PG_LOCAL=true nohup python3 /tmp/test_fatou_script.py > /tmp/test_fatou.out 2>&1 &")
print("Test Fatou Diallo lancé...")
ssh.close()

# Attendre et lire résultat
for i in range(20):
    time.sleep(15)
    ssh2 = paramiko.SSHClient()
    ssh2.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh2.connect("195.200.14.241", username="root", password="Abdelghan#2026", timeout=20)
    _, o, _ = ssh2.exec_command("cat /tmp/test_fatou.out 2>/dev/null")
    out = o.read().decode("utf-8", errors="replace")
    _, o2, _ = ssh2.exec_command("pgrep -f 'test_fatou_script' | wc -l")
    running = o2.read().decode().strip()
    ssh2.close()
    if "RESULT_END" in out:
        print(f"\nRésultat après {(i+1)*15}s :")
        print(out)
        break
    print(f"  [{(i+1)*15}s] En cours... ({len(out)} chars)")
else:
    print("Timeout — résultat partiel :")
    print(out[-2000:])

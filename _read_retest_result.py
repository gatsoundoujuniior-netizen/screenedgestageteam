import paramiko, sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# Poll jusqu'à ce que le fichier de résultat soit complet (contient "Confirmes KO")
for attempt in range(20):
    time.sleep(10)
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh.connect("195.200.14.241", username="root", password="Abdelghan#2026", timeout=20)
        _, o, _ = ssh.exec_command("cat /tmp/_retest_result.txt 2>/dev/null")
        content = o.read().decode("utf-8", errors="replace")
        ssh.close()
        if "Confirmes KO" in content:
            print(content)
            break
        else:
            print(f"[{attempt+1}] En cours... ({len(content)} chars)", flush=True)
    except Exception as e:
        print(f"[{attempt+1}] Erreur connexion: {e}", flush=True)
else:
    print("Timeout — résultat incomplet")

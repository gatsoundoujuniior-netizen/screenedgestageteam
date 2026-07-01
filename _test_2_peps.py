import paramiko, sys, io, textwrap
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("195.200.14.241", username="root", password="Abdelghan#2026", timeout=40)

PERSONNES = [
    ("patrice", "talon"),
    ("fare",    "gnassimbe"),
]

for prenom, nom in PERSONNES:
    SCRIPT = textwrap.dedent(f"""
        import sys
        sys.path.insert(0, '/root/screen_edge')
        from pep_agent import verifier_pep
        print("\\n{'='*60}")
        print("TEST : {prenom} {nom}")
        print('='*60)
        r = verifier_pep("{prenom}", "{nom}", stocker=False)
        print("\\n--- RÉSULTAT ---")
        for k, v in r.items():
            print(f"  {{k}}: {{v}}")
    """)

    sftp = ssh.open_sftp()
    with sftp.open("/tmp/_test_pep_tmp.py", "w") as f:
        f.write(SCRIPT)
    sftp.close()

    print(f"\n{'='*60}")
    print(f"Lancement : {prenom} {nom}")
    print('='*60)
    _, stdout, stderr = ssh.exec_command(
        "cd /root/screen_edge && python3 /tmp/_test_pep_tmp.py 2>&1",
        timeout=180
    )
    stdout.channel.settimeout(180)
    print(stdout.read().decode("utf-8", errors="replace"))

ssh.close()

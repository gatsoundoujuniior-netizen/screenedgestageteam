import paramiko, sys, io, textwrap
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("195.200.14.241", username="root", password="Abdelghan#2026", timeout=40)

PERSONNES = [("patrice", "talon"), ("fare", "gnassimbe")]

for prenom, nom in PERSONNES:
    SCRIPT = textwrap.dedent(f"""
        import sys
        sys.path.insert(0, '/root/screen_edge')
        from pep_agent import verifier_pep
        r = verifier_pep("{prenom}", "{nom}", stocker=False)
        print("\\n{'='*60}")
        print("CHAMPS : {prenom} {nom}")
        print('='*60)
        d = r.model_dump() if hasattr(r, 'model_dump') else vars(r)
        for k, v in d.items():
            print(f"  {{k:30s}}: {{v}}")
    """)
    sftp = ssh.open_sftp()
    with sftp.open("/tmp/_show_fields.py", "w") as f:
        f.write(SCRIPT)
    sftp.close()
    _, stdout, _ = ssh.exec_command(
        "cd /root/screen_edge && python3 /tmp/_show_fields.py 2>&1", timeout=180
    )
    stdout.channel.settimeout(180)
    out = stdout.read().decode("utf-8", errors="replace")
    # Afficher uniquement la partie CHAMPS (pas tout le pipeline)
    if "CHAMPS :" in out:
        print(out[out.index("CHAMPS :"):])
    else:
        print(out[-3000:])

ssh.close()

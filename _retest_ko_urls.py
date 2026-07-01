import paramiko, sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("195.200.14.241", username="root", password="Abdelghan#2026", timeout=40)

SCRIPT = r"""
import requests, warnings, sys
warnings.filterwarnings('ignore')

KO_DOMAINES = {
    "MA": ["bkam.ma", "ammc.ma"],
    "DZ": ["el-mouradia.dz", "apn.dz", "senat.dz", "bank-of-algeria.dz", "ctrf.gov.dz"],
    "TN": ["gouvernement.tn", "bct.gov.tn", "jo.gov.tn"],
    "LY": ["gov.ly", "hor.ly", "fiulibya.gov.ly"],
    "CI": ["assemblee-nationale.ci", "centif-ci.ci", "jo.ci"],
    "ML": ["primature.gov.ml"],
    "BF": ["aib.bf"],
    "NE": ["presidence.ne", "gouv.ne"],
    "BJ": ["jo.gouv.bj", "abp.bj", "benin-news.com"],
    "GW": ["gov.gw"],
}

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"
HEADERS = {"User-Agent": UA}

out = open("/tmp/_retest_result.txt", "w")

def log(msg):
    print(msg, flush=True)
    out.write(msg + "\n")

log("=== RETEST DOMAINES RETIRES ===\n")
recuperables = []
confirmes_ko = []

for pays, domaines in KO_DOMAINES.items():
    for d in domaines:
        res = "KO"
        for scheme in ("https", "http"):
            try:
                r = requests.get(f"{scheme}://{d}", headers=HEADERS, timeout=7,
                                 allow_redirects=True, verify=False)
                if r.status_code < 500:
                    res = f"OK {r.status_code} ({scheme})"
                    break
            except Exception:
                pass
        status = "RECUPERE" if res.startswith("OK") else "KO"
        log(f"  {status}  [{pays}] {d} — {res}")
        if res.startswith("OK"):
            recuperables.append((pays, d, res))
        else:
            confirmes_ko.append((pays, d))

log(f"\n=== RÉSUMÉ ===")
log(f"Recuperables ({len(recuperables)}):")
for pays, d, res in recuperables:
    log(f"  [{pays}] {d} — {res}")
log(f"Confirmes KO ({len(confirmes_ko)}):")
for pays, d in confirmes_ko:
    log(f"  [{pays}] {d}")
out.close()
"""

sftp = ssh.open_sftp()
with sftp.open("/tmp/_retest_ko.py", "w") as f:
    f.write(SCRIPT)
sftp.close()

# Lancer en background sur le VPS
ssh.exec_command("nohup python3 /tmp/_retest_ko.py > /tmp/_retest_stdout.txt 2>&1 &")
print("Script lancé en background sur VPS.")
print("Attendre ~90s puis lire /tmp/_retest_result.txt")
ssh.close()

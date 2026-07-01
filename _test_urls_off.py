import paramiko, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect("195.200.14.241", username="root", password="Abdelghan#2026", timeout=40)

SCRIPT = r"""
import requests, warnings
warnings.filterwarnings('ignore')
import sys
sys.stdout.reconfigure(line_buffering=True)

DOMAINES_TEST = {
    "MA": ["maroc.ma","cg.gov.ma","parlement.ma","chambredesrepresentants.ma","chambredesconseillers.ma","bkam.ma","utrf.gov.ma","ammc.ma","acaps.ma"],
    "DZ": ["el-mouradia.dz","premier-ministre.gov.dz","apn.dz","senat.dz","bank-of-algeria.dz","ctrf.gov.dz","joradp.dz"],
    "TN": ["carthage.tn","gouvernement.tn","arp.tn","bct.gov.tn","ctaf.gov.tn","jo.gov.tn"],
    "LY": ["gov.ly","hor.ly","cbl.gov.ly","fiulibya.gov.ly"],
    "SN": ["presidence.sn"],
    "CI": ["presidence.ci","gouv.ci","assemblee-nationale.ci","senat.ci","centif-ci.ci","jo.ci","aip.ci","pulse.ci"],
    "ML": ["koulouba.ml","primature.gov.ml","amap.ml"],
    "BF": ["gouvernement.gov.bf","sig.gov.bf","centif.bf","aib.bf","fasonet.bf","presidencedufaso.bf"],
    "NE": ["presidence.ne","gouv.ne","centif.ne","anp.ne"],
    "TG": ["presidenceduconseil.gouv.tg","togo.gouv.tg","assemblee-nationale.tg","centif.tg","jo.gouv.tg","atop.tg","togofirst.com"],
    "BJ": ["presidence.bj","gouv.bj","assemblee-nationale.bj","centif.bj","jo.gouv.bj","abp.bj","portailinfo.bj","benin-news.com"],
    "GW": ["gov.gw"],
    "GN": ["presidence.gov.gn","gouvernement.gov.gn","bcrg.org","agpguinee.com"],
}

HEADERS = {"User-Agent":"Mozilla/5.0 (compatible; ScreenEdge/1.0)"}

print("=== TEST DOMAINES OFFICIELS ===\n")
ok_list = {}
ko_list = {}

for pays, domaines in DOMAINES_TEST.items():
    ok_list[pays] = []
    ko_list[pays] = []
    for d in domaines:
        url = f"https://{d}"
        try:
            r = requests.get(url, headers=HEADERS, timeout=8, allow_redirects=True, verify=False)
            if r.status_code < 500:
                ok_list[pays].append(d)
                print(f"  OK  [{pays}] {d} — {r.status_code}")
            else:
                ko_list[pays].append(d)
                print(f"  KO  [{pays}] {d} — {r.status_code}")
        except Exception as e:
            ko_list[pays].append(d)
            print(f"  KO  [{pays}] {d} — {str(e)[:70]}")

print("\n=== RÉSUMÉ ===")
for pays in DOMAINES_TEST:
    print(f"[{pays}] OK={ok_list[pays]} | KO={ko_list[pays]}")
"""

sftp = ssh.open_sftp()
with sftp.open("/tmp/_test_urls.py", "w") as f:
    f.write(SCRIPT)
sftp.close()

print("Script uploadé, test en cours...")
_, stdout, stderr = ssh.exec_command("python3 /tmp/_test_urls.py 2>&1", timeout=120)
print(stdout.read().decode("utf-8", errors="replace"))
err = stderr.read().decode("utf-8", errors="replace")
if err:
    print("STDERR:", err[:300])
ssh.close()

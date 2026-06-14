"""Teste les domaines racine pour savoir lesquels sont en vie."""
import sys, requests, warnings
warnings.filterwarnings("ignore")
sys.stdout.reconfigure(encoding="utf-8")

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120"}

# Domaines racine à tester + alternatives connues
DOMAINES = {
    "MA": [
        ("parlement",      "https://www.chambredesrepresentants.ma"),
        ("gouvernement",   "https://www.cg.gov.ma"),
        ("gouvernement2",  "https://www.maroc.ma/fr/gouvernement"),
        ("bkam",           "https://www.bkam.ma"),
    ],
    "DZ": [
        ("premier-min",    "https://www.premier-ministre.gov.dz"),
        ("parlement",      "https://www.apn.dz"),
        ("banque",         "https://www.bank-of-algeria.dz"),
        ("presidence",     "https://www.el-mouradia.dz"),
    ],
    "TN": [
        ("gouvernement",   "https://www.gouvernement.tn"),
        ("parlement",      "https://www.arp.tn"),
        ("bct",            "https://www.bct.gov.tn"),
        ("presidence",     "https://www.carthage.tn"),
    ],
    "LY": [
        ("gouvernement",   "https://www.gov.ly"),
        ("parlement",      "https://www.hor.ly"),
    ],
    "SN": [
        ("parlement",      "https://www.assemblee-nationale.sn"),
        ("parlement2",     "https://www.assemblee-nationale.sn/deputes"),
    ],
    "CI": [
        ("gouvernement",   "https://www.gouv.ci"),
        ("gouvernement2",  "https://www.gouv.ci/gouvernement"),
        ("parlement",      "https://www.assemblee-nationale.ci"),
        ("presidence",     "https://www.presidence.ci"),
    ],
    "ML": [
        ("primature",      "https://www.primature.gov.ml"),
        ("presidence",     "https://www.koulouba.ml"),
        ("transition",     "https://www.gouvernement.ml"),
    ],
    "BF": [
        ("gouvernement",   "https://www.gouvernement.gov.bf"),
        ("gouvernement2",  "https://www.gouvernement.gov.bf/gouvernement"),
    ],
    "NE": [
        ("gouvernement",   "https://www.gouv.ne"),
        ("presidence",     "https://www.presidence.ne"),
        ("cnsp",           "https://www.gouv.ne/le-gouvernement"),
    ],
    "TG": [
        ("presidence",     "https://www.presidence.gouv.tg"),
        ("presidence2",    "https://www.presidence.gouv.tg/gouvernement"),
        ("gouvernement",   "https://www.gouvernement.gouv.tg"),
    ],
    "BJ": [
        ("gouvernement",   "https://www.gouv.bj"),
        ("gouvernement2",  "https://www.gouv.bj/le-gouvernement"),
        ("presidence",     "https://www.presidence.bj"),
        ("parlement",      "https://www.assemblee-nationale.bj"),
    ],
    "GN": [
        ("banque",         "https://www.bcrg.org"),
        ("banque2",        "https://www.bcrg-guinee.org"),
    ],
}

for code, tests in DOMAINES.items():
    print(f"\n[{code}]")
    for label, url in tests:
        try:
            r = requests.get(url, headers=HEADERS, timeout=10, verify=False)
            chars = len(r.content)
            print(f"  {'✅' if r.status_code == 200 and chars > 500 else '❌'} [{label}] HTTP {r.status_code} — {chars} bytes — {url}")
        except Exception as e:
            print(f"  ❌ [{label}] ERREUR — {str(e)[:55]} — {url}")

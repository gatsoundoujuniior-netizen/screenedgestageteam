"""Trouve les bons chemins sur les domaines vivants."""
import sys, requests, warnings
warnings.filterwarnings("ignore")
sys.stdout.reconfigure(encoding="utf-8")

H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120"}

def test(label, url):
    try:
        r = requests.get(url, headers=H, timeout=10, verify=False)
        ok = r.status_code == 200 and len(r.content) > 1000
        print(f"  {'✅' if ok else '❌'} [{label}] {r.status_code} — {len(r.content)} bytes — {url}")
        return ok
    except Exception as e:
        print(f"  ❌ [{label}] ERREUR — {str(e)[:50]}")
        return False

print("=== MA — Maroc ===")
test("parlement_membres",    "https://www.chambredesrepresentants.ma/fr/les-membres")
test("parlement_deputés",    "https://www.chambredesrepresentants.ma/fr/les-d%C3%A9put%C3%A9s")
test("parlement_root",       "https://www.chambredesrepresentants.ma/fr")
test("gouv_composition",     "https://www.cg.gov.ma/fr/composition-gouvernement")
test("gouv_root",            "https://www.cg.gov.ma/fr")
test("bkam_gouvernance",     "https://www.bkam.ma/Gouvernance/Organes-de-gouvernance")
test("bkam_conseil",         "https://www.bkam.ma/Gouvernance/Conseil-de-Bank-Al-Maghrib")
test("bkam_root",            "https://www.bkam.ma/fr")

print("\n=== DZ — Algérie ===")
test("banque_gouv",          "https://www.bank-of-algeria.dz/fr/content/gouverneurs")
test("banque_direction",     "https://www.bank-of-algeria.dz/fr/gouvernance")
test("banque_root_fr",       "https://www.bank-of-algeria.dz/fr")

print("\n=== TN — Tunisie ===")
test("parlement_membres",    "https://www.arp.tn/fr/membres")
test("parlement_root",       "https://www.arp.tn/fr")
test("presidence_gouv",      "https://www.carthage.tn/gouvernement")
test("presidence_root",      "https://www.carthage.tn/fr")

print("\n=== CI — Côte d'Ivoire ===")
test("gouv_composition",     "https://www.gouv.ci/gouvernement")
test("gouv_composition2",    "https://www.gouv.ci/index.php/gouvernement/composition")
test("parlement_deputes",    "https://www.assemblee-nationale.ci/l-assemblee/les-deputes")
test("parlement_root",       "https://www.assemblee-nationale.ci")
test("presidence_gouv",      "https://www.presidence.ci/gouvernement")
test("presidence_root",      "https://www.presidence.ci")

print("\n=== ML — Mali ===")
test("koulouba_gouv",        "https://www.koulouba.ml/gouvernement")
test("koulouba_root",        "https://www.koulouba.ml")

print("\n=== BF — Burkina Faso ===")
test("gouv_composition",     "https://www.gouvernement.gov.bf/gouvernement/composition")
test("gouv_gouvernement",    "https://www.gouvernement.gov.bf/gouvernement")
test("gouv_root",            "https://www.gouvernement.gov.bf")

print("\n=== NE — Niger ===")
test("gouv_root",            "https://www.gouv.ne")
test("gouv_gouvernement",    "https://www.gouv.ne/gouvernement")
test("gouv_composition",     "https://www.gouv.ne/index.php/gouvernement")

print("\n=== TG — Togo ===")
test("presidence_root",      "https://www.presidence.gouv.tg")
test("presidence_gouv",      "https://www.presidence.gouv.tg/gouvernement")
test("presidence_conseil",   "https://www.presidence.gouv.tg/conseil-des-ministres")

print("\n=== BJ — Bénin ===")
test("gouv_root",            "https://www.gouv.bj")
test("gouv_gouvernement",    "https://www.gouv.bj/gouvernement")
test("gouv_composition",     "https://www.gouv.bj/le-gouvernement")
test("presidence_gouv",      "https://www.presidence.bj/gouvernement")
test("parlement_membres",    "https://www.assemblee-nationale.bj/assemblee/membres")
test("parlement_root",       "https://www.assemblee-nationale.bj")

print("\n=== GN — Guinée ===")
test("bcrg_gouvernance",     "https://www.bcrg.org/index.php/gouvernance")
test("bcrg_root",            "https://www.bcrg.org")
test("bcrg2_gouvernance",    "https://www.bcrg-guinee.org/gouvernance")

---
name: aml-pep-research-agent
version: "8.1"
updated: "2026-05-24"
description: >
  Agent de recherche autonome spécialisé dans la veille réglementaire AML/CFT
  et l'identification des Personnes Politiquement Exposées (PPE/PEP).
  Couvre le Maghreb (MA, DZ, TN, LY) et l'Afrique de l'Ouest (UEMOA 8 pays + GN).

  Utiliser ce skill dès que l'utilisateur mentionne : PPE, PEP, AML, LAB-FT,
  LCB-FT, conformité réglementaire, loi bancaire, GAFI, sanctions, gel des avoirs,
  KYC, FATF, banque centrale, UTRF, CTAF, GIABA, BCEAO, Bank Al-Maghrib, ou toute
  recherche de texte réglementaire financier dans un pays africain ou maghrébin.
---

# AML/PEP Research Agent v8.1

> **Mis à jour le 24/05/2026** — Sources officielles vérifiées. Statuts GAFI fév. 2026.
> Validé par Junior Stevy / ScreenEdge Africa.

---

## Couverture géographique

| Zone | Pays | Code | Loi confirmée | GAFI fév. 2026 |
|------|------|------|---------------|----------------|
| Maghreb | Maroc | MA | Loi n°12-18 (2021) + Circ. BAM n°5/W/2022 | 🟢 Clean |
| Maghreb | Algérie | DZ | Loi n°05-01 mod. + Instr. CTRF n°03/2023 | 🔴 **Liste grise** |
| Maghreb | Tunisie | TN | Loi org. 2015-26 + Circ. BCT n°2017-08 | 🟢 Clean |
| Maghreb | Libye | LY | Loi n°1/2005 (partielle) | 🟢 Clean* |
| UEMOA | Sénégal | SN | Loi n°2024-08 du 14/02/2024 | 🟢 Clean |
| UEMOA | Côte d'Ivoire | CI | Ordonnance n°2023-875 du 23/11/2023 | 🔴 **Liste grise** |
| UEMOA | Togo | TG | Loi n°2026-001 du 02/03/2026 | 🟢 Clean |
| UEMOA | Bénin | BJ | Loi n°2024-01 du 20/02/2024 | 🟢 Clean |
| UEMOA | Mali | ML | Directive UEMOA (loi locale non localisée) | 🟢 Clean* |
| UEMOA | Burkina Faso | BF | Loi n°46-2024 du 30/12/2024 | 🟢 Clean |
| UEMOA | Niger | NE | Ordonnance n°2024-56 du 19/12/2024 | 🟢 Clean* |
| UEMOA | Guinée-Bissau | GW | Directive UEMOA (loi locale non localisée) | ⚠️ À confirmer |
| Autres | Guinée | GN | L/2012/N°011/CNT du 19/07/2012 | 🟢 Clean* |

*Clean GAFI mais vigilance renforcée recommandée (instabilité politique / transition militaire).

**Source GAFI :** fatf-gafi.org/en/publications/High-risk-and-other-monitored-jurisdictions/ (fév. 2026)
**Liste noire fév. 2026 :** RPDC, Iran, Myanmar UNIQUEMENT.

---

## Workflow de l'agent

### PHASE 1 — Identifier le cadre légal
```
1. Identifier le pays cible et sa zone (Maghreb / UEMOA / Autre)
2. Charger la section de référence du pays dans ce fichier
3. Vérifier statut GAFI du pays (liste noire / grise / clean)
4. Appliquer niveau de vigilance correspondant
```

### PHASE 2 — Extraire les éléments critiques PPE

```json
{
  "pays": "",
  "code_iso": "",
  "zone": "maghreb | uemoa | autre",
  "loi_reference": "",
  "date_publication": "",
  "source_url": "",
  "directive_uemoa": false,
  "pep_categories": {
    "etrangeres": true,
    "nationales": true,
    "organisations_internationales": true
  },
  "pep_fonctions": [],
  "famille_incluse": true,
  "proches_associes_inclus": true,
  "duree_statut_post_fonction": "permanente | N_ans | non_precise",
  "reevaluation_periodicite": "3_ans | non_precise",
  "autorite_supervision": "",
  "statut_gafi": "clean | liste_grise | liste_noire",
  "date_statut_gafi": "2026-02",
  "vigilance_niveau": "standard | renforcee | maximale",
  "statut_verification": "officiel | secondaire | non_verifie",
  "date_extraction": ""
}
```

### PHASE 3 — Vérifier la fiabilité
```
🟢 OFFICIEL (priorité absolue)
   ├── Banque centrale (BAM, BCT, BCA, BCEAO)
   ├── Journal officiel
   ├── Unité de renseignement financier (CENTIF/CTRF/UTRF)
   └── Autorité de marché financier

🟡 SECONDAIRE (référence croisée)
   ├── GAFI / FATF (fatf-gafi.org)
   ├── GIABA (Afrique de l'Ouest)
   ├── FMI / Banque mondiale
   └── BCEAO (pour UEMOA)

🔴 NON FIABLE (exclure)
   ├── Sites sans auteur identifié
   ├── Blogs / forums
   └── Sources sans date
```

### PHASE 4 — Produire le rapport

```markdown
# Rapport PPE — [PAYS] — [DATE]

## Cadre légal
- Loi : ...
- Zone : Maghreb | UEMOA | Autre
- Directive commune UEMOA : Oui/Non

## Définition PPE
- Catégories : étrangères / nationales / orgs internationales
- Fonctions (i à xii) : ...
- Famille : ...
- Proches associés : ...

## Durée ex-PPE
- Durée fixe : Oui/Non
- Texte : ...

## Statut GAFI (fév. 2026)
- Statut : Clean | Liste grise | Liste noire
- Vigilance ScreenEdge : standard | renforcée | maximale

## Sources officielles
- [URL] — [Autorité] — [Date lecture]
```

---

## Règles critiques

1. Ne jamais citer une source sans vérifier son statut officiel
2. Toujours horodater chaque extraction
3. Croiser au minimum 2 sources avant de valider
4. Pour l'UEMOA : une seule définition PPE pour 8 pays (Directive n°001-2023-CM)
5. Pays liste grise (DZ, CI) → vigilance renforcée obligatoire, documenter
6. Pays "Clean mais fragiles" (LY, ML, NE, GN) → vigilance renforcée recommandée
7. Vérifier fatf-gafi.org avant tout classement GAFI
8. Liste noire fév. 2026 = RPDC + Iran + Myanmar uniquement
9. ML et GW : loi locale non localisée → appliquer Directive UEMOA n°001-2023-CM par défaut

---

# Références AML/PPE — Maghreb
> Version 8.1 | Mise à jour : 24/05/2026 | Sources officielles lues directement

---

## MAROC

**Loi :** n°12-18 du 14 juin 2021 (modifie Loi n°43-05) — Art.1, Art.46 à 51
**Circulaire :** BAM n°5/W/2022
**Guide officiel :** BAM + ANRF + AMMC + ACAPS + CNASNU — Mars 2025

**Autorités :**
| Autorité | URL |
|----------|-----|
| BAM (Bank Al-Maghrib) | bkam.ma |
| ANRF (ex-UTRF) | utrf.ma |
| AMMC | ammc.ma |

**Définition PPE :** Toute personne physique qui exerce ou a exercé d'importantes fonctions publiques au Maroc ou à l'étranger, notamment : chefs d'État, membres du gouvernement, parlementaires, membres des juridictions supérieures, hauts fonctionnaires, dirigeants de partis politiques, hauts responsables d'organisations internationales. Inclut les membres de la famille proche et les proches associés.

**Durée ex-PPE :** Non confirmée publiquement → appliquer GAFI R12 (surveillance permanente)
**Famille :** Incluse (détail réservé aux assujettis — Directive BAM n°2/W/2019)
**Proches associés :** Inclus
**Liste officielle PPE :** Partielle — réservée aux assujettis (non publique)
**Statut GAFI fév. 2026 :** 🟢 Clean (sorti liste grise fév. 2023)
**Vigilance ScreenEdge :** Standard

**Sources :**
```
bkam.ma → Supervision → Intégrité Financière → Guide LBC-FT (mars 2025)
utrf.ma
ammc.ma
```

**GAP :** Liste PPE réservée assujettis → fallback GAFI R12. Base PEP locale déjà présente dans ScreenEdge.

---

## ALGÉRIE

**Loi :** n°05-01 du 6 fév. 2005 modifiée par n°23-01 (7 fév. 2023) + n°25-048 (2025) — Art.4
**Instructions clés :** CTRF n°03/2023 du 5 déc. 2023 (PPE) — Art.2,3,4,5 + CTRF n°02/2023 du 4 déc. 2023 — Art.17

**Autorité :** CTRF (Cellule de Traitement du Renseignement Financier) — Ministère des Finances

**Définition PPE verbatim (Art.2 Instr.CTRF n°03/2023) :**
> "Tout Algérien, étranger, élu ou nommé, ayant exercé ou exerce en Algérie ou à l'étranger
> de hautes fonctions législatives, exécutives, administratives ou judiciaires, et les hauts
> responsables des partis politiques, ainsi que les personnes qui exercent ou ayant exercé
> des fonctions importantes auprès ou pour des organisations internationales."

**Durée ex-PPE :** Surveillance permanente (Art.4 + Art.5 Instr.n°03/2023) — aucune durée fixe
**Famille :** Incluse (Art.4 Instr.n°03/2023)
**Proches associés :** Inclus (Art.17 Instr.n°02/2023)
**Autorisation :** Autorité supérieure obligatoire avant relation avec PPE
**Statut GAFI fév. 2026 :** 🔴 **Liste grise** (depuis oct. 2024 — sortie possible 2026)
**Vigilance ScreenEdge :** ⚠️ RENFORCÉE OBLIGATOIRE

**Sources :**
```
bank-of-algeria.dz → À propos → Cadre législatif → Instructions CTRF
PDFs : Instruction CTRF n°02/2023 + Instruction CTRF n°03/2023
ctrf.mf.gov.dz
```

---

## TUNISIE

**Loi :** Loi organique n°2015-26 du 7 août 2015 — Art.110
**Modificative :** Loi organique n°2019-9 du 23 jan. 2019
**Circulaire principale :** BCT n°2017-08 du 19 sept. 2017 — Art.2 (définition) + Art.16 (vigilance) ✅ LUE
**Circulaire récente :** BCT n°2026-02 du 23 jan. 2026 (bureaux de change) ⚠️ à reconsulter

**Autorités :**
| Autorité | URL |
|----------|-----|
| BCT | bct.gov.tn |
| CTAF | ctaf.gov.tn |

**Définition PPE verbatim (Art.2 Circ. BCT n°2017-08) :**
Personnes tunisiennes ou étrangères qui exercent ou ont exercé des hautes fonctions publiques ou des missions représentatives ou politiques en Tunisie ou à l'étranger, notamment :
- Chef d'État, Chef du gouvernement, membre d'un gouvernement, gouverneurs
- Membres d'un parlement (élus nationaux et régionaux)
- Membres d'une cour constitutionnelle ou d'une haute juridiction
- Membres d'une instance constitutionnelle
- Officiers militaires supérieurs
- Ambassadeurs, chargés d'affaires, consuls
- Membres de collèges/conseils d'administration des autorités de contrôle
- Membres d'organes d'administration/direction/contrôle d'entreprises publiques
- Membres des organes de direction d'organisations internationales
- Hauts responsables de partis politiques
- Membres des organes de direction syndicale ou patronale

**Durée ex-PPE :** Surveillance continue et renforcée (Art.16) — aucune durée fixe
**Famille :** Ascendants/descendants 1er degré + conjoints (Art.16)
**Proches associés :** Personnes ayant liens d'affaires étroits (Art.16)
**Statut GAFI fév. 2026 :** 🟢 Clean (sorti liste grise 2019)
**Vigilance ScreenEdge :** Standard

**Sources :**
```
bct.gov.tn (⚠️ maintenance 24/05/2026 — reconsulter)
ctaf.gov.tn
legislation-securite.tn
cbf.org.tn → Circulaires et Notes
```

---

## LIBYE

**Loi :** n°1 de 2005 sur le blanchiment d'argent et le financement du terrorisme (révisée) — application partielle
**Autorité :** FIU Libya → fiulibya.gov.ly (accès intermittent)
**Région GAFI :** MENAFATF

**Définition PPE :** Personne exerçant ou ayant exercé d'importantes fonctions publiques, conformément aux recommandations GAFI : chefs d'État, gouvernement, parlementaires, membres judiciaires supérieurs, responsables militaires, dirigeants de banques centrales et entreprises d'État. Famille proche incluse.

**Statut GAFI fév. 2026 :** 🟢 Clean (non listé fév. 2026)
**Vigilance ScreenEdge :** ⚠️ Renforcée recommandée malgré Clean GAFI

**GAP :** Instabilité politique majeure, guerre civile, application partielle de la loi → sources internationales (OFAC, ONU) à privilégier.

---

# Références AML/PPE — Afrique de l'Ouest
> Version 8.1 | Mise à jour : 24/05/2026 | Sources officielles lues directement

---

## CADRE COMMUN UEMOA

**Directive :** n°001-2023-CM/UEMOA
**Instructions BCEAO :** n°001/002/003-03-2025
**Autorité régionale :** BCEAO → bceao.int
**GAFI régional :** GIABA → giaba.org

> **PRINCIPE CLÉ** : Les 8 pays UEMOA partagent la MÊME définition PPE.
> Une seule structure — colonne "loi nationale" différente par pays.

### Définition PPE commune UEMOA

**3 catégories :**

**a) PPE étrangères** — fonctions i à xii :

| # | Fonction |
|---|---------|
| i | Chefs d'État/Gouvernement, ministres, ministres délégués, secrétaires d'État |
| ii | Membres de familles royales |
| iii | SG Présidence/Gouvernement/ministères + DG ministères |
| iv | Parlementaires |
| v | Membres cours suprêmes/constitutionnelles/hautes juridictions sans recours |
| vi | Membres cours des comptes/conseils/directoires banques centrales |
| vii | Ambassadeurs, chargés d'affaires, officiers supérieurs forces armées |
| viii | Membres organes administration/direction/surveillance entreprises publiques |
| ix | Hauts responsables partis politiques |
| x | Famille : conjoint, enfants+conjoints/partenaires, autres parents |
| xi | Personnes étroitement associées à une PPE |
| xii | Toute personne désignée par l'assujetti sur base RBA |

**b) PPE nationales** — mêmes fonctions dans le pays (i à xii)

**c) PPE organisations internationales** — membres haute direction + famille (x à xii)

### Obligations communes Art.29

| Obligation | Détail |
|-----------|--------|
| Dispositif de détection | Procédures formalisées obligatoires |
| Autorisation haute direction | Avant toute relation PPE |
| Origine du patrimoine | Établir source des fonds |
| Surveillance | Continue et renforcée |
| **Réévaluation** | **Tous les 3 ans** ← CRITIQUE ScreenEdge |

**Durée ex-PPE :** "exercent ou ont exercé" — aucune durée fixe
**Seuil bénéficiaire effectif :** > 25% du capital
**Conservation documents :** 10 ans

---

## SÉNÉGAL

**Loi :** n°2024-08 du 14 fév. 2024 (LBC/FT/PADM) — Art.2 + Art.29 ✅ LUE
**J.O :** n°7716 du 20 mars 2024 | Abroge loi 2018-03
**Autorité :** CENTIF Sénégal → site.centif.sn
**Statut GAFI fév. 2026 :** 🟢 Clean (sorti liste grise oct. 2024)
**Vigilance ScreenEdge :** Standard

**Notes :** 9 fonctions listées + extensions famille/proches. Réévaluation obligatoire tous les 3 ans (Art.29). Seuil bénéficiaire effectif > 25% (Art.2). Conservation 10 ans (Art.23).

**Source :**
```
site.centif.sn → Cadre juridique → National → Législatifs → Textes LBCFT
PDF : Loi-n°2024-08-du-14-fevrier-2024-relative-a-LBC-FT-PADM.pdf
```

---

## CÔTE D'IVOIRE

**Loi :** Ordonnance n°2023-875 du 23 nov. 2023 (LBC/FT/PADM) — Art.2 point 50 + Art.29 ✅ LUE
**J.O :** 1er décembre 2023 | Abroge loi n°2016-992
**Autorité :** CENTIF CI → centif.ci
**Statut GAFI fév. 2026 :** 🔴 **Liste grise** (depuis oct. 2024)
**Vigilance ScreenEdge :** ⚠️ RENFORCÉE OBLIGATOIRE

**Notes :** Structure PPE identique au Sénégal — même directive UEMOA transposée. Seuil bénéficiaire effectif > 25% (Art.2 point 12). Conservation 10 ans (Art.23). Signé par le Président Alassane Ouattara.

**Source :**
```
centif.ci → Cadre juridique → Législation et réglementation
PDF : ORDONNANCE-N2023-875-DU-23-NOVEMBRE-2023-...pdf
```

---

## TOGO

**Loi :** n°2026-001 du 02 mars 2026 (LBC/FT/PADM) *(la plus récente de l'UEMOA)* ✅ LUE
**Autorité :** CENTIF Togo → centif.tg
**Statut GAFI fév. 2026 :** 🟢 Clean (sorti liste grise oct. 2025)
**Vigilance ScreenEdge :** Standard

**Note spécifique :** Point x-3 famille = "les autres parents" (formulation plus précise que SN/CI).

**Source :**
```
centif.tg → Lois et Textes
```

---

## BÉNIN

**Loi :** n°2024-01 du 20 fév. 2024 (LBC/FT/PADM) ✅ LUE (90/96 pages scannées)
**Autorité :** CENTIF Bénin → centif.bj
**Statut GAFI fév. 2026 :** 🟢 Clean
**Vigilance ScreenEdge :** Standard

**Notes :** Définition PPE identique UEMOA — 9 fonctions + famille + proches. Réévaluation tous les 3 ans. Durée ex-PPE : pas de durée fixe.

**Source :**
```
centif.bj → Publications → Lois & Règlements → Lois
```

---

## MALI

**Loi nationale :** Non localisée (centif.ml inaccessible)
**Fallback :** Directive UEMOA n°001-2023-CM — définition PPE identique aux autres pays UEMOA
**Autorité :** CENTIF Mali (site inaccessible) / GIABA → giaba.org/member-states/mali.html
**Statut GAFI fév. 2026 :** 🟢 Clean (sorti liste grise oct. 2025)
**Vigilance ScreenEdge :** ⚠️ Renforcée recommandée

**GAP documentaire :** centif.ml inaccessible. Coup d'État 2021, Alliance États du Sahel, sorti CEDEAO jan. 2025.

---

## BURKINA FASO

**Loi :** n°46-2024 du 30 déc. 2024 (LBC/FT/PADM) ✅
**Décret :** n°2023-1308 du 08 oct. 2023 — 37 catégories EPNFD listées ✅ LU
**Autorité :** CENTIF-BF / ANS-LBC/FT/FP → centif.bf
**Statut GAFI fév. 2026 :** 🟢 Clean (sorti liste grise oct. 2025)
**Vigilance ScreenEdge :** Standard

**Note spécifique BF :** Seul pays UEMOA avec 37 catégories EPNFD listées + autorités de supervision (Art.4 + Art.25 Décret 2023-1308). Obligation PPE EPNFD : Art.25 → GAFI R.22.3. Sanctions ANS : max 500 000 000 FCFA.

**Source :**
```
centif.bf
```

---

## NIGER

**Loi :** Ordonnance n°2024-56 du 19 déc. 2024 (LBC/FT/PADM) — Art.2 point 50 + Art.29 ✅ LUE
**Autorité :** CENTIF-Niger → centif.ne
**Statut GAFI fév. 2026 :** 🟢 Clean (non listé fév. 2026)
**Vigilance ScreenEdge :** ⚠️ Renforcée recommandée

**Notes :** Définition PPE identique UEMOA. Famille point x. Proches point xi. Réévaluation tous les 3 ans. Signé par le CNSP (junte militaire). Coup d'État 2023, Alliance États du Sahel.

**Source :**
```
centif.ne → Cadre juridique → Textes législatifs
```

---

## GUINÉE-BISSAU

**Loi nationale :** Non localisée en ligne
**Fallback :** Directive UEMOA n°001-2023-CM — membre UEMOA depuis 1997
**Autorité :** CENTIF Guinée-Bissau (inaccessible) / GIABA → giaba.org/member-states/guinea-bissau.html
**Statut GAFI fév. 2026 :** ⚠️ À confirmer sur fatf-gafi.org
**Vigilance ScreenEdge :** ⚠️ Renforcée par défaut

**GAP documentaire :** Site CENTIF-GW inaccessible. Instabilité politique chronique.

---

## GUINÉE (hors UEMOA)

**Loi :** L/2012/N°011/CNT du 19 juillet 2012 — application partielle
**Autorité :** CENTIF Guinée (inaccessible) / BCRG → bcrg.org
**Statut GAFI fév. 2026 :** 🟢 Clean (non listé fév. 2026)
**Vigilance ScreenEdge :** ⚠️ Renforcée obligatoire par défaut

**Notes :** Hors UEMOA — loi nationale propre. Transition militaire CNRD depuis sept. 2021. PPE à surveiller : membres CNRD, gouvernement de transition, hauts fonctionnaires militaires. Source alternative : giaba.org/member-states/guinea.html

**GAP documentaire :** Site CENTIF-GN inaccessible. Définition PPE basée sur recommandations GAFI transposées localement.


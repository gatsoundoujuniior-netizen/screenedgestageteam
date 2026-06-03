# Agent AML/PPE — ScreenEdge Africa

Module de recherche et de surveillance réglementaire AML/PPE pour la plateforme ScreenEdge Africa.

**Axe** : Matching Multilingue & Gestion des PEP  
**Responsable** : Junior Stevy Gatsoundou  
**Superviseur** : Hazim Sebbata  
**MVP** : 19 juillet 2026

---

## Fonctionnalités

### Agent de recherche AML/PPE (`agent_aml_pep.ipynb`)
- LLM local Ollama (llama3.1:8b) — gratuit, aucune donnée envoyée en cloud
- 4 tools : recherche web (Tavily), lecture PDF officiels, lecture pages web, vérification GAFI
- Routing dynamique : détecte le type de requête et active le bon tool
- Output structuré Pydantic (`PPEReport`) — 12 champs
- Mémoire par session (`thread_id`) — isolation multi-clients

### Monitoring GAFI automatique (`gafi_monitor.py`)
- Surveillance hebdomadaire des 13 pays cibles (Maghreb + UEMOA + Guinée)
- Détection automatique des changements de statut (liste grise / liste noire / clean)
- Pipeline de validation humaine via n8n avant toute mise à jour du référentiel
- Notifications Email (Gmail) + WhatsApp (Twilio)

### Pipeline de validation humaine
```
gafi_monitor.py → détecte changement
       ↓
gafi_pending.json (sauvegarde locale)
       ↓
n8n webhook → Email + WhatsApp avec boutons Valider/Refuser
       ↓
approval_server.py (Flask local) ← n8n POST /apply-gafi
       ↓
apply_changes.py → met à jour le référentiel .md
```

---

## Couverture géographique

| Région | Pays |
|--------|------|
| Maghreb | Maroc, Algérie, Tunisie, Libye |
| UEMOA | Sénégal, Côte d'Ivoire, Mali, Burkina Faso, Niger, Togo, Bénin, Guinée-Bissau |
| GIABA | Guinée |

---

## Installation

```bash
# 1. Cloner le repo
git clone https://github.com/gatsoundoujuniior-netizen/screenedgestageteam.git
cd screenedgestageteam

# 2. Créer l'environnement virtuel
python -m venv .venv
.venv\Scripts\activate       # Windows
# source .venv/bin/activate  # Linux/Mac

# 3. Installer les dépendances
pip install -r requirements.txt

# 4. Configurer les variables d'environnement
cp .env.example .env
# Éditer .env avec vos clés API

# 5. Installer Ollama (LLM local)
# https://ollama.com → puis : ollama pull llama3.1:8b
```

---

## Utilisation

### Agent de recherche (Jupyter)
```bash
jupyter lab agent_aml_pep.ipynb
```

### Monitoring GAFI (manuel)
```bash
python gafi_monitor.py
```

### Serveur d'approbation n8n (laisser tourner en arrière-plan)
```bash
python approval_server.py
```

### Déployer le workflow n8n
```bash
python upload_n8n_workflow.py
```

---

## Base de données

Le fichier `create_table.sql` contient la table `referentiel_pep` pour Supabase/PostgreSQL.

```bash
# Exécuter dans Supabase Dashboard > SQL Editor
# ou via psql :
psql -U postgres -d compliance_db -f create_table.sql
```

---

## Référentiel PPE

`PEP_Referentiel_Pays_ScreenEdge_Africa_v11.xlsx` — validé par Hazim Sebbata & Mme Ibtissam  
- Définitions PPE officielles par pays (sources réglementaires lues)
- Statuts GAFI vérifiés (fév. 2026)
- 4 feuilles : Référentiel / Définition GAFI / Statuts & Couverture / Changelog

---

## Structure du projet

```
agent_aml_pep/
├── agent_aml_pep.ipynb          # Agent LangGraph AML/PPE
├── gafi_monitor.py              # Monitoring GAFI automatique
├── apply_changes.py             # Application des changements validés
├── approval_server.py           # Serveur Flask webhook n8n
├── upload_n8n_workflow.py       # Déploiement workflow n8n
├── create_table.sql             # Schéma BDD referentiel_pep
├── aml-pep-research-agent.md   # Référentiel AML/PPE (base de connaissances)
├── PEP_Referentiel_Pays_...xlsx # Référentiel Excel validé
├── requirements.txt             # Dépendances Python
├── .env.example                 # Template variables d'environnement
└── .gitignore
```

---

## Dépendances principales

| Package | Version | Usage |
|---------|---------|-------|
| langgraph | 1.2.1 | Orchestration agent |
| langchain-ollama | 1.1.0 | LLM local |
| langchain-tavily | 0.2.18 | Recherche web |
| pydantic | 2.13.4 | Output structuré |
| flask | — | Serveur approbation |
| openpyxl | 3.1.5 | Excel |
| pypdf | 6.12.1 | Lecture PDFs |

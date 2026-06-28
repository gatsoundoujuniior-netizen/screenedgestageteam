# Documentation Globale — ScreenEdge Compliance Platform

> Version : 1.0 — Mai 2026  
> Rédigée par : Analyse complète du code source (backend + frontend)

---

## Table des matières

1. [Vue d'ensemble du projet](#1-vue-densemble-du-projet)
2. [Architecture technique](#2-architecture-technique)
3. [Rôles et permissions](#3-rôles-et-permissions)
4. [Criblage manuel (Sanctions)](#4-criblage-manuel-sanctions)
5. [Criblage manuel PEP](#5-criblage-manuel-pep)
6. [Criblage automatique (AutoScreening)](#6-criblage-automatique-autoscreening)
7. [KYC — Création et fonctionnement](#7-kyc--création-et-fonctionnement)
8. [Gestion des Cas](#8-gestion-des-cas)
9. [Rapports](#9-rapports)
10. [Tables clés de la base de données](#10-tables-clés-de-la-base-de-données)

---

## 1. Vue d'ensemble du projet

ScreenEdge est une **plateforme de conformité réglementaire** destinée aux institutions financières et aux établissements assujettis à la réglementation de lutte contre le blanchiment d'argent et le financement du terrorisme.

La plateforme permet à ses clients (banques, sociétés de change, etc.) de :
- Gérer les dossiers KYC de leurs clients finaux (personnes physiques et morales)
- Cribler automatiquement et manuellement ces dossiers contre des listes de sanctions internationales (SEMA-LMES, OFAC, ONU, etc.) et la liste des Personnes Politiquement Exposées (PEP)
- Gérer les alertes et les cas suspects détectés
- Produire des rapports réglementaires (format CNASNU)
- Assurer une piste d'audit complète de toutes les actions

---

## 2. Architecture technique

```
Utilisateur (navigateur)
        │
        ▼
   Frontend : React + TypeScript + Vite
   (composants ShadCN/ui + Tailwind CSS)
        │
        ▼ API REST (HTTPS)
   Reverse Proxy : nginx 
        │
        ▼
   Backend : Node.js / Express 
   PM2 — mode cluster (2 workers)
        │
        ▼
   Base de données : PostgreSQL
   (hébergée sur serveur externe)
```

### Modules principaux du backend

| Module | Rôle |
|--------|------|
| `controllers/screeningController.js` | Criblage manuel (sanctions + PEP) |
| `services/autoScreeningService.js` | Logique du criblage automatique |
| `services/autoScreeningScheduler.js` | Planificateur cron du criblage auto |
| `controllers/kycController.js` | CRUD des dossiers KYC |
| `controllers/caseController.js` | Gestion des cas |
| `controllers/reportController.js` | Génération de rapports PDF/DOCX |
| `controllers/pepController.js` | Consultation de la base PEP |
| `utils/screeningMVPPlus.js` | Algorithme de scoring (Jaro-Winkler) |
| `utils/screeningUtils.js` | Fonctions de calcul des sous-scores |

---

## 3. Rôles et permissions

La plateforme distingue plusieurs niveaux d'accès :

| Rôle | Accès aux données |
|------|------------------|
| `super_admin_screenedge` | 
| `admin_screenedge` | 
| `admin_client` | 
| `admin` | 
| `validateur` | 
| `compliance_officer` | 
| `officier` | 

Chaque action sensible (créer un criblage, créer un cas, etc.) est en plus conditionnée par des **permissions granulaires** stockées en base de données dans la colonne `permissions` de la table `utilisateurs`.

---

## 4. Criblage manuel (Sanctions)

### 4.1 Déclenchement

Le criblage manuel est initié par un utilisateur connecté depuis le module **Screening** de l'interface. Il existe deux sous-types :
- **Personne physique** : criblage par nom, prénom, date de naissance, nationalité, numéros de pièces d'identité (CNI, passeport)
- **Personne morale (entreprise)** : criblage par raison sociale et pays d'établissement / de constitution

### 4.2 Fonctionnement — Personne physique

**Étape 1 — Saisie et validation**

L'utilisateur saisit au minimum le nom et le prénom de la personne à cribler. Les autres champs (date de naissance, nationalité, CNI, passeport) sont facultatifs mais améliorent la précision du matching. Un seuil de matching configurable (par défaut 60 %) détermine le score minimum pour qu'une correspondance soit retenue.

**Étape 2 — Génération du numéro de criblage**

Un numéro unique au format `SCR-YYYY-XXXX` est généré et vérifié contre la base de données pour garantir son unicité.

**Étape 3 — Pré-filtrage SQL dans la base de sanctions**

Une requête SQL est lancée sur la table `entites_sanctionnees` pour récupérer jusqu'à 100 candidats potentiels. Cette requête utilise des correspondances partielles (`LIKE`) sur le nom, le prénom et le nom complet. Un algorithme de pré-filtrage amélioré est également appliqué : si le prénom correspond exactement, le nom de l'entité doit commencer par les 2 ou 3 premiers caractères du nom recherché.

**Étape 4 — Calcul du score de matching (algorithme MVP++)**

Pour chaque candidat retenu par le pré-filtrage, un score global est calculé à partir de plusieurs composantes :

- **Score nom** (méthode Jaro-Winkler) : combine le score du prénom (pondération 40 %) et du nom de famille (pondération 60 %). L'algorithme Jaro-Winkler est adapté aux noms de personnes car il donne plus de poids aux caractères en début de chaîne et gère bien les variantes orthographiques mineures. Les alias éventuels de l'entité sanctionnée sont également évalués.
- **Score date de naissance** : comparaison exacte entre la date fournie et celle de l'entité (score de 100 si identiques, 0 sinon).
- **Score nationalité** : comparaison textuelle entre la nationalité fournie (en français et en anglais) et celle de l'entité. La correspondance peut être partielle.
- **Score identité** (CNI / passeport) : comparaison exacte des numéros de pièces d'identité.

Les pondérations sont **dynamiques** : elles s'adaptent en fonction des informations disponibles. Si la date de naissance n'est pas fournie, son poids est redistribué sur le nom. Si la nationalité n'est pas connue, son poids est également redistribué.

**Étape 5 — Filtre strict post-scoring**

Même si le score calculé est élevé (potential match), un filtre strict supplémentaire est appliqué : le prénom doit correspondre exactement (après normalisation et suppression des diacritiques) ET les 2 premiers caractères normalisés du nom doivent correspondre. Ce filtre évite les faux positifs dus à des prénoms communs avec des noms très différents.

**Étape 6 — Niveaux de risque**

| Niveau | Condition | Signification |
|--------|-----------|---------------|
| `potential_match` | Score ≥ 82 % | Correspondance probable, action requise |
| `review` | Score entre 65 % et 82 % | À examiner manuellement |
| `clear` | Score < 65 % | Pas de correspondance significative |

**Étape 7 — Enregistrement des résultats**

- Le criblage est créé dans la table `criblage` avec le type `manuel`, le statut `terminé`, le résultat global (`match` ou `clear`), le score maximum et la liste des correspondances (JSON).
- Chaque correspondance retenue est stockée dans la table `resultats_criblage` avec l'intégralité des détails d'explicabilité (scores détaillés par composante, pondérations utilisées).
- L'enregistrement est lié au dossier KYC correspondant via `kyc_id` si le criblage est lancé depuis un dossier KYC.

### 4.3 Fonctionnement — Personne morale (entreprise)

Le processus est similaire mais adapté aux entités légales :
- La raison sociale est **nettoyée** avant matching (suppression des suffixes de forme juridique : SA, SARL, SAS, SAS.U, LLD, ainsi que leurs variantes avec points)
- La recherche porte uniquement sur les entités de type `entreprise` ou `organisation` dans la base de sanctions
- Le score pays est calculé à partir du pays de constitution (ou de siège)
- Il n'y a pas de score date ni de score identité (non applicables)
- Le scoring privilégie fortement la similarité de la raison sociale (pondération dominante)

### 4.4 Gestion des faux positifs

Un utilisateur autorisé peut marquer une correspondance comme **faux positif**. Cette action met le champ `situation` à `true` sur l'enregistrement de criblage et réinitialise le `resultat_global` à `clear`. Les criblages marqués faux positifs ne reçoivent plus d'email de notification automatique.

---

## 5. Criblage manuel PEP

### 5.1 Qu'est-ce qu'un PEP ?

Un PEP (Personne Politiquement Exposée) est une personne qui exerce ou a exercé d'importantes fonctions publiques. La réglementation AML exige une vigilance renforcée pour ces personnes. La plateforme dispose d'une base PEP locale (table `pep`) alimentée notamment par des données marocaines (ministres, hauts fonctionnaires, etc.).

### 5.2 Déclenchement

Le criblage PEP manuel est accessible depuis la section dédiée du module Screening. L'utilisateur doit disposer de la permission explicite `canRunScreening`. Les champs de saisie sont identiques au criblage sanctions (nom, prénom, date de naissance, nationalité, CNI, passeport).

### 5.3 Fonctionnement

**Étape 1 — Sécurité sur le client_id**

Le système utilise systématiquement le `client_id` de l'utilisateur connecté (extrait du token JWT) et non celui transmis dans le corps de la requête, afin d'éviter tout contournement d'isolation entre clients.

**Étape 2 — Pré-filtrage SQL dans la base PEP**

Une requête `LIKE` est lancée sur la table `pep` (champs `nom`, `prenom`, `nom_complete`). Si la nationalité est fournie, le résultat est filtré en langue française et anglaise pour réduire les faux candidats.

**Étape 3 — Calcul du score**

Le même moteur de scoring est utilisé (nom, date, pays), mais sans score identité (les PEP n'ont pas de numéros CNI/passeport dans la base). Des cas particuliers sont gérés :
- Si le score nom ≥ 95 % ET date ≥ 85 % ET pays ≥ 85 % → score global 100 %
- Si le score nom ≥ 95 % ET pays ≥ 85 % ET pas de date → score global 100 %
- Si le score nom ≥ 95 % ET aucune date ni pays fournis → score global 100 %

**Étape 4 — Enregistrement**

- Le criblage est créé dans la table `criblage_pep` avec le type `manuel`.
- Le meilleur match PEP trouvé est enregistré en détail dans le même enregistrement (nom, prénom, nationalité, fonction actuelle, date de nomination, date de naissance, lieu de naissance, formations, fonctions intérieures, source URL).
- Les 10 meilleurs résultats sont retournés au frontend, triés par score décroissant.

**Étape 5 — Validation et faux positifs**

Comme pour le criblage sanctions :
- Un utilisateur peut marquer le résultat comme faux positif (`situation = true`)
- Un utilisateur autorisé peut valider le résultat (`validation = true`, `valider_par`, `date_validation`)

---

## 6. Criblage automatique (AutoScreening)

### 6.1 Vue d'ensemble

Le criblage automatique est un processus planifié (cron) qui crible **tous les dossiers KYC actifs** de tous les clients de la plateforme, sans intervention humaine. Il couvre à la fois les personnes physiques et les entreprises, et inclut un criblage PEP en parallèle pour les personnes physiques.

### 6.2 Planification

| Environnement | Criblage | Monitoring |
|---------------|----------|------------|
| Production | Tous les jours à **04h00 GMT+1** | Tous les jours à **06h00 GMT+1** |
| Local/Dev | Toutes les **heures** (UTC) + au démarrage (5 s) | Tous les jours à **06h00 GMT+1** |

La timezone est configurable via la variable d'environnement `AUTO_SCREENING_CRON_TZ` (défaut : `Etc/GMT-1`).

### 6.3 Sélection des enregistrements à cribler

**Personnes physiques :** Tous les enregistrements de la table `enregistrements_kyc` dont :
- Le statut est `En cours`, `En attente`, `Rejeté` ou `Vérifié`
- Le type n'est pas `entreprise`
- Le nom et le prénom sont renseignés

**Entreprises :** Tous les enregistrements de la table `kyc_entreprise` dont :
- Le KYC parent a un statut `En cours`, `En attente`, `Rejeté` ou `Vérifié`
- La raison sociale est renseignée

Il n'y a **pas de filtre de délai** : chaque exécution cron recrible l'intégralité des dossiers éligibles.

### 6.4 Processus de criblage automatique

Le traitement est **séquentiel** (un enregistrement à la fois) pour éviter de surcharger la base de données. Les personnes physiques sont traitées en premier, puis les entreprises.

**Pour chaque personne physique :**

1. Génération d'un numéro de criblage unique au format `SCR-AUTO-YYYY-XXXXXXXXX`
2. Récupération des données du pays de nationalité
3. Recherche dans `entites_sanctionnees` par correspondance partielle sur nom/prénom/nom complet, avec filtre nationalité optionnel (max 100 candidats)
4. **En parallèle** : recherche dans la base PEP (même logique)
5. Calcul des scores pour chaque candidat sanctions (mêmes fonctions que le criblage manuel, seuil 60 %)
6. Calcul des scores pour chaque candidat PEP (seuil 60 %)
7. Création d'un enregistrement dans la table `criblage` (type `automatique`) avec le résultat consolidé (sanctions + PEP)

**Pour chaque entreprise :**

1. Nettoyage de la raison sociale (suppression des suffixes juridiques)
2. Recherche uniquement parmi les entités de type `entreprise` ou `organisation` dans `entites_sanctionnees`
3. Calcul du score (nom dominant, pays optionnel, pas de date ni identité)
4. Création d'un enregistrement dans `criblage` (type `automatique`)

### 6.5 Notification par email

Un email de notification est envoyé au créateur du dossier KYC lorsque les conditions suivantes sont toutes réunies :
- Au moins un match avec un score **≥ 80 %** est détecté (sanctions ou PEP)
- Le statut KYC est `En cours` ou `En attente`
- Le dossier n'est pas marqué faux positif (`situation = false`)
- Aucun email n'a déjà été envoyé **ce jour calendaire** pour ce dossier (anti-doublon via colonne `auto_match_email_sent_at`)

L'email liste l'ensemble des correspondances trouvées (sanctions et PEP séparément) avec leur score, leur source et la décision associée.

### 6.6 Monitoring quotidien

À 06h00, un rapport de monitoring est généré et envoyé par email aux responsables configurés. Ce rapport résume l'exécution du criblage de la nuit : nombre de dossiers criblés, nombre de matches, emails envoyés, erreurs éventuelles, durée d'exécution.

### 6.7 Robustesse

- Si le pool de connexions PostgreSQL est fermé (arrêt du serveur), le criblage s'interrompt proprement sans erreur critique.
- Les erreurs sur un dossier individuel n'interrompent pas le traitement des dossiers suivants.
- En mode cluster PM2, les deux workers partagent le même cron. Il faut veiller à ne pas déclencher des exécutions concurrentes.

---

## 7. KYC — Création et fonctionnement

### 7.1 Qu'est-ce qu'un KYC ?

Un enregistrement KYC (Know Your Customer) représente un dossier d'identification et de vérification d'un client final. ScreenEdge distingue deux types de KYC :
- **Personne physique** : particulier identifié par nom, prénom, date de naissance, nationalité, pièces d'identité
- **Personne morale (entreprise)** : société identifiée par raison sociale, forme juridique, RC, ICE, pays de constitution, pays de siège

### 7.2 Création d'un KYC

**Via l'interface**

Un utilisateur avec les droits appropriés crée un dossier KYC manuellement en remplissant le formulaire d'enregistrement. La création génère automatiquement un **numéro KYC unique** au format :

```
YYYY-ClientID-XXXX
Exemple : 2026-22-0010
```

La séquence `XXXX` est incrémentale par client et par année. Elle est calculée en cherchant le dernier numéro existant pour ce client/année et en incrémentant la partie numérique (pour éviter les problèmes de tri alphabétique avec des longueurs variables).

**Via lien d'invitation (KYC Link)**

Un administrateur peut générer un lien unique d'invitation envoyé par email à un tiers. Ce tiers renseigne lui-même ses informations via une interface publique. Le lien a une durée de validité limitée et est à usage unique.

**Via import CSV**

Le module `KYCCSVUpload` permet l'import en masse de dossiers KYC à partir d'un fichier CSV structuré.

### 7.3 Champs d'un KYC personne physique

| Champ | Obligatoire | Description |
|-------|-------------|-------------|
| Prénom | Oui | Prénom de la personne |
| Nom | Oui | Nom de famille |
| Date de naissance | Non | Format YYYY-MM-DD |
| Nationalité | Non | Lien vers la table `pays` |
| Email | Non | Contact |
| Téléphone | Non | Contact |
| CNI | Non | Numéro de carte nationale d'identité |
| Passeport | Non | Numéro de passeport |
| Documents | Non | Fichiers joints (scans de pièces) |
| Commentaires | Non | Notes libres |

### 7.4 Champs d'un KYC entreprise (kyc_entreprise)

| Champ | Description |
|-------|-------------|
| Raison sociale | Nom commercial de l'entreprise |
| Forme juridique | SA, SARL, SAS, etc. |
| Numéro RC | Registre du commerce |
| ICE | Identifiant commun d'entreprise (Maroc) |
| Identifiant fiscal | Numéro fiscal |
| Pays de constitution | Pays où l'entreprise est immatriculée |
| Pays de siège | Pays du siège social |
| Ville du siège | Ville |
| Date de constitution | Date de création légale |

### 7.5 Cycle de vie et statuts

```
Création
    │
    ▼
En attente  ←──────────────────────┐
    │                              │
    ▼                              │
En cours  ──────── Rejeté ─────────┘
    │
    ▼
Vérifié
```

| Statut | Signification |
|--------|---------------|
| `En attente` | Dossier créé, en attente de traitement |
| `En cours` | Dossier en cours de vérification |
| `Rejeté` | Dossier refusé suite à vérification |
| `Vérifié` | Dossier validé et conforme |

### 7.6 Détection PEP automatique à l'affichage

Lors de la récupération de la liste KYC, un indicateur de correspondance PEP (`pep_nom_prenom_match`) est calculé directement en SQL pour chaque dossier. Cette correspondance est basée sur une **comparaison exacte** (insensible à la casse) entre le nom + prénom du dossier KYC et la base PEP (nom + prénom exacts, ou nom_complet exact). Cet indicateur est purement informatif et ne remplace pas un criblage PEP complet.

### 7.7 Visibilité et contrôle d'accès

- `super_admin_screenedge` / `admin_screenedge` : voient tous les KYC de tous les clients
- `admin_client` / `admin` : voient tous les KYC de leur client uniquement
- `validateur` / `compliance_officer` / `officier` : voient uniquement les KYC qu'ils ont eux-mêmes créés

La liste des KYC permet de filtrer par statut, par date, par texte (nom, prénom, email, numéro KYC) et d'être triée et paginée.

### 7.8 Lien avec le criblage

Depuis la fiche d'un KYC, il est possible de lancer directement un criblage manuel (sanctions ou PEP). Le lien `kyc_id` dans la table `criblage` permet de retrouver tous les criblages effectués sur un dossier donné, ainsi que les dates du dernier criblage automatique et du dernier criblage manuel.

---

## 8. Gestion des Cas

### 8.1 Définition d'un cas

Un cas est créé manuellement par un utilisateur autorisé (`canCreateCases`) lorsqu'un criblage a détecté une correspondance jugée sérieuse. Le cas formalise la prise en charge de l'alerte et permet de suivre son traitement jusqu'à sa résolution.

### 8.2 Numérotation

Le numéro de cas suit le format :

```
CAS-YYYY-XXXX
Exemple : CAS-2026-4521
```

La partie numérique est générée aléatoirement sur 4 chiffres (entre 1000 et 9999).

### 8.3 Création d'un cas

Pour créer un cas, l'utilisateur doit fournir :
- L'identifiant du criblage (`criblage_id`) qui a généré l'alerte
- L'identifiant du client (`client_id`)
- Son propre identifiant (`cree_par`)

Les autres champs sont automatiquement déduits par le système :
- `resultat_criblage_id` : le résultat de criblage avec le score le plus proche du score transmis est recherché automatiquement dans `resultats_criblage`
- `kyc_id` : transmis optionnellement
- `entite_sanctionnee_id` : identifiant de l'entité sanctionnée concernée
- `score_match` : score de correspondance du match déclencheur
- `sujet` : généré automatiquement (`"Cas de sanction détecté - Score: XX%"`)

### 8.4 Données liées à un cas

Un cas agrège les informations suivantes :
- **Données du criblage original** : nom/prénom ou raison sociale tels que saisis lors du criblage, date de naissance, nationalité, CNI, passeport, RC, ICE
- **Données de l'entité sanctionnée trouvée** : nom, prénom, nationalité, date de naissance, CNI, passeport, raison de sanction, programme, description, source, liste de sanctions
- **Score et niveau de confiance** : score brut + qualification (Élevé ≥ 95 %, Moyen ≥ 80 %, Faible < 80 %)
- **Notes** : champ JSON structuré permettant d'ajouter plusieurs notes horodatées avec l'email de l'auteur
- **Réponse des autorités** (`autorite_response`) : texte libre permettant de consigner la réponse reçue des autorités compétentes, avec sa date
- **Contact** : établissement, référent conformité, email

### 8.5 Notifications

Lors de la création d'un cas, des notifications internes sont automatiquement envoyées aux utilisateurs concernés du même client (selon leur rôle). Ces notifications apparaissent dans le centre de notifications de l'interface.

### 8.6 Cycle de vie

Les cas sont consultables dans le module **Gestion des Cas** de l'interface. Ils peuvent être modifiés (ajout de notes, saisie de la réponse des autorités) et sont la source principale de génération des rapports réglementaires.

---

## 9. Rapports

### 9.1 Déclenchement

Un rapport est généré à la demande depuis la fiche d'un cas. L'utilisateur déclenche la génération depuis le module Reporting ou directement depuis la fiche du cas.

### 9.2 Format

Les rapports sont produits au format **PDF** via la bibliothèque `pdfkit`. Le système supporte automatiquement les polices Unicode (DejaVuSans, LiberationSans, NotoSans) pour l'affichage correct des caractères arabes et latins dans le même document.

### 9.3 Contenu du rapport

Le rapport suit le **format réglementaire CNASNU** (Commission Nationale Anti-blanchiment et contre le financement du terrorisme) et contient les sections suivantes :

**Section 1 — Cible (données saisies lors du criblage)**
- Type (Personne physique ou Entité)
- Nom / Raison sociale
- Identifiants (CNI, Passeport)
- RC et ICE (pour les entreprises)
- Date et lieu de naissance + nationalité (pour les personnes physiques)

**Section 2 — Entité sanctionnée trouvée**
- Nom, prénom, nationalité, date de naissance
- Numéros de pièces d'identité
- Raison de la sanction

**Section 3 — Détails du match**
- Source de la liste (SEMA-LMES, OFAC, ONU, etc.)
- Niveau de confiance interne (Élevé / Moyen / Faible)
- Horodatage de la détection
- Date d'entrée en relation

**Section 4 — Notes**
- Toutes les notes ajoutées au cas, avec l'horodatage et l'auteur de chaque note

**Section 5 — Réponse des autorités** *(si renseignée)*
- Texte de la réponse
- Mention automatique de la levée de gel si le texte le contient
- Date d'enregistrement de la réponse

**Section 6 — Contact**
- Établissement (nom du client)
- Référent conformité (nom + prénom de l'utilisateur)
- Email de contact
- Référence interne (numéro de cas)
- Date de génération du rapport

### 9.4 Données sources

Le rapport consolide des données provenant de plusieurs tables :

| Table | Données utilisées |
|-------|------------------|
| `cas` | Métadonnées du cas, notes, réponse autorités |
| `criblage` | Données de la personne criblée (telles que saisies) |
| `resultats_criblage` | Score de match, liste source |
| `entites_sanctionnees` | Informations sur l'entité sanctionnée |
| `listes_sanctions` | Nom de la liste, organisme source |
| `clients` | Nom de l'établissement |
| `utilisateurs` | Identité du référent conformité |
| `pays` | Libellé de la nationalité |

### 9.5 Gestion des caractères spéciaux

Le système applique une sanitisation des textes avant insertion dans le PDF :
- Normalisation Unicode (NFC)
- Suppression des caractères de contrôle
- Tentative de correction du double-encodage Latin-1/UTF-8 (fréquent avec des données arabes)
- Troncature automatique si le texte dépasse les limites de taille

---

## 10. Tables clés de la base de données

| Table | Description |
|-------|-------------|
| `clients` | Organisations clientes (banques, etc.) |
| `utilisateurs` | Utilisateurs de la plateforme avec rôles et permissions |
| `pays` | Référentiel des pays (code ISO2, nom FR, nom EN) |
| `enregistrements_kyc` | Dossiers KYC des personnes physiques |
| `kyc_entreprise` | Extension KYC pour les personnes morales |
| `entites_sanctionnees` | Entités listées dans les sanctions (personnes et organisations) |
| `pep` | Personnes Politiquement Exposées |
| `criblage` | Enregistrements de criblage (manuel et automatique) |
| `criblage_pep` | Enregistrements de criblage PEP (manuel) |
| `resultats_criblage` | Résultats détaillés de chaque correspondance trouvée |
| `cas` | Cas gérés suite aux alertes de criblage |
| `rapports` | Rapports générés (métadonnées + fichier) |
| `notifications` | Notifications internes utilisateurs |
| `paiements` | Paiements via Payzone (abonnements clients) |
| `plans_abonnement` | Plans tarifaires disponibles |
| `abonnements_clients` | Abonnements actifs par client |

---

*Document généré par analyse complète du code source ScreenEdge — Mai 2026*

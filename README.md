# Prime CRM — CRM intelligent pour TPE & PME

**Prime CRM** est une application éditée par **Prime Vision Solutions** (Tunis, Tunisie) pour centraliser clients, pipeline commercial, devis, agenda et intelligence artificielle facultative.

> [!WARNING]
> Le projet n'est pas encore prêt pour une exposition publique. L'accès privé, Redis, le changement de mot de passe et la révocation des sessions sont intégrés techniquement ; leur raccordement au déploiement reste à valider. Il reste notamment à protéger les connexions par IP, revoir les destinations réseau IA, prévoir la récupération d'un compte et vérifier les dépendances et les sauvegardes. Une CI verte ne constitue pas une validation de sécurité.

![Prime CRM](https://img.shields.io/badge/Stack-React%20%2B%20FastAPI%20%2B%20PostgreSQL-0ea5e9)
![License](https://img.shields.io/badge/License-MIT-green)
![Docker](https://img.shields.io/badge/Docker-Compose-2496ED)

---

## ✨ Fonctionnalités livrées

### Module Clients & Prospects (360°)
- CRUD complet, recherche globale, filtres (type, secteur, source, propriétaire), pagination, tri, vues
- Contacts multiples par entreprise, notes, tags, catégorie, secteur, statut
- Fiche 360° : contacts + opportunités + activités + devis + historique chronologique
- Détection de doublons (email/téléphone/nom) + fusion intelligente avec conservation d'historique
- Import CSV/Excel avec prévisualisation & validation + export CSV/Excel filtré
- Archivage (soft delete), propriétaire commercial, séparation stricte des données par entreprise (company_id)

### Pipeline Kanban interactif
- Glisser-déposer (DnD Kit) entre étapes configurables (8 par défaut : Nouveau prospect → Perdu)
- Étapes personnalisables (nom, couleur, ordre) avec flags Gagné/Perdu
- Chaque opportunité : titre, client, propriétaire, montant, probabilité, échéance, source, prochaine action, notes, historique
- CA potentiel, CA pondéré (montant × probabilité), alertes affaires bloquées / sans activité 14j / échéances dépassées
- Filtrage par commercial/période/étape/montant/source, raison de perte obligatoire

### Activités, Agenda & Relances
- Vues liste / jour / semaine / mois, création rendez-vous/appels/tâches/réunions avec priorité, durée, lieu, rappels
- Association client/opportunité, tâches en retard, notifications in-app, historique
- Moteur de règles configurable : devis sans réponse 5j → tâche relance, changement étape → notification, client inactif → alerte, avant RDV → rappel, opportunité gagnée → actions de suivi
- Journalisation des exécutions, anti-doublon (idempotence 5 min), désactivable, sans envoi externe sans canal autorisé

### Devis, Produits & Suivi Commercial
- Catalogue produits/services avec prix, coût, remise, TVA (TND 19% par défaut, configurable EUR/USD)
- Conditions de paiement, validité, numérotation auto `DEV-0001-2026` (préfixe configurable)
- Génération PDF professionnel (fpdf2) avec en-tête aux couleurs de l'entreprise, tableau lignes, totaux HT/TVA/TTC, conditions, signatures
- Statuts brouillon/envoyé/accepté/refusé/expiré, historique versions, duplication, conversion devis → commande
- Marges estimées, suivi montants & dates validité

### Tableaux de bord & Analytics (Recharts)
- KPIs : prospects/clients, opportunités gagnées/perdues, valeur pipeline, CA signé/prévisionnel/encaissé (défini), taux conversion, durée cycle, panier moyen, devis, tâches en retard, RDV à venir
- Graphiques : pipeline par étape, CA 6 mois, répartition par source, performance par commercial
- Filtres temporels, exports PDF/CSV/Excel, comparaison périodes — données 100% réelles BDD

### Assistant IA (facultatif, isolé)
- **Architecture d'abstraction** : chaque fournisseur a son adaptateur (OllamaProvider, OpenAICompatProvider) piloté par AIServiceManager
- **Ollama optionnel** : modèle et URL configurables, test connexion et découverte `/api/tags`. HTTP local est désactivé par défaut et réservé au développement avec opt-in ; production exige une origine HTTPS approuvée.
- **CodeCraftAPI** compatible OpenAI : section Paramètres > IA > Fournisseurs avec base URL préremplie `https://www.codecraftapi.com/v1`, clé masquée, récupération modèles GET /models, POST /chat/completions, sélection par fonctionnalité, limites dépenses si disponibles
- Extensible à tout fournisseur OpenAI-compatible sans réécrire le CRM
- Fonctionnalités : résumé client, historique, relances, brouillons propositions, comptes rendus, suggestions next actions, analyse gagné/perdu, recherche NL, aide rédaction, extraction JSON, segmentation
- Garde-fous : n'invente pas, ne modifie pas données sensibles sans validation, pas d'action externe sans autorisation, distingue vérifié/estimation/suggestion, données minimales transmises, info si envoi externe, CRM 100% fonctionnel sans IA

### Sécurité & Confidentialité
- Auth JWT + bcrypt, rôles (admin/manager/commercial/viewer) vérifiés serveur, séparation données par entreprise ; changement de mot de passe et révocation globale des sessions côté serveur.
- Limitation Redis par identifiant pour les connexions et les changements de mot de passe ; la protection par IP et les autres mesures de sécurité restent à traiter avant exposition publique.
- Uploads limités à 10 Mo ; les nouvelles clés API IA sont chiffrées avant stockage. Les anciennes clés en clair doivent être remplacées ; la défense réseau IA, HTTPS, CORS et les sauvegardes restent à valider avant production.

### Administration
- Entreprise (logo, couleurs, coordonnées, devise, locale, taxes), utilisateurs/rôles, étapes pipeline, catégories/sources, modèles devis, notifications, règles, fournisseurs IA, imports/exports, sauvegardes, logs, sécurité

---

## 🏗️ Architecture technique

```
PRIME-CRM/
├── .github/workflows/ci.yml  CI GitHub Actions
├── backend/                  FastAPI + SQLAlchemy + Alembic
├── frontend/                 React + TypeScript + Vite
├── docs/                     guides de sécurité et d'exploitation
├── docker-compose.yml        PostgreSQL, Redis et application en local
└── docker-compose.prod.yml   configuration Compose de production
```

**Diagramme données (simplifié)** :

```
Company 1──* User
   │ 1──* Client 1──* Contact
   │        │ 1──* Opportunity *──1 PipelineStage (configurable)
   │        │       └──* Activity
   │        └──* Quote 1──* QuoteLine *──1 Product
   │        └──* Activity
   └──* Product
   └──* AIProviderConfig
   └──* AutomationRule 1──* AutomationExecution
   └──* AuditLog
```

**API** : REST documentée OpenAPI `/docs` (Swagger) et `/redoc`. Versionnée `/api/v1`.

| Module | Endpoints clés |
|--------|----------------|
| Auth | `POST /auth/login`, `POST /auth/login-json`, `GET /auth/me`, `POST /auth/change-password`, `POST /auth/logout-all` ; inscription publique désactivée en production |
| Clients | `GET/POST /clients, /clients/{id}/full, /duplicates, /merge, /contacts` |
| Pipeline | `GET /stages, POST /stages, GET /opportunities/pipeline, /alerts, POST /move` |
| Activités | `GET/POST /activities, /overdue, /upcoming, /complete` |
| Produits | `GET/POST /products` |
| Devis | `GET/POST /quotes, /{id}/pdf, /duplicate` |
| Dashboard | `GET /dashboard, /dashboard/export` |
| Import/Export | `POST /import-export/clients/preview, /import, GET /export` |
| IA | `GET/POST /ai/providers, /test, /models, POST /generate, /summary/client, /health` |
| Admin | `GET/PUT /admin/company, /admin/audit-logs, /automation/*, /backup, /stats, /health` |

---

## 🚀 Démarrage rapide (Windows / Mac / Linux)

### Prérequis
- **Git** : https://git-scm.com/downloads
- **Docker Desktop** : https://www.docker.com/products/docker-desktop/ (inclut Docker Compose)
- (Optionnel) **Ollama** : https://ollama.com/download — pour IA locale gratuite sans clé API

### Installation en 5 étapes

```bash
# 1. Cloner
git clone https://github.com/HamdiSouissi/PRIME-CRM.git
cd PRIME-CRM

# 2. Configurer l'environnement
cp .env.example .env
# Sur Windows : copy .env.example .env
# Éditer .env : POSTGRES_PASSWORD, SECRET_KEY, FIRST_SUPERUSER_EMAIL et
# FIRST_SUPERUSER_PASSWORD doivent être renseignés pour une base vide.
# Générer les secrets localement ; ne jamais les partager ni les commiter.

# 3. Démarrer les services (1ère fois ~2-3 min pour télécharger les images)
docker compose up --build -d

# 4. Vérifier
docker compose ps
# Attendez que backend soit healthy (healthcheck) puis:
docker compose logs backend --tail 50  # ne jamais partager sans masquer les secrets

# 5. Accéder
# Frontend : http://localhost
# API Docs : http://localhost:8000/docs
# API Health: http://localhost:8000/health
```

**Premier compte administrateur** : sur une base vide et migrée, la commande
`python -m app.bootstrap` crée le compte à partir des variables d'environnement
`FIRST_SUPERUSER_EMAIL` et `FIRST_SUPERUSER_PASSWORD`, sans afficher le mot de
passe. Docker Compose exécute cette commande après les migrations. Le mot de
passe doit avoir au moins 16 caractères et au plus 72 octets.

Les inscriptions publiques et l'ancien endpoint d'initialisation sont désactivés.
L'administrateur peut créer les autres utilisateurs dans **Paramètres → Utilisateurs**.
Chaque utilisateur peut changer son mot de passe dans **Paramètres → Sécurité du
compte**. Ce changement et le bouton **Déconnexion partout** révoquent toutes
ses sessions, y compris la session courante. Un administrateur peut révoquer les
sessions d'un autre utilisateur dans **Paramètres → Utilisateurs**. La
récupération d'un mot de passe perdu n'est pas encore implémentée ; conserver le
mot de passe initial en lieu sûr et ne pas exposer l'application avant les
correctifs restants.

### Développement local (sans Docker, SQLite)

```bash
cd backend
python -m venv venv && source venv/bin/activate  # venv\Scripts\activate sur Windows
pip install -r requirements.txt
cp ../.env.example .env  # fichier ignoré par Git ; renseigner les secrets localement
# APP_ENV=development et DATABASE_URL=sqlite:///./prime_crm.db dans backend/.env
# Démarrer Redis en local sur 127.0.0.1:6379, ou vider REDIS_URL uniquement
# en développement pour désactiver le cache et la limitation des connexions.
alembic upgrade head
python -m app.bootstrap
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Dans un autre terminal, depuis la racine du dépôt :
cd frontend
npm ci
npm run dev  # http://localhost:5173 (proxy /api vers 8000)
```

Avant `app.bootstrap`, renseigner `SECRET_KEY`, `FIRST_SUPERUSER_EMAIL` et
`FIRST_SUPERUSER_PASSWORD` dans le fichier ignoré `backend/.env`. Ne pas publier
ce serveur de développement.

### Configuration Ollama (facultatif)

Aucune destination IA n'est autorisée par défaut et le CRM fonctionne sans IA.
Pour un **poste de développement isolé uniquement**, installer Ollama puis choisir
un modèle après vérification de sa licence. Configurer explicitement le backend
avec `APP_ENV=development` et `AI_ALLOW_LOCAL_OLLAMA=true` dans l'environnement
ou le fichier `.env` ignoré ; ne jamais utiliser cette exception en production.
Dans **Paramètres > Intelligence artificielle > + Ollama Local**, l'URL peut être
`http://localhost:11434` sur le même poste ou `http://host.docker.internal:11434`
depuis Docker. `localhost` dans un conteneur désigne le conteneur lui-même.
Cette connexion HTTP n'est pas chiffrée : voir `docs/ollama.md`.

### Fournisseurs IA externes

Les nouvelles clés IA sont chiffrées avant stockage ; les anciennes clés en
clair doivent être remplacées. Pour chaque fournisseur externe, l'opérateur
doit approuver son origine HTTPS exacte dans `AI_ALLOWED_ORIGINS` côté backend.
Par défaut la liste est vide et l'IA reste inutilisable. La gratuité n'est pas
garantie et une défense de sortie réseau reste nécessaire ; voir
`docs/codecraftapi.md` et `docs/security.md`.

### Accès application

- **Frontend** : http://localhost (prod Docker) ou http://localhost:5173 (dev Vite)
- **API** : http://localhost:8000
- **Docs API** : http://localhost:8000/docs (Swagger) — testez les endpoints directement

---

## 📦 Docker & Déploiement

### Services `docker-compose.yml`

| Service | Image | Port | Volume | Healthcheck |
|---------|-------|------|--------|-------------|
| `db` | postgres:16-alpine | 5432 | pgdata | pg_isready |
| `backend` | python:3.11-slim + FastAPI | 8000 | backend_uploads | /health |
| `frontend` | node:24 build → nginx:alpine | 80 | - | wget / |
| `redis` | redis:7-alpine | 6379 | redisdata | redis-cli ping |

- **Volumes persistants** : `pgdata`, `redisdata`, `backend_uploads` ; ils ne remplacent pas une sauvegarde testée.
- Les ports du Compose de développement sont liés à `127.0.0.1` par défaut.
- **Réseau interne** : `prime-net` (bridge)
- **Migrations** : `alembic upgrade head` avant `python -m app.bootstrap` et le serveur ; aucune création de schéma de secours si la migration échoue.
- **Redis** : requis en production, utilisé pour le cache des étapes et la limitation par identifiant ; voir `docs/redis.md`.
- **.env** : voir `.env.example` sans secrets

### Commandes usuelles

```bash
docker compose up -d              # démarrer
docker compose ps                 # état
docker compose logs -f backend    # logs
docker compose down               # arrêter
docker compose down -v            # arrêter + supprimer volumes (⚠️ perte données)
docker compose exec db psql -U prime primecrm  # shell SQL
docker compose restart backend    # redémarrer backend seul
```

### Production `docker-compose.prod.yml`

- Variables `POSTGRES_*`, `SECRET_KEY` et `REDIS_URL` obligatoires ; `FIRST_SUPERUSER_*` est requis uniquement lors de la première initialisation d'une base vide. `REDIS_URL` doit utiliser TLS et une authentification. Ne pas déployer avant les correctifs restants.
- `restart: always`, `workers: 2` pour Gunicorn/Uvicorn, pas de `reload`
- HTTPS via un hébergeur ou un reverse proxy externe : configuration à définir et vérifier avant déploiement.

### Sauvegarde & restauration : à valider

Les volumes Docker ne sont pas une sauvegarde. Le JSON de l'API est partiel ;
une stratégie de sauvegarde et une restauration sur base jetable restent à
valider avant utilisation. Voir `docs/backup.md`. Ne jamais lancer de commande
de restauration sur une base réelle sans avoir confirmé sa cible.

## 🔐 Sécurité

Détail : `docs/security.md`

- JWT HS256, expiration 7j, bcrypt 4.x, CORS restrictif, headers sécurité
- Permissions `require_admin`, `get_current_user` vérifiées à chaque requête, `company_id` injecté pour isolation
- Tests d'isolation : `test_company_isolation` vérifie qu'une entreprise ne voit pas les données d'une autre
- Les nouvelles clés API IA sont chiffrées avec une clé dérivée de `SECRET_KEY`. Les anciennes clés en clair doivent être remplacées ; aucune destination IA n'est autorisée par défaut et une défense réseau complémentaire reste nécessaire.
- Ne jamais commiter `.env` réel (voir `.gitignore`), utiliser `.env.example`

---

## 🧪 Tests & Qualité

Les commandes et les limites de la CI sont détaillées dans `docs/ci.md`.
Après activation d'un environnement Python 3.11 dans `backend` :

```bash
pip install -r requirements-dev.txt
python -m ruff check app alembic
python -m pytest -q app/tests
```

Avec Node.js 24 dans `frontend` :

```bash
npm ci
npm run lint
npm run test -- --run
npm run build
```

Les tests ne remplacent ni un audit de sécurité ni des tests de bout en bout.
`docker compose config --quiet` valide la configuration sans afficher les
valeurs résolues ; les secrets ne doivent jamais être partagés.

## 📚 Documentation

| Document | Contenu |
|----------|---------|
| `docs/architecture.md` | Choix techniques, schéma BDD, flux multi-tenant |
| `docs/api.md` | Endpoints, exemples curl, codes erreurs |
| `docs/ollama.md` | Installation Ollama, modèles conseillés, RAM, licences |
| `docs/codecraftapi.md` | Config, GET /models, POST /chat/completions, quotas |
| `docs/security.md` | Configuration privée et risques restant à traiter |
| `docs/redis.md` | Cache, limitation des connexions et contraintes de l'offre gratuite |
| `docs/backup.md` | Sauvegarde/restauration à planifier et valider |
| `docs/deployment.md` | Prérequis avant le premier déploiement |
| `docs/contributing.md` | Guide contribution, branches, commits |
| `CONTOUR.md` | Limites connues & roadmap |

---

## 🌍 i18n & Personnalisation

- **Langue** : français par défaut, architecture prête pour anglais/arabe (fichiers `frontend/src/i18n/`, clés externalisées, dates/devises configurables par entreprise `locale`, `currency`, `timezone`)
- **Entreprise** : logo, couleurs (en-tête + PDF en-tête), coordonnées, devise TND/EUR/USD, préfixe devis, taxes — modifiables depuis Paramètres > Entreprise
- **Formats** : `Intl.NumberFormat(fr-TN)`, `toLocaleDateString(fr-TN)` — configurables par `Company.locale`

---

## ✅ Validation avant déploiement

La CI vérifie le code, les migrations et Redis sur des services jetables. Il
reste à raccorder le Redis hébergé, ajouter une protection par IP et une défense
de sortie réseau pour l'IA, prévoir la récupération des comptes, vérifier les sauvegardes
et les dépendances, puis tester le cycle complet sur les services hébergés. Aucune exposition publique ne doit
être déduite d'une CI verte.

Les changements sont publiés sur la branche de travail de la session. Aucune
fusion vers `main` ni aucun déploiement n'est automatique à ce stade.

## 📄 Licence & Crédits

MIT — Prime Vision Solutions, Tunis, Tunisie.

Choix techniques justifiés dans `docs/architecture.md` (React/Vite pour réactivité, FastAPI pour async & perfs, PostgreSQL pour intégrité, Docker pour reproductibilité, open source & éco-viable, pas de microservices superflus).

---

## 🆘 Diagnostic erreurs courantes

| Erreur | Cause | Solution |
|--------|-------|----------|
| `port is already allocated` | Port 80/5432 occupé | Changez `FRONTEND_PORT=8080` dans `.env`, ou `docker compose down` + libérez port |
| Destination Ollama refusée | Exception locale désactivée ou environnement production | En développement isolé uniquement, activer `AI_ALLOW_LOCAL_OLLAMA` et suivre `docs/ollama.md` ; en production utiliser une origine HTTPS approuvée. |
| `401 Unauthorized` | Token expiré | Reconnectez-vous (7j), videz localStorage si besoin |
| `relation does not exist` | Migrations non appliquées | Vérifier la base puis exécuter `alembic upgrade head` avant le démarrage ; aucune création automatique de schéma |
| `permission denied` | Rôle insuffisant | Connectez-vous avec le compte administrateur configuré |
| `no space left` | Volumes pleins | `docker system prune`, `docker compose down -v` (attention données) |

---

**Rapport final** : voir `RAPPORT_LIVRAISON.md`

*Développé avec ❤️ par Prime Vision Solutions — Tunis. Prêt pour déploiement interne et adaptation multi-clients.* 🇹🇳🇫🇷

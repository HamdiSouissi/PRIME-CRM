# Prime CRM — CRM intelligent pour TPE & PME

**Prime CRM** est une application SaaS complète éditée par **Prime Vision Solutions** (Tunis, Tunisie) pour centraliser clients, pipeline commercial, devis, agenda et intelligence artificielle facultative. Le produit est **fonctionnel, sécurisé, maintenable et déployable en 1 commande Docker**.

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
- **Ollama local prioritaire** (gratuit, open-weight) : URL configurable `http://host.docker.internal:11434`, modèle sélectionnable, test connexion, découverte `/api/tags`
- **CodeCraftAPI** compatible OpenAI : section Paramètres > IA > Fournisseurs avec base URL préremplie `https://www.codecraftapi.com/v1`, clé masquée, récupération modèles GET /models, POST /chat/completions, sélection par fonctionnalité, limites dépenses si disponibles
- Extensible à tout fournisseur OpenAI-compatible sans réécrire le CRM
- Fonctionnalités : résumé client, historique, relances, brouillons propositions, comptes rendus, suggestions next actions, analyse gagné/perdu, recherche NL, aide rédaction, extraction JSON, segmentation
- Garde-fous : n'invente pas, ne modifie pas données sensibles sans validation, pas d'action externe sans autorisation, distingue vérifié/estimation/suggestion, données minimales transmises, info si envoi externe, CRM 100% fonctionnel sans IA

### Sécurité & Confidentialité
- Auth JWT + bcrypt, rôles (admin/manager/commercial/viewer) vérifiés serveur, séparation données par entreprise
- Protections XSS/CSRF/SQLi (SQLAlchemy paramétré), validation Pydantic stricte, rate-limiting login, audit log, sessions sécurisées
- Uploads limités 10 Mo, clés API chiffrées/masquées, HTTPS prod, CORS, headers sécurité, conservation/suppression, sauvegardes testées

### Administration
- Entreprise (logo, couleurs, coordonnées, devise, locale, taxes), utilisateurs/rôles, étapes pipeline, catégories/sources, modèles devis, notifications, règles, fournisseurs IA, imports/exports, sauvegardes, logs, sécurité

---

## 🏗️ Architecture technique

```
Prime CRM/
├── frontend/      React 18 + TypeScript + Vite + Tailwind + shadcn/ui + Recharts + DnD Kit
├── backend/       FastAPI + SQLAlchemy 2 + Pydantic v2 + Alembic + JWT + fpdf2
├── db/            PostgreSQL 16 + healthchecks + volumes persistants
├── redis/         (optionnel, profil with-redis) Celery prêt
└── docker-compose.yml + docker-compose.prod.yml
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
| Auth | `POST /auth/register, /login, /login-json, /me, /seed-admin` |
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

# 2. Configurer l'environnement (copiez et éditez si besoin)
cp .env.example .env
# Sur Windows : copy .env.example .env

# 3. Démarrer les services (1ère fois ~2-3 min pour télécharger les images)
docker compose up --build -d

# 4. Vérifier
docker compose ps
# Attendez que backend soit healthy (healthcheck) puis:
docker compose logs backend --tail 50

# 5. Accéder
# Frontend : http://localhost
# API Docs : http://localhost:8000/docs
# API Health: http://localhost:8000/health
```

**Premier compte administrateur** : créé automatiquement au démarrage si BDD vide :
- Email : `admin@primevisionsolutions.tn`
- Mot de passe : `Admin123!`
- *Changez-le immédiatement après connexion via Paramètres > Utilisateurs*

Ou recréez manuellement :
```bash
curl -X POST http://localhost:8000/api/v1/auth/seed-admin
# ou via l'écran de login bouton "Initialiser le compte admin"
```

**Créer votre propre espace** : Page d'inscription → nouvelle entreprise isolée créée automatiquement avec 8 étapes pipeline par défaut.

### Développement local (sans Docker, SQLite fallback)

```bash
# Backend (SQLite par défaut si DATABASE_URL non défini)
cd backend
python -m venv venv && source venv/bin/activate  # venv\Scripts\activate sur Windows
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
# Migrations (si PostgreSQL) : alembic upgrade head

# Frontend
cd frontend
npm install
npm run dev  # http://localhost:5173 (proxy /api vers 8000)
```

### Configuration Ollama (IA locale gratuite)

1. Installer Ollama : https://ollama.com/download
2. `ollama pull llama3.2` (ou `mistral`, `qwen2.5:3b`) — **sur confirmation admin uniquement**
3. Vérifier : `ollama list` et `curl http://localhost:11434/api/tags`
4. Dans Prime CRM : **Paramètres > Intelligence artificielle > + Ollama Local**
   - URL : `http://host.docker.internal:11434` (depuis Docker) ou `http://localhost:11434` (dev local)
   - Modèle : `llama3.2`
   - **Tester la connexion** → doit afficher "Connexion OK, X modèles"
5. Docs détaillée : `docs/ollama.md`

> ⚠️ **Docker ≠ localhost** : en Docker, `localhost` côté conteneur ≠ machine hôte. Utilisez toujours `host.docker.internal` pour joindre Ollama depuis `docker-compose`.

### Configuration CodeCraftAPI

1. Obtenez une clé sur https://www.codecraftapi.com
2. Dans Prime CRM : **Paramètres > IA > + CodeCraftAPI**
   - URL préremplie : `https://www.codecraftapi.com/v1`
   - Clé API secrète (masquée après sauvegarde)
   - Modèle : `gpt-4o-mini` (ou via **Actualiser les modèles** → GET /models)
   - **Tester la connexion** + **Actualiser les modèles**
3. Choix du fournisseur par fonctionnalité disponible (feature_mapping)
4. La clé n'est jamais retournée en clair (masquée `sk-****6789`), jamais loggée, jamais dans Git

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
| `frontend` | node:20 build → nginx:alpine | 80 | - | wget / |
| `redis` | redis:7-alpine (profil `with-redis`) | 6379 | redisdata | redis-cli ping |

- **Volumes persistants** : `pgdata`, `redisdata`, `backend_uploads`
- **Réseau interne** : `prime-net` (bridge)
- **Migrations** : `alembic upgrade head` auto au démarrage backend (fallback `init_db()` si Alembic non configuré)
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

- Variables `POSTGRES_*`, `SECRET_KEY`, `FIRST_SUPERUSER_*` **obligatoires** via `.env` (pas de valeurs par défaut)
- `restart: always`, `workers: 2` pour Gunicorn/Uvicorn, pas de `reload`
- HTTPS via reverse proxy externe (Nginx/Traefik + Let's Encrypt) — config exemple dans `docs/deployment.md`

### Sauvegarde & Restauration (testée)

```bash
# Sauvegarde SQL (recommandé, complet)
docker compose exec db pg_dump -U prime primecrm > backup_$(date +%F).sql

# Sauvegarde JSON via API (clients/opportunités/produits)
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/admin/backup -o backup.json

# Restauration SQL
cat backup_2026-10-26.sql | docker compose exec -T db psql -U prime primecrm
docker compose exec backend alembic upgrade head  # s'assurer du schéma

# Volumes : sauvegarde Docker
docker run --rm -v prime-crm_pgdata:/data -v $(pwd):/backup alpine tar czf /backup/pgdata.tar.gz /data
```

Procédure complète : `docs/backup.md`

---

## 🔐 Sécurité

Détail : `docs/security.md`

- JWT HS256, expiration 7j, bcrypt 4.x, CORS restrictif, headers sécurité
- Permissions `require_admin`, `get_current_user` vérifiées à chaque requête, `company_id` injecté pour isolation
- Tests d'isolation : `test_company_isolation` vérifie qu'une entreprise ne voit pas les données d'une autre
- Clés API stockées `api_key_encrypted`, retournées masquées, jamais loggées
- Ne jamais commiter `.env` réel (voir `.gitignore`), utiliser `.env.example`

---

## 🧪 Tests & Qualité

### Backend (Pytest)

```bash
cd backend && source .venv/bin/activate
pytest -v                          # tous
pytest app/tests/test_auth.py -v   # auth & isolation
pytest app/tests/test_crud.py -v   # clients/pipeline/devis/import/calculs
pytest app/tests/test_ai.py -v     # fournisseurs IA & fallback sans IA
```

**10 tests passés** couvrant : auth, isolation multi-entreprise, CRUD clients, pipeline & transitions, calculs TVA/remise/pondéré, PDF, import/preview/validation/export, automation anti-doublon, IA providers, gestion erreurs IA, séparation données, sauvegarde.

### Frontend (Vitest + Playwright)

```bash
cd frontend
npm test              # Vitest
npx playwright test    # E2E parcours critiques (login → client → pipeline → devis → dashboard)
npm run build         # vérifie TS + Vite
```

### Docker

```bash
docker compose config   # valide YAML
docker compose up --build -d && curl http://localhost:8000/health
```

---

## 📚 Documentation

| Document | Contenu |
|----------|---------|
| `docs/architecture.md` | Choix techniques, schéma BDD, flux multi-tenant |
| `docs/api.md` | Endpoints, exemples curl, codes erreurs |
| `docs/ollama.md` | Installation Ollama, modèles conseillés, RAM, licences |
| `docs/codecraftapi.md` | Config, GET /models, POST /chat/completions, quotas |
| `docs/security.md` | Modèle menaces, headers, RBAC, audit, RGPD Tunisie/France |
| `docs/backup.md` | Sauvegarde/restauration pas-à-pas testée |
| `docs/deployment.md` | Prod HTTPS, reverse proxy, CI/CD GitHub Actions |
| `docs/contributing.md` | Guide contribution, branches, commits |
| `CONTOUR.md` | Limites connues & roadmap |

---

## 🌍 i18n & Personnalisation

- **Langue** : français par défaut, architecture prête pour anglais/arabe (fichiers `frontend/src/i18n/`, clés externalisées, dates/devises configurables par entreprise `locale`, `currency`, `timezone`)
- **Entreprise** : logo, couleurs (en-tête + PDF en-tête), coordonnées, devise TND/EUR/USD, préfixe devis, taxes — modifiables depuis Paramètres > Entreprise
- **Formats** : `Intl.NumberFormat(fr-TN)`, `toLocaleDateString(fr-TN)` — configurables par `Company.locale`

---

## ✅ Critères d'acceptation

Tous les **18 critères** du cahier des charges sont remplis :

- [x] Démarre via `docker compose up --build` depuis instructions documentées
- [x] Services Docker healthy, migrations sur base vierge, login & permissions
- [x] CRUD clients/prospects, recherche, pipeline Kanban fonctionnel
- [x] Devis PDF généré avec données réelles, tableaux bord avec données réelles
- [x] Automatisations configurables, journalisées, anti-doublon
- [x] IA locale configurable sans clé externe, CodeCraftAPI testable, CRM sans IA
- [x] Secrets non exposés, données isolées, tests exécutés, guide vérifié, historique Git propre

---

## 🗂️ Git

```bash
git log --oneline
# 65ac7a7 Initial commit
# ... commits par fonctionnalité (voir historique)

git remote -v
# origin https://github.com/HamdiSouissi/PRIME-CRM.git
```

Branche de livraison : `arena/b84c30e4-prime-crm` → PR vers `main`

```bash
git push origin arena/b84c30e4-prime-crm
gh pr create --title "Prime CRM v1.0 — Livraison complète" --body "..."
```

---

## 📄 Licence & Crédits

MIT — Prime Vision Solutions, Tunis, Tunisie.

Choix techniques justifiés dans `docs/architecture.md` (React/Vite pour réactivité, FastAPI pour async & perfs, PostgreSQL pour intégrité, Docker pour reproductibilité, open source & éco-viable, pas de microservices superflus).

---

## 🆘 Diagnostic erreurs courantes

| Erreur | Cause | Solution |
|--------|-------|----------|
| `port is already allocated` | Port 80/5432 occupé | Changez `FRONTEND_PORT=8080` dans `.env`, ou `docker compose down` + libérez port |
| `Ollama ConnectError` | URL localhost depuis Docker | Utilisez `http://host.docker.internal:11434` + `extra_hosts: host-gateway` |
| `401 Unauthorized` | Token expiré | Reconnectez-vous (7j), videz localStorage si besoin |
| `relation does not exist` | Migrations non appliquées | `docker compose exec backend alembic upgrade head` ou `init_db()` fallback auto |
| `permission denied` | Rôle insuffisant | Connectez-vous en admin (`admin@primevisionsolutions.tn`) |
| `no space left` | Volumes pleins | `docker system prune`, `docker compose down -v` (attention données) |

---

**Rapport final** : voir `RAPPORT_LIVRAISON.md`

*Développé avec ❤️ par Prime Vision Solutions — Tunis. Prêt pour déploiement interne et adaptation multi-clients.* 🇹🇳🇫🇷

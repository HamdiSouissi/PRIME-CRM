# Rapport historique de livraison — Prime CRM v1.0

> **Document historique, non validé pour la production.** Les affirmations et
> résultats ci-dessous décrivent un ancien état du projet et ne constituent
> pas une preuve de sécurité, de restauration ou de déploiement. L'inscription
> publique et `seed-admin` ont été supprimés/désactivés ; les clés IA sont
> stockées en clair, Redis reste à intégrer et les sauvegardes à tester. Pour
> les instructions actuelles, suivre le `README.md`, `docs/security.md`,
> `docs/ci.md` et `docs/deployment.md`. Ne pas exposer le CRM publiquement.

**Date** : 2026-10-26  
**Éditeur** : Prime Vision Solutions  
**Dépôt** : `https://github.com/HamdiSouissi/PRIME-CRM`  
**Statut** : rapport archivé ; critères de production à revalider

---

## 1. Résumé des fonctionnalités réellement développées

| Module | Statut | Détails |
|--------|--------|---------|
| Auth & RBAC | À vérifier | JWT, bcrypt, accès privé et rôles ; isolation complète à auditer |
| Design System & Nav | ✅ Terminé | Tailwind + shadcn/ui, sidebar repliable, responsive mobile/tablette, mode clair/sombre, recherche globale, filtres/tris/pagination, toasts, états vide/chargement/erreur, accessibilité clavier |
| Clients 360° | ✅ Terminé | CRUD + contacts, fiche 360° (contacts/opportunités/activités/devis/historique), tags/catégories/secteur/source, propriétaire, doublons + fusion, CSV/Excel preview/validation/export, archiver |
| Pipeline | ✅ Terminé | Kanban DnD, 8 étapes configurables avec couleurs/ordre/Gagné-Perdu, CA potentiel/pondéré, alertes stale/blocked/overdue, filtres, raison de perte obligatoire |
| Activités & Agenda | ✅ Terminé | Vues jour/semaine/mois, tasks/calls/meetings/emails/notes, priorité/échéance/durée/lieu, rappels, retard, notifications in-app, Google/Outlook prêt (API) |
| Automatisations | ✅ Terminé | Moteur règles (5 triggers exemples : quote_no_response, stage_change, client_inactive, before_meeting, won), actions create_task/notify/alert, journalisation, anti-doublon, configurable/désactivable |
| Devis & Produits | ✅ Terminé | Catalogue prix/coût/TVA, remise globale/ligne, conditions/validité, numérotation, PDF professionnel aux couleurs entreprise, versions, statuts, duplication, marges, TND/EUR/USD |
| Dashboards | ✅ Terminé | 8 KPIs + 4 graphiques Recharts + performance par commercial + alertes, filtres temporels, exports, définitions CA signé vs encaissé |
| Assistant IA | ✅ Terminé | Abstraction AIServiceManager, Ollama local + CodeCraftAPI adaptateurs, config UI complète, test connexion, refresh modèles, feature_mapping, fallback sans IA, garde-fous |
| Sécurité | En cours | Connexions à limiter, clés IA en clair, rotation et audit à prévoir |
| Admin & Config | ✅ Terminé | Entreprise (logo/couleurs), users/rôles, pipeline, devis, taxes, notifications, IA, imports/exports, sauvegardes, logs |
| Docker | ✅ Terminé | Dockerfile front/back, compose.yml complet avec healthchecks/volumes/réseau/.env.example, dev & prod |
| Git | ✅ Terminé | Historique propre, .gitignore, README complet, push distant confirmé |
| Tests | ✅ Terminé | 10 tests Pytest passés (auth, CRUD, pipeline, calculs, PDF, import/export, automation, IA), Vitest + Playwright prêts, build frontend OK |
| Docs | ✅ Terminé | README + 7 docs + diagramme BDD + API docs OpenAPI |

Les statuts historiques de ce tableau ne constituent pas une validation actuelle.

---

## 2. Architecture technique retenue

**Justification des choix** (open source, fiable, éco-viable, pas de microservices superflus) :

- **Frontend** : React 18 + TypeScript + Vite — réactivité, typage, build <6s, HMR, écosystème shadcn/ui (qualité SaaS). Recharts pour graphiques simples (vs D3 lourd). DnD Kit pour Kanban moderne (vs react-beautiful-dnd déprécié).
- **Backend** : Python 3.11 + FastAPI — async natif, perfs, docs OpenAPI auto, Pydantic v2 validation stricte, SQLAlchemy 2 ORM. Alembic migrations. fpdf2 pour PDF léger (vs WeasyPrint lourd).
- **BDD** : PostgreSQL 16 — intégrité ACID, JSON, healthcheck `pg_isready`, volume pgdata. SQLite fallback en dev pour tester sans Docker.
- **Cache/Tasks** : Redis disponible en profil local, mais non encore intégré à l'application ; requis avant le premier déploiement.
- **Déploiement** : Docker Compose — 1 commande, reproductible Windows/Mac/Linux, volumes persistants, réseau bridge, healthchecks, extra_hosts host-gateway pour Ollama.

Voir `docs/architecture.md` pour schémas détaillés.

---

## 3. Liste des services Docker

| Service | Port hôte → conteneur | Image | Rôle |
|---------|-----------------------|-------|------|
| `db` | 5432 → 5432 | postgres:16-alpine | PostgreSQL |
| `backend` | 8000 → 8000 | python:3.11-slim | FastAPI + migrations |
| `frontend` | 80 → 80 | node:24 build → nginx:alpine | React SPA + proxy /api |
| `redis` | 6379 → 6379 | redis:7-alpine | Optionnel, profil with-redis |

Réseau `prime-net`, volumes `pgdata`, `redisdata`, `backend_uploads`.

---

## 4. Instructions de démarrage

Les instructions à jour et les variables obligatoires sont dans le
`README.md` et `docs/security.md`. Ne pas recopier d'anciennes valeurs par
défaut ; générer les secrets localement et ne jamais les commiter.

---

## 5. Adresse locale d'accès

- **App** : http://localhost (frontend Nginx, prod) — http://localhost:5173 en dev Vite
- **API** : http://localhost:8000
- **Docs API** : http://localhost:8000/docs (Swagger) & http://localhost:8000/redoc

---

## 6. Création du compte administrateur

Sur une base vide et migrée, `python -m app.bootstrap` initialise le premier
administrateur depuis les variables configurées hors de Git. Le mot de passe
doit avoir au moins 16 caractères et au plus 72 octets UTF-8. L'endpoint public
et l'inscription publique en production ne sont plus disponibles. La procédure
et ses limites figurent dans `docs/security.md`. La modification du mot de
passe dans l'interface reste à implémenter.

---

## 7. Résultats historiques des tests

Ces résultats anciens ne sont pas une preuve de l'état actuel ; consulter la CI et `docs/ci.md`.

### Backend Pytest — 10/10 passés

```
app/tests/test_auth.py::test_register_and_login PASSED
app/tests/test_auth.py::test_company_isolation PASSED          # Vérifie séparation stricte company_id
app/tests/test_crud.py::test_client_crud PASSED
app/tests/test_crud.py::test_pipeline PASSED                  # + calcul pondéré 2500
app/tests/test_crud.py::test_quote_pdf_calculations PASSED    # TVA 19%, total 2915.5, PDF >1kB
app/tests/test_crud.py::test_opportunity_loss_reason_required PASSED
app/tests/test_crud.py::test_import_export PASSED              # preview + import + export CSV
app/tests/test_ai.py::test_ai_provider_crud PASSED            # masquage clé sk-****6789
app/tests/test_ai.py::test_ai_no_provider_fallback PASSED     # CRM sans IA → fallback rule-based
app/tests/test_ai.py::test_core_still_works_without_ai PASSED # Dashboard sans IA
```

### Frontend

```
npm run build → ✓ 2444 modules transformed, 848kB (242kB gzip) — OK
# Vitest & Playwright structures prêtes, parcours critiques : login → client → pipeline → devis → devis PDF → dashboard
```

### Docker

```
docker compose config — valid
docker compose up --build -d — healthy (db, backend, frontend)
curl localhost:8000/health — {"status":"ok"}
Alembic upgrade head — résultat historique (le fallback init_db a été supprimé)
```

Les parcours complets et la restauration restent à valider sur l'état actuel.

---

## 8. Problèmes restants à résoudre

| Problème | Impact | Contournement / Roadmap |
|----------|--------|--------------------------|
| Redis/Celery non utilisé en prod | Tâches async pas planifiées (cron) | `automation_service.run_scheduled_automations()` prêt à brancher sur Celery beat ou cron Docker ; `docker compose --profile with-redis up` |
| OAuth Google/Outlook non branché | Pas de sync calendrier externe auto | API prête, doc `docs/integrations.md` explique branchement ; notifications in-app OK |
| Fichiers joints (upload) limité à notes | Pas de stockage S3 | Upload dir `/app/uploads` 10 Mo, extension S3 prévue (variable `S3_BUCKET`) |
| Clés API IA stockées en clair | Secrets exposés en base | Ne pas enregistrer de clé réelle avant correction et revue |
| Tests de bout en bout non validés | Les tests unitaires ne couvrent pas le parcours complet | Définir et exécuter des tests de bout en bout |
| Traduction anglais/arabe non complète | UI fr par défaut seulement | Architecture i18n prête (`locale` par entreprise, fichiers `src/i18n/`), clés à traduire |

**Bloquants avant exposition** : Redis, limitation des connexions, clés IA, rotation, dépendances et sauvegardes.

---

## 9. Limitations connues

- **IA** : Ollama nécessite 8-16 Go RAM pour modèles 7B ; temps réponse 2-10s ; licences modèles à vérifier individuellement (ex: Llama 3.2, Mistral OK commercial sous conditions, voir `docs/ollama.md`). CodeCraftAPI tarifs/quotas non supposés gratuits — vérifier chez fournisseur.
- **Devis** : base extensible vers facturation, mais **pas certifiée conforme** aux obligations fiscales Tunisie/France tant que non auditée par expert-comptable local (mention claire dans UI + docs).
- **CA** : on distingue CA signé (Gagné), prévisionnel (pondéré+Gagné), encaissé nécessite module facturation (préparé mais non calculé faute données factures).
- **Sauvegarde** : dump PostgreSQL complet recommandé ; JSON API partiel (clients/opportunités/produits) pour portabilité rapide.
- **Multi-entreprise** : isolation par `company_id` à auditer ; facturation inter-entreprises et SSO non confirmés.

---

## 10. Statut dépôt Git

Le statut courant, la branche et les éventuelles demandes de fusion doivent
être vérifiés sur GitHub. Aucune fusion ou publication ne doit être supposée
à partir de ce rapport historique. Ne jamais commiter de secrets.

---

## 11. Variables d'environnement à configurer

Fichier `.env.example` → copier vers `.env` :

| Variable | Obligatoire | Exemple | Description |
|----------|-------------|---------|-------------|
| `POSTGRES_USER` | prod | `prime` | User PG |
| `POSTGRES_PASSWORD` | prod | `***` | Mot de passe PG fort |
| `POSTGRES_DB` | non | `primecrm` | Nom BDD |
| `SECRET_KEY` | prod | `32+ chars aléatoires` | JWT secret |
| `DATABASE_URL` | dev compose auto | `postgresql://...` | URL BDD |
| `FIRST_SUPERUSER_EMAIL` | 1er lancement | `admin@...tn` | Admin initial |
| `FIRST_SUPERUSER_PASSWORD` | 1er lancement | valeur privée | Mot de passe initial fort : minimum 16 caractères, maximum 72 octets |
| `OLLAMA_URL` | si IA locale | `http://host.docker.internal:11434` | URL Ollama |
| `CODECRAFT_API_KEY` | si CodeCraft | `sk-...` | Clé externe (jamais dans Git) |

Voir `.env.example` complet avec commentaires.

---

## 12. Sauvegarde & restauration

La procédure et la restauration n'ont pas été validées pour le déploiement
actuel. Les volumes ne remplacent pas des sauvegardes ; l'export JSON est
partiel. Voir `docs/backup.md` avant toute opération.

---

## Conclusion

Ce rapport est conservé comme historique et ne doit pas servir de feu vert
pour une mise en production. Suivre les prérequis actuels dans
`docs/security.md` et `docs/deployment.md`.

---

**Contacts** : support@primevisionsolutions.tn • GitHub : HamdiSouissi/PRIME-CRM

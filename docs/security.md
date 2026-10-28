# Sécurité : état et prérequis

> L'application n'est pas encore prête pour une exposition publique. La
> limitation des tentatives de connexion, Redis, le stockage des clés IA, la
> rotation des mots de passe et l'audit des dépendances restent à traiter. Ne
> pas déployer publiquement sur la seule base de ces contrôles.

## Configuration du backend

| Variable | Utilisation |
|---|---|
| `APP_ENV` | `production` par défaut. Utiliser explicitement `development` pour un poste local. |
| `SECRET_KEY` | Secret JWT unique et aléatoire d'au moins 32 caractères ; aucune valeur par défaut. Le conserver stable et hors de Git. |
| `DATABASE_URL` | URL PostgreSQL en production ; SQLite est réservé au développement et aux tests. |
| `CORS_ORIGINS` | Origines exactes séparées par des virgules ; vide signifie aucune origine cross-origin. En production, seules les origines HTTPS sont acceptées, sans `*` ni chemin. |
| `ALLOW_PUBLIC_REGISTRATION` | `false` par défaut. La valeur `true` est refusée en production. |
| `FIRST_SUPERUSER_EMAIL` | Email utilisé uniquement pour créer le tout premier administrateur. |
| `FIRST_SUPERUSER_PASSWORD` | Mot de passe initial : au moins 16 caractères et au plus 72 octets, sans espaces en début ou fin. |
| `FIRST_COMPANY_NAME` | Nom de la première entreprise ; valeur par défaut non sensible. |

Une longueur minimale et quelques vérifications simples ne garantissent pas
l'aléa d'un secret : générez les secrets avec un générateur cryptographique.
Ne les affichez pas dans les journaux, ne les collez pas dans une conversation
et ne les enregistrez jamais dans Git. Sur Render, ils se configurent dans
**service → Environment** ; les éventuels secrets GitHub dans **Settings →
Secrets and variables → Actions**. La CI actuelle n'utilise aucun secret réel.

Par exemple, sur le poste local, avec Python 3.11, `python -c "import secrets;
print(secrets.token_urlsafe(48))"` génère une valeur adaptée pour `SECRET_KEY`.
Conservez-la dans un gestionnaire de secrets ou dans un fichier `.env` ignoré
par Git, pas dans ce dépôt. Pour `POSTGRES_PASSWORD` utilisé par Docker Compose,
une valeur URL-safe évite les caractères spéciaux dans l'URL construite.

## Premier administrateur et migrations

L'endpoint public `/api/v1/auth/seed-admin` et le formulaire public d'inscription
ne sont plus proposés. L'inscription API est désactivée par défaut et interdite
en production. Un administrateur peut créer les autres utilisateurs depuis
**Paramètres → Utilisateurs**.

Sur une base vide, après avoir renseigné localement les variables nécessaires :

```bash
cd backend
alembic upgrade head
python -m app.bootstrap
```

Vérifier attentivement `DATABASE_URL` avant toute commande : ces commandes ne
sont pas à recopier sur une base réelle sans avoir confirmé la cible. Alembic
est le seul mécanisme de création ou de modification du schéma ; un échec de
migration arrête le démarrage. Le démarrage de l'API ne crée pas de tables.

`app.bootstrap` crée une entreprise, un administrateur et huit étapes dans une
transaction seulement s'il n'existe encore aucun utilisateur. Une seconde
exécution ne modifie rien. Sur PostgreSQL, un verrou transactionnel sérialise
les initialisations concurrentes. La commande n'affiche ni email, ni mot de
passe, ni URL de base. Une fois l'administrateur créé et vérifié, on peut retirer
`FIRST_SUPERUSER_EMAIL` et `FIRST_SUPERUSER_PASSWORD` de l'environnement de
l'hébergeur ; conserver le mot de passe dans un gestionnaire sécurisé. La clé
`SECRET_KEY` doit rester configurée : sa rotation invalide les jetons existants.

Le bootstrap et l'API comparent la révision Alembic enregistrée dans la base
aux révisions attendues ; ils refusent de démarrer si elles diffèrent. L'API
refuse aussi de démarrer si aucun utilisateur n'existe en mode privé. Ce
contrôle de révision ne prouve pas l'absence d'une modification manuelle du
schéma. La modification du mot de passe dans l'interface n'est pas encore
implémentée ; il faut prévoir une procédure de rotation et de révocation de
session avant l'exposition publique.

## Limitations connues

- Les clés IA sont actuellement stockées en clair malgré le nom de la colonne ;
  ne pas y enregistrer de clé réelle avant correction.
- Les URL des fournisseurs IA et les erreurs remontées par ces fournisseurs
  nécessitent une revue supplémentaire avant exposition.
- Redis n'est pas encore utilisé par l'application et aucune limitation des
  tentatives de connexion n'est en place.
- Les tests actuels ne constituent pas un audit complet des permissions,
  dépendances, sauvegardes, restauration, ni de l'isolation entre entreprises.

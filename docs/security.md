# Sécurité : état et prérequis

> L'application n'est pas encore prête pour une exposition publique. Redis
> est intégré techniquement ; son raccordement au déploiement reste à valider.
> La protection par adresse IP, la revue des destinations IA, la récupération
> des comptes et l'audit des dépendances restent notamment à traiter.

## Configuration du backend

| Variable | Utilisation |
|---|---|
| `APP_ENV` | `production` par défaut. Utiliser explicitement `development` pour un poste local. |
| `SECRET_KEY` | Secret JWT unique et aléatoire d'au moins 32 caractères ; aucune valeur par défaut. Le conserver stable et hors de Git. |
| `DATABASE_URL` | URL PostgreSQL en production ; SQLite est réservé au développement et aux tests. |
| `REDIS_URL` | Obligatoire en production : URL TCP `rediss://` authentifiée, avec vérification du certificat et du nom d'hôte. Ne jamais la partager. |
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
schéma.

### Migration des sessions à planifier séparément

La nouvelle révision `20261029_02` ajoute `users.session_nonce` sans supprimer
les utilisateurs. Les comptes déjà présents reçoivent une valeur aléatoire lors
de leur prochaine connexion réussie. Les anciens JWT sans cette valeur sont
refusés par la nouvelle version : chaque utilisateur doit se reconnecter.
La base Neon réelle, si elle est encore à `20261028_01`, **n'a pas été migrée
par les tests**. Ne pas lui appliquer cette révision avant d'avoir confirmé la
cible, la sauvegarde et l'étape de déploiement. Le nouveau backend refuse de
démarrer tant que la base n'est pas à la révision attendue.

Prévoir une bascule coordonnée : arrêter les anciennes instances backend,
appliquer la migration à la base confirmée puis démarrer uniquement la nouvelle
version. Une instance ancienne encore en fonctionnement peut continuer à
accepter des jetons révoqués, car elle ne vérifie pas `session_nonce`. Il ne
faut pas mélanger anciennes et nouvelles versions pour considérer la révocation
effective. Déployer aussi le nouveau frontend et faire recharger les
navigateurs : l'ancienne interface n'appelait pas la révocation serveur lors de
la déconnexion. Ne pas effectuer de `downgrade` en production sans plan :
revenir à l'ancien code peut réautoriser des jetons révoqués mais non expirés.

## Mots de passe et sessions

- Tout utilisateur connecté peut changer son mot de passe dans **Paramètres →
  Sécurité du compte** en fournissant l'ancien. Le nouveau doit être différent,
  avoir au moins 16 caractères et au plus 72 octets UTF-8, sans espaces aux
  extrémités. Le mot de passe reste haché par bcrypt. Une limite ne garantit
  pas à elle seule un mot de passe imprévisible : utilisez un gestionnaire.
- Un changement réussi déconnecte **toutes** les sessions de ce compte,
  y compris celle qui a fait la demande ; l'utilisateur se reconnecte avec son
  nouveau mot de passe. Le menu **Déconnexion partout** fait de même sans
  changer le mot de passe. Il n'y a pas de révocation par appareil ni de liste
  des appareils. Si l'appel de déconnexion échoue, le navigateur efface sa
  copie locale et indique que les autres sessions peuvent être encore actives.
- Un administrateur peut révoquer toutes les sessions d'un autre utilisateur
  de sa propre entreprise dans **Paramètres → Utilisateurs**. Une désactivation,
  une réactivation ou un changement de rôle invalide aussi les jetons précédents.
  Les autres comptes ne sont pas déconnectés.
- La version de session aléatoire est stockée en base et vérifiée avec le JWT
  à chaque requête authentifiée ; la mise à jour est atomique, y compris face
  aux connexions concurrentes. Un jeton révoqué est refusé aux vérifications
  suivantes, mais une requête déjà authentifiée peut encore se terminer.
- L'API limite séparément les changements de mot de passe par compte : cinq
  tentatives sur 15 minutes, réussies ou non, puis `429`. Redis indisponible
  bloque la modification en production (`503`), sans modifier le mot de passe.
  Voir [redis.md](redis.md). Une erreur de réseau après l'envoi peut laisser
  l'issue incertaine : la modification a pu être enregistrée malgré l'erreur.
- Les JWT expirent par défaut après sept jours (`ACCESS_TOKEN_EXPIRE_MINUTES`),
  sans renouvellement automatique. Ils restent stockés dans `localStorage` :
  une faille XSS peut les voler. La révocation ne remplace pas une protection
  XSS, une configuration HTTPS correcte ou un audit des permissions.
- Il n'existe pas encore de récupération de mot de passe oublié, ni de
  réinitialisation par un administrateur. Conserver les mots de passe dans un
  gestionnaire sûr et définir une procédure de récupération avant exposition.
  Les anciens mots de passe bcrypt de plus de 72 octets, autrefois tronqués
  silencieusement, ne sont désormais plus acceptés à la connexion.
- Restaurer une ancienne sauvegarde peut restaurer d'anciennes versions de
  session et réautoriser des JWT non expirés. Prévoir et tester une révocation
  globale après restauration ; aucune commande dédiée n'est encore fournie.
  Ne pas changer `SECRET_KEY` sans plan : les clés IA chiffrées en dépendent.

## Clés des fournisseurs IA

Les **nouvelles** clés IA sont chiffrées et authentifiées avant leur écriture
sur `ai_provider_configs.api_key_encrypted` (Fernet). Une clé propre à chaque
entreprise et fournisseur est dérivée de `SECRET_KEY` par HMAC-SHA256 avec un
contexte distinct de ceux du cache et des jetons. Le champ de réponse
`api_key_masked` affiche seulement `***`, sans fragment de clé. Le déchiffrement
n'a lieu que pour appeler
le fournisseur configuré ou vérifier l'état de la clé.

Ce chiffrement protège contre la lecture directe d'une sauvegarde ou d'une
base de données seule, pas contre une compromission du serveur qui possède
`SECRET_KEY`. Il n'ajoute aucune variable d'environnement. Conserver cette clé
stable et en lieu sûr : la perdre ou la remplacer rend les clés IA illisibles
et invalide les jetons. La restauration de clés chiffrées exige le même secret
et les mêmes identifiants d'entreprise et de fournisseur. Une procédure de
rotation/réchiffrement n'est pas encore fournie.

Les anciennes clés en clair, les données altérées et les clés chiffrées avec
un autre `SECRET_KEY` sont refusées, sans conversion automatique ni envoi au
fournisseur. L'interface signale qu'une clé doit être remplacée : un admin peut
supprimer et recréer le fournisseur, ou utiliser l'API pour remplacer sa clé.
Les anciennes clés en clair peuvent aussi subsister dans les sauvegardes et les
anciens messages ; les révoquer chez leur fournisseur et protéger les anciennes
copies. Le déploiement de cette modification ne convertit ni n'efface les
anciennes clés automatiquement.

Les tests et la récupération de modèles sont réservés aux admins. Un test d'un
fournisseur enregistré ne peut pas remplacer son URL ; changer l'URL d'un
fournisseur ayant une clé impose de remplacer ou supprimer cette clé au même
moment. Les URL OpenAI-compatibles exigent HTTPS en production et ne doivent
pas contenir d'identifiants, de paramètres ni de fragment. Les réponses
extérieures et exceptions ne sont plus reproduites dans les messages d'erreur.

**Limite importante :** ces mesures ne constituent pas une protection SSRF
complète. Les destinations réseau et les URL Ollama doivent encore être
revues ; ne pas enregistrer de clé IA réelle ni exposer le CRM avant cette revue.
Les fournisseurs IA externes peuvent être payants.

## Limitations connues

- Les destinations réseau et URL des fournisseurs IA nécessitent une revue
  supplémentaire avant exposition, y compris contre les attaques SSRF.
- La limitation Redis couvre les deux routes de connexion et les changements
  de mot de passe par identifiant, pas par IP. Elle peut être utilisée pour bloquer temporairement un compte et
  ne protège pas seule contre une attaque distribuée ou l'épuisement des quotas.
  Voir [redis.md](redis.md).
- Les tests actuels ne constituent pas un audit complet des permissions,
  dépendances, sauvegardes, restauration, ni de l'isolation entre entreprises.

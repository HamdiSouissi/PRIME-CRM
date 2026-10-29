# Déploiement et migrations

Ce dépôt ne configure pas les services hébergés à lui seul. Pour l'instance
personnelle, une première connexion frontend/backend a été confirmée ; elle ne
constitue pas un audit complet de sécurité ni un test de restauration. Vérifier
les réglages et les quotas directement chez les hébergeurs avant chaque mise en
production. Le CD GitHub n'est pas encore configuré par ce dépôt.

## Sécurité de l'instance

- Le backend a besoin de `APP_ENV=production`, d'une `SECRET_KEY` aléatoire et
  persistante, d'une URL PostgreSQL, d'une URL Redis TLS authentifiée et
  d'origines HTTPS explicites. Ne jamais commiter ou partager ces secrets.
- `ALLOW_PUBLIC_REGISTRATION=false` désactive l'inscription publique ; le
  premier administrateur se crée une seule fois avec le bootstrap privé. Ne
  pas laisser `FIRST_SUPERUSER_*` dans les services ou la CI après bootstrap.
- La visibilité privée Netlify Free est limitée au propriétaire de l'équipe.
  Elle protège l'accès au frontend, pas l'API Render, qui reste joignable sur
  Internet et doit donc conserver son authentification et ses protections.
- `AI_ALLOWED_ORIGINS` est vide par défaut : ne pas activer de fournisseur IA
  sans valider la destination, son coût et la défense de sortie réseau. Ne pas
  activer l'exception Ollama locale en production.
- Sur Render Free, le stockage local est éphémère : ne pas compter sur les
  fichiers uploadés pour une conservation durable. La veille et les quotas
  gratuits peuvent également affecter la disponibilité.

Le serveur web choisit un quota par IP (`LOGIN_LIMIT_SCOPE=ip`, défaut) ou un
quota partagé (`LOGIN_LIMIT_SCOPE=global`). Le mode IP de production exige
`CLIENT_IP_MODE` et, avec `trusted_proxy`, les CIDR vérifiés du pair et un
en-tête écrasé par le proxy. **Les CIDR fiables de Render ne sont pas établis** :
ne pas les deviner.

Le mode global, prévu comme compromis pour un usage personnel, ne dépend pas
de ces CIDR. Il n'offre pas de limite par IP : un seul visiteur peut bloquer
les nouvelles connexions pour tous. Les `CLIENT_IP_*` doivent être vides et
`PUBLIC_API_ORIGIN` doit indiquer l'origine HTTPS publique exacte du backend.
Cette origine sert aux redirections ; elle n'impose pas HTTPS elle-même. Il faut
vérifier séparément l'entrée publique et tout éventuel accès HTTP alternatif.
Conserver `--no-proxy-headers` dans la commande Uvicorn. Voir [security.md](security.md).

## Migrations et sauvegardes

Une sauvegarde dont le sommaire est lisible n'est pas une sauvegarde dont la
restauration a été testée. Tester toute restauration sur une base **isolée et
jetable**, jamais par accident sur la base active. Ne pas commiter les archives.

La révision `20261029_02` a été appliquée à l'instance personnelle initiale
après sauvegarde et autorisation. Ceci ne dit rien de l'état d'autres bases :
vérifier la cible et sa révision avant toute opération. Le serveur vérifie la
révision Alembic au démarrage et refuse un décalage ; il ne lance ni migration
ni bootstrap et ne crée pas les tables avec `create_all`. Cette vérification de
révision ne prouve pas que le schéma physique ou les données sont intacts.

Pour chaque future migration :

1. Identifier la base et vérifier la sauvegarde ainsi que la stratégie de
   restauration. Évaluer la compatibilité entre ancien code, nouveau code et
   schéma, y compris pendant le déploiement. Prévoir une maintenance si la
   migration n'est pas rétrocompatible.
2. Tester la migration sur une base PostgreSQL jetable. Obtenir une autorisation
   explicite avant toute écriture sur la base active ; ne pas supposer qu'un
   simple déploiement autorise une migration.
3. Appliquer la migration autorisée, puis vérifier la révision réellement
   présente en base avant de mettre à jour toute référence de déploiement.
4. Déployer le code testé et surveiller le service. Un retour arrière du code
   ne restaure pas la base et un `alembic downgrade` peut perdre des données.

Render Free ne propose pas de commande pre-deploy : les migrations ne doivent
pas être lancées automatiquement au démarrage du conteneur. Les révisions
futures nécessitent une procédure explicite et adaptée à leur compatibilité.

## Contrôle préparatoire des fichiers Alembic

`tools/migration_fingerprint.py` calcule une empreinte SHA-256 sur les objets
Git du répertoire `backend/alembic` et du fichier `backend/alembic.ini` d'un
commit complet. Exemples depuis la racine du dépôt :

```sh
python tools/migration_fingerprint.py print --commit <SHA_COMPLET>
python tools/migration_fingerprint.py verify --commit <SHA_COMPLET> --expected <EMPREINTE_ENREGISTREE>
```

`verify` retourne 0 si l'empreinte correspond, 1 si elle diffère, et 2 en cas
d'entrée invalide ou de lecture impossible. Les fichiers non commités ne sont
pas pris en compte. Le contrôle lit Git localement : aucun accès à Neon, Redis,
Render ou Netlify. La CI teste ce contrôle sur des dépôts Git jetables.

Cette empreinte détecte les changements de fichiers Alembic, **elle ne vérifie
pas la révision ou le schéma de la base** et ne prouve pas la compatibilité du
code. Elle ne protège pas non plus contre des écritures effectuées par du code
applicatif. Elle n'est pas encore reliée à un déploiement et ne constitue donc
pas un garde-fou de production à elle seule. Un job de répétition de la CI, sans
accès à un hébergeur, la compare après approbation à la variable GitHub
`PRODUCTION_ALEMBIC_FINGERPRINT` de l'environnement `production`. Il contrôle
ensuite localement le format du secret `RENDER_DEPLOY_HOOK_URL`, sans afficher
sa valeur. Il ne consulte pas la base de production et ne publie rien. Ce
contrôle de format ne vérifie pas l'authenticité du hook ni le service visé.

La référence doit être conservée séparément et ne doit être mise à jour
qu'après validation explicite et migration réellement vérifiée ; ne jamais la
changer simplement pour contourner un échec. Pour tout futur CD, maintenir
l'approbation des utilisateurs autorisés et arrêter le déploiement si la
référence est absente ou différente.

Le workflow [CI](../.github/workflows/ci.yml) teste les migrations sur une base
PostgreSQL et Redis sur des services jetables ; il construit les images sans les
publier. Il n'accède ni à Neon ni à un Redis hébergé et ne déploie rien. Voir
[ci.md](ci.md), [redis.md](redis.md) et [security.md](security.md).

# Déploiement : préparation en cours

**Ne pas exposer publiquement le projet pour l'instant.** Redis et les modes
IP/global sont intégrés, mais leur raccordement et HTTPS restent à valider sur
l'hébergeur réel. Une défense réseau complémentaire pour l'IA, la récupération
d'un compte perdu, les sauvegardes et l'audit des dépendances restent à traiter.
Le changement de mot de passe et la révocation globale des sessions sont
intégrés, mais pas encore déployés. Aucun CD Render ou frontend n'est configuré
à ce stade.

Le backend doit utiliser `APP_ENV=production`, une `SECRET_KEY` aléatoire et
persistante, une URL PostgreSQL, une URL Redis TLS authentifiée et des origines
HTTPS explicites. Les variables
sensibles doivent être définies dans le gestionnaire de secrets de l'hébergeur,
jamais dans Git. `AI_ALLOWED_ORIGINS` est vide par défaut : laisser l'IA sans
fournisseur tant que la destination, son coût et la défense de sortie réseau
n'ont pas été validés ; ne pas activer l'exception Ollama locale en production.
Voir [security.md](security.md).

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
La validation du trajet réel et la création d'un service auront lieu seulement
après autorisation ; ce document ne crée ni ne configure d'hébergement.

Avant de lancer le serveur, exécuter les migrations Alembic, puis le bootstrap
du premier administrateur lorsque la base est vide. La cible de la base doit
être vérifiée avant toute migration. La révision `20261029_02` est nouvelle :
Neon reste à `20261028_01` jusqu'à une migration explicitement confirmée. Lors
de la bascule, arrêter les anciennes versions du backend avant d'appliquer la
migration et démarrer les nouvelles : l'ancien code ne vérifie pas la révocation
des sessions. Le démarrage échoue si l'une des étapes échoue ; il ne crée pas
les tables avec `create_all`. Voir [security.md](security.md).

Le workflow [CI](../.github/workflows/ci.yml) teste les migrations sur une base
PostgreSQL et Redis sur des services jetables ; il construit les images sans les
publier. Il n'accède ni à Neon ni à un Redis hébergé et ne déploie rien. Voir
[ci.md](ci.md) et [redis.md](redis.md).

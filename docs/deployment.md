# Déploiement : préparation en cours

**Ne pas exposer publiquement le projet pour l'instant.** Redis et la
limitation IP sont intégrés, mais leur raccordement et la frontière du proxy
réel restent à valider. Une défense réseau complémentaire pour l'IA, la
récupération d'un compte perdu, les sauvegardes et l'audit des dépendances
restent à traiter. Le changement de mot de passe et la révocation globale des
sessions sont intégrés, mais pas encore déployés. Aucun CD Render ou frontend
n'est configuré à ce stade.

Le backend doit utiliser `APP_ENV=production`, une `SECRET_KEY` aléatoire et
persistante, une URL PostgreSQL, une URL Redis TLS authentifiée et des origines
HTTPS explicites. Les variables
sensibles doivent être définies dans le gestionnaire de secrets de l'hébergeur,
jamais dans Git. `AI_ALLOWED_ORIGINS` est vide par défaut : laisser l'IA sans
fournisseur tant que la destination, son coût et la défense de sortie réseau
n'ont pas été validés ; ne pas activer l'exception Ollama locale en production.
Voir [security.md](security.md).

Le serveur web de production exige aussi `CLIENT_IP_MODE`, et, en mode
`trusted_proxy`, `CLIENT_IP_PROXY_HEADER` et `CLIENT_IP_TRUSTED_PROXIES`. Ces
valeurs ne sont pas des secrets, mais ne doivent être choisies qu'après avoir
vérifié le pair TCP réel, l'en-tête écrasé par ce pair, l'isolation de l'origine
et l'obligation HTTPS sur tout le trajet public. **La topologie Render et ses
CIDR fiables ne sont pas encore établis** : aucune valeur ne doit être devinée
et le futur déploiement est bloqué tant que ces conditions ne sont pas prouvées.
Garder `--no-proxy-headers` dans la commande de démarrage. Si ces conditions ne
peuvent pas être vérifiées avec l'offre gratuite, étudier une autre architecture
ou reporter l'exposition, sans activer un mode non fiable pour contourner l'erreur.
La validation s'effectuera seulement après autorisation de l'étape concernée ;
ce document ne crée aucun service.

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

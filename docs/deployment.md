# Déploiement : préparation en cours

**Ne pas exposer publiquement le projet pour l'instant.** Redis est intégré
mais aucun service hébergé n'est configuré. La protection par IP, les clés IA,
la rotation des mots de passe, les sauvegardes et l'audit des dépendances
restent à traiter. Aucun CD Render ou frontend n'est configuré à ce stade.

Le backend doit utiliser `APP_ENV=production`, une `SECRET_KEY` aléatoire et
persistante, une URL PostgreSQL, une URL Redis TLS authentifiée et des origines
HTTPS explicites. Les variables
sensibles doivent être définies dans le gestionnaire de secrets de l'hébergeur,
jamais dans Git. Voir [security.md](security.md).

Avant de lancer le serveur, exécuter les migrations Alembic, puis le bootstrap
du premier administrateur lorsque la base est vide. La cible de la base doit
être vérifiée avant toute migration. Le démarrage échoue si l'une des étapes
échoue ; il ne crée pas les tables avec `create_all`.

Le workflow [CI](../.github/workflows/ci.yml) teste les migrations sur une base
PostgreSQL et Redis sur des services jetables ; il construit les images sans les
publier. Il n'accède ni à Neon ni à un Redis hébergé et ne déploie rien. Voir
[ci.md](ci.md) et [redis.md](redis.md).

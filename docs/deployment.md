# Déploiement : préparation en cours

**Ne pas exposer publiquement le projet pour l'instant.** Redis, la protection
contre les tentatives de connexion, les clés IA, la rotation des mots de passe
et l'audit des dépendances doivent encore être traités avant le premier
déploiement. Aucun CD Render ou frontend n'est configuré à ce stade.

Le backend doit utiliser `APP_ENV=production`, une `SECRET_KEY` aléatoire et
persistante, une URL PostgreSQL et des origines HTTPS explicites. Les variables
sensibles doivent être définies dans le gestionnaire de secrets de l'hébergeur,
jamais dans Git. Voir [security.md](security.md).

Avant de lancer le serveur, exécuter les migrations Alembic, puis le bootstrap
du premier administrateur lorsque la base est vide. La cible de la base doit
être vérifiée avant toute migration. Le démarrage échoue si l'une des étapes
échoue ; il ne crée pas les tables avec `create_all`.

Le workflow [CI](../.github/workflows/ci.yml) teste les migrations sur une base
PostgreSQL jetable et construit l'image backend sans la publier. Il n'accède pas
à Neon et ne déploie pas l'application. Voir [ci.md](ci.md).

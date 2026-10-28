# Redis : intégration technique, avant hébergement

L'application utilise Redis pour un cache limité et pour une première limitation
des connexions. Aucun compte ni service hébergé n'est créé par ce dépôt ou par
la CI. **Ne pas exposer le CRM publiquement avant les autres correctifs de
sécurité.**

## Configuration et disponibilité

- En production, `REDIS_URL` est obligatoire et doit être une URL TCP Redis
  `rediss://` **authentifiée**, sans paramètres de requête ni fragment et avec
  la base `/0` ou sans chemin. Le client vérifie le certificat **et le nom
  d'hôte**, avec des délais de connexion et d'opération de deux secondes.
- La valeur complète contient un secret : la fournir via le gestionnaire de
  secrets de l'hébergeur (par exemple **Render → service → Environment**),
  jamais dans Git, une conversation ou un journal. Ne pas utiliser les variables
  REST d'Upstash à la place de l'URL TCP.
- Le bootstrap vérifie la présence et le format de `REDIS_URL` en production
  mais n'y ouvre pas de connexion. Au démarrage de l'API, une petite écriture
  jetable vérifie l'authentification, la connectivité et la disponibilité en
  écriture. Si elle échoue, l'API ne démarre pas.
- Si Redis devient indisponible ensuite, les nouvelles connexions renvoient
  `503` plutôt que de contourner la limitation. Les utilisateurs déjà connectés
  peuvent encore utiliser le tableau de bord, qui reprend les données PostgreSQL.
  `/health` est une vérification de présence de l'API, **pas** une vérification
  continue de Redis ou de son quota.
- Sur le service hébergé, laisser **Eviction désactivé**. Redis contient aussi
  les compteurs de connexion : une suppression prématurée affaiblirait la
  limitation. L'application ne vérifie pas ce réglage au démarrage. Si le
  stockage est plein, les écritures peuvent être refusées et les nouvelles
  connexions bloquées jusqu'au rétablissement du service.
- En développement, `REDIS_URL` peut être absent pour travailler sans Redis ;
  le cache et la limitation sont alors désactivés. Le Compose de développement
  lance Redis par défaut et lui relie le backend. Le Compose de production
  attend une `REDIS_URL` externe sécurisée.

## Données stockées

- Le cache ne contient que les identifiants des étapes gagnées/perdues nécessaires
  aux statistiques du tableau de bord. Ses valeurs sont chiffrées et authentifiées
  côté application avec Fernet ; sa clé est dérivée de `SECRET_KEY` avec HMAC et
  un contexte distinct. Les noms des clés sont également pseudonymisés par HMAC.
  Aucun mot de passe, jeton, clé IA, nom de client ou activité n'est mis en cache.
- Chaque entrée appartient à une entreprise et expire après 30 secondes. Une
  modification d'étape déclenche une invalidation ; en cas de course ou d'échec
  d'invalidation, les statistiques peuvent rester périmées pendant environ
  30 secondes. PostgreSQL reste la source de vérité. Le cache n'est pas utilisé
  pour les autorisations ou les mutations commerciales.
- Les compteurs de connexion sont des nombres ; leurs clés utilisent un HMAC de
  l'identifiant normalisé, jamais l'email en clair. Ces données sont
  **pseudonymisées, pas anonymisées** : le fournisseur peut voir leur existence,
  leur fréquence et leur durée. Une rotation de `SECRET_KEY` invalide les
  jetons, rend les anciennes entrées de cache illisibles et change les clés des
  compteurs.

## Limitation des connexions

Les deux routes `/auth/login` et `/auth/login-json` partagent un compteur Redis
atomique par identifiant normalisé, commun aux processus de l'API. Les dix
premières tentatives dans une fenêtre de 15 minutes sont autorisées ; à partir
de la onzième, l'API répond `429` avec `Retry-After`. **Toutes** les tentatives
comptent, même réussies ; une connexion réussie ne remet pas le compteur à zéro.

Cette protection n'est pas une protection complète contre les attaques : un
attaquant peut épuiser le quota Redis, cibler de nombreux identifiants, ou
bloquer temporairement un compte connu. Aucune adresse IP ni en-tête
`X-Forwarded-For` n'est utilisé pour cette limitation : la confiance dans les
proxys et une protection par IP restent à définir avant exposition. Une fenêtre
fixe autorise aussi des rafales aux frontières de deux fenêtres.

## Offre gratuite envisagée

Au moment de la vérification, [Upstash Free](https://upstash.com/docs/redis/overall/billing)
annonce une base, 500 000 commandes par mois, 250 Mo et 10 Go de transfert,
sans carte bancaire. Une commande `EVAL` et les commandes exécutées par son
script comptent dans le quota. Un dépassement peut rendre les opérations Redis,
et donc les connexions au CRM, indisponibles ; il faut suivre le quota.

Le [TLS est toujours activé](https://upstash.com/docs/redis/howto/connect-client),
mais le [chiffrement du stockage au repos](https://upstash.com/docs/redis/features/security)
est une option payante, non comprise dans l'offre gratuite. Le chiffrement
applicatif ci-dessus réduit l'exposition du cache, sans masquer les métadonnées
ni les compteurs pseudonymisés. Ne pas ajouter de carte : Upstash indique que
cela convertit les ressources gratuites en offres payantes. Laisser également
[Auto Upgrade désactivé](https://upstash.com/docs/redis/features/auto-upgrade).
Les bases Free peuvent être [archivées après au moins 30 jours d'inactivité](https://upstash.com/docs/redis/help/faq) ;
vérifier leur disponibilité avant une connexion ou un déploiement ultérieur.
Vérifier les conditions avant toute création : tarifs et limites peuvent changer.

## Vérifier la connexion à la base Upstash dédiée

Le module `backend/app/verify_redis.py` permet de tester **sans déployer** une
base dédiée déjà créée. Il demande l'URL TCP Upstash authentifiée via une
saisie masquée ; elle ne doit être ni partagée, ni collée dans une commande,
ni enregistrée dans un fichier. Le module ne se connecte pas à PostgreSQL : il
utilise une configuration fictive isolée de la configuration réelle et de
`.env`.

Le test vérifie le certificat et le nom d'hôte TLS, l'authentification,
l'écriture, le cache chiffré et le script Lua de compteur. Il crée seulement
deux clés fictives dans un préfixe aléatoire, chacune avec une expiration de
30 ou 60 secondes, puis tente de les supprimer ; il ne lance jamais `FLUSHDB`
ni `SCAN`. Ce test ne vérifie pas la connexion HTTP, le frontend ou le cycle
de déploiement. Les erreurs sont volontairement résumées sans URL ni secrets.

Dans la console Upstash, ouvrez votre base, puis **Connect → TCP** et copiez
l'URL commençant par `rediss://`. Décochez **Read-Only Token** si cette option
est visible : le test doit pouvoir écrire ses clés temporaires. N'utilisez pas
l'URL REST en `https://`. Le test accepte uniquement un hôte `*.upstash.io`,
sans paramètres de requête ou fragment.
Depuis la racine du dépôt, avec les dépendances backend installées :

```powershell
Push-Location backend
try {
    & '..\.venv\neon-migration\Scripts\python.exe' -m app.verify_redis
    if ($LASTEXITCODE -ne 0) { throw 'Test Redis non validé.' }
} finally { Pop-Location }
```

Collez l'URL **uniquement à l'invite masquée**, puis validez avec Entrée. Le
résultat attendu se termine par `TEST_REDIS_OK`. Utilisez PowerShell dans un
vrai terminal et non une fenêtre de sortie : si la saisie masquée est
indisponible, le programme s'arrête avant la saisie. Videz ensuite le
presse-papiers si nécessaire. Ce bloc n'a pas été exécuté sur Windows dans cet
environnement.

## Tests automatisés

La CI démarre un Redis jetable dans le runner. Elle vérifie cache chiffré,
isolation entre entreprises, invalidation, expiration, limitation concurrente,
panne et vérification du nom d'hôte TLS avec un certificat local temporaire.
Elle ne contacte pas Upstash. Les tests n'effacent que leur propre préfixe
aléatoire et ne lancent jamais `FLUSHDB`.

Les tests locaux sans `CI_TEST_REDIS_URL` sautent les tests d'intégration Redis ;
la CI exige qu'ils s'exécutent. La variable de test n'accepte qu'une URL
`redis://127.0.0.1:<port>/0` sans mot de passe : ne jamais la diriger vers une
base contenant des données à conserver. Voir [ci.md](ci.md).

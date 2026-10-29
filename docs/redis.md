# Redis : intégration technique, avant hébergement

L'application utilise Redis pour un cache limité et pour une première limitation
des connexions et des changements de mot de passe. Aucun compte ni service hébergé n'est créé par ce dépôt ou par
la CI. **Ne pas exposer le CRM publiquement avant les autres correctifs de
sécurité.**

## Configuration et disponibilité

- En production, `REDIS_URL` est obligatoire et doit être une URL TCP Redis
  `rediss://` **authentifiée**, sans paramètres de requête ni fragment et avec
  la base `/0` ou sans chemin. Le client vérifie le certificat **et le nom
  d'hôte**, avec des délais de connexion et d'opération de deux secondes.
  Pour toute connexion Redis TLS, il utilise uniquement le bundle de CA publiques
  `certifi` épinglé dans `backend/requirements.txt`, plutôt que le magasin CA
  de l'OS ; il ne fait aucun repli vers ce magasin. Cette règle ne change pas
  la confiance TLS de PostgreSQL ou des autres clients. Une CA privée n'est pas
  prise en charge pour Redis par cette configuration ; mettre à jour et tester
  régulièrement la version de `certifi` avant que son bundle ne vieillisse.
- La valeur complète contient un secret : la fournir via le gestionnaire de
  secrets de l'hébergeur (par exemple **Render → service → Environment**),
  jamais dans Git, une conversation ou un journal. Ne pas utiliser les variables
  REST d'Upstash à la place de l'URL TCP.
- Le bootstrap vérifie la présence et le format de `REDIS_URL` en production
  mais n'y ouvre pas de connexion. Au démarrage de l'API, une petite écriture
  jetable vérifie l'authentification, la connectivité et la disponibilité en
  écriture. Si elle échoue, l'API ne démarre pas.
- Si Redis devient indisponible ensuite, les nouvelles connexions et les
  changements de mot de passe renvoient `503` plutôt que de contourner la
  limitation. Les utilisateurs déjà connectés peuvent encore utiliser le
  tableau de bord, qui reprend les données PostgreSQL ; la déconnexion globale
  utilise PostgreSQL et ne dépend pas de Redis.
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
- Les compteurs de connexion et de changement de mot de passe sont des nombres ;
  leurs clés utilisent un HMAC de l'identifiant normalisé, de l'adresse IP
  canonique ou de la constante du compteur global, jamais l'email ou l'IP en
  clair. Ces données sont **pseudonymisées,
  pas anonymisées** : le fournisseur peut voir leur existence, leur fréquence
  et leur durée. L'hébergeur ou les proxys peuvent journaliser des IP en dehors
  de Redis. Une rotation de `SECRET_KEY` invalide les jetons, rend les anciennes
  entrées de cache illisibles et change les clés des compteurs.

## Limitation des connexions et changements de mot de passe

Les routes `/auth/login` et `/auth/login-json` partagent deux compteurs Redis
atomiques entre tous les processus :

1. **Quota avant validation** : 30 requêtes par 15 minutes pour les deux
   routes ; la 31e reçoit `429` et `Retry-After`. Les corps invalides et les
   connexions réussies comptent. Avec `LOGIN_LIMIT_SCOPE=ip` (défaut), le quota
   est par IP vérifiée. Avec `LOGIN_LIMIT_SCOPE=global`, il est **partagé entre
   tous les visiteurs**, sans dépendre d'une IP ni d'un en-tête ; ce n'est pas
   une limitation par IP. Une personne peut bloquer toutes les nouvelles
   connexions pendant la fenêtre et prolonger le blocage en recommençant.
2. **Identifiant normalisé** : 10 tentatives par 15 minutes après validation ;
   la 11e reçoit `429` avec `Retry-After`. Réussir une connexion ne remet pas
   le compteur à zéro. Cette limite est indépendante du quota précédent.

En mode IP, `X-Forwarded-For` n'identifie jamais le client ; une frontière
proxy invalide renvoie `503`. Le mode global exige une origine HTTPS publique
configurée et une entrée HTTPS imposée, sans s'appuyer sur un CIDR : voir
[security.md](security.md). La même clé Redis globale est partagée par les
processus et déploiements qui ont les mêmes `SECRET_KEY` et préfixe Redis.

`/auth/change-password` a un compteur **séparé** par compte, limité à cinq
changements demandés par 15 minutes ; la sixième tentative reçoit `429`. Toutes
les tentatives comptent, même réussies. Ce compteur n'épuise pas celui utilisé
pour se reconnecter. Aucun mot de passe n'est envoyé à Redis. Sans `REDIS_URL`
en développement/test, le cache et **toutes ces limites**, y compris le
préfiltre local, sont désactivés ; ne pas exposer cette configuration.

Avant Redis, chaque processus autorise au maximum **60 requêtes par 60
secondes au total** à atteindre le premier compteur. Les refus Redis sont gardés
dans un cache négatif local limité à 4 096 clés HMAC ; en mode global une seule
clé représente le quota partagé. Tant qu'un refus reste en cache, il ne sollicite
plus Redis. Les requêtes bloquées par le préfiltre reçoivent `429` et
`Retry-After`. `/health`, les prévols `OPTIONS` et les sessions déjà émises ne
sont pas bloqués par ce compteur. Ce budget et ce cache sont **par processus**,
réinitialisés au redémarrage et non coordonnés entre instances : un attaquant
peut encore épuiser le quota ou bloquer les utilisateurs légitimes.

Le script atomique coûte `EVAL` + `INCR` + `TTL`, soit **trois commandes
Upstash**, et une commande `EXPIRE` supplémentaire lors de la première création.
Une tentative au corps valide mobilise les compteurs initial et identifiant,
soit habituellement six commandes au total, jusqu'à huit si les deux clés sont
créées ; un corps invalide mobilise seulement le premier compteur, soit trois
ou quatre. Ces chiffres n'incluent pas les autres usages Redis. Les fenêtres
sont fixes et peuvent laisser passer des rafales à leur frontière.

Aucun de ces mécanismes ne constitue une défense DDoS ou une garantie de
protection du quota Upstash ; surveiller la disponibilité et l'usage réels.

## Offre gratuite envisagée

Au moment de la vérification, [Upstash Free](https://upstash.com/docs/redis/overall/billing)
annonce une base, 500 000 commandes par mois, 250 Mo et 10 Go de transfert,
sans carte bancaire. Une commande `EVAL` et les commandes exécutées par son
script comptent dans le quota. Un dépassement peut rendre les opérations Redis,
et donc les connexions et changements de mot de passe, indisponibles ; il faut suivre le quota.

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

### Diagnostiquer une erreur TLS sans accès aux données

En cas d'échec du certificat, lancer `python -m app.verify_redis --tls-diagnostic`
depuis `backend` avec l'environnement Python du projet. À l'invite masquée,
entrer uniquement l'**Endpoint** Upstash, sans URL ni token, et ajouter `:port`
si le port affiché diffère de `6379`. Le mode effectue uniquement une
négociation TLS avec vérification du certificat et du nom d'hôte. Ce mode
utilise volontairement les CA système pour le diagnostic ; il n'utilise pas le
bundle `certifi` du client Redis et son résultat peut donc différer du test
applicatif. Il n'envoie **ni authentification, ni commande Redis**, n'accède
pas à PostgreSQL et ne modifie aucune clé.

La sortie indique le nombre de certificats CA chargés, la présence éventuelle
des variables `SSL_CERT_FILE` et `SSL_CERT_DIR` (sans leurs valeurs), l'heure
UTC et un code de vérification TLS. Aucun nom d'hôte, chemin, jeton, message
brut d'exception ou détail de certificat n'est affiché. L'horloge, le magasin de
confiance, une chaîne incomplète, une interception réseau ou un nom d'hôte
incorrect peuvent expliquer un échec ; le code aide à distinguer ces cas sans
justifier la désactivation de TLS. Le mode diagnostic désactive aussi, dans son
propre processus seulement, l'écriture éventuelle de secrets TLS par
`SSLKEYLOGFILE`.

Si le code indique un certificat expiré, un diagnostic plus détaillé est
possible avec `python -m app.verify_redis --tls-certificate-details`. Il demande
lui aussi uniquement l'Endpoint masqué. Il effectue deux négociations TLS
**vérifiées** : l'une avec les certificats système, l'autre avec le bundle
`certifi` seul s'il est disponible dans l'environnement Python. Cette
comparaison ne modifie pas la configuration de l'application ; deux connexions
successives peuvent également rencontrer des chemins réseau différents.

Le diagnostic tente de relever uniquement les dates d'expiration des
certificats présentés pendant la première négociation. Ces dates sont
**non authentifiées si la validation échoue** : elles ne prouvent pas l'identité
du serveur ni le certificat effectivement retenu par OpenSSL. Les noms,
certificats complets, chemins et exceptions ne sont pas affichés. Sur certaines
versions de Python, les dates peuvent être indisponibles. Aucun token, aucune
commande Redis ni donnée CRM ne sont envoyés.

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

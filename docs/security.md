# Sécurité : état et prérequis

> L'application n'est pas encore prête pour une exposition publique. Redis,
> les modes de limitation des connexions et HTTPS doivent encore être validés
> sur l'hébergement réel. La défense réseau complémentaire pour l'IA, la
> récupération des comptes, les sauvegardes et l'audit des dépendances restent
> à traiter.

## Configuration du backend

| Variable | Utilisation |
|---|---|
| `APP_ENV` | `production` par défaut. Utiliser explicitement `development` pour un poste local. |
| `SECRET_KEY` | Secret JWT unique et aléatoire d'au moins 32 caractères ; aucune valeur par défaut. Le conserver stable et hors de Git. |
| `DATABASE_URL` | URL PostgreSQL en production ; SQLite est réservé au développement et aux tests. |
| `REDIS_URL` | Obligatoire en production : URL TCP `rediss://` authentifiée, avec vérification du certificat et du nom d'hôte. Ne jamais la partager. |
| `CORS_ORIGINS` | Origines exactes séparées par des virgules ; vide signifie aucune origine cross-origin. En production, seules les origines HTTPS sont acceptées, sans `*` ni chemin. |
| `ALLOW_PUBLIC_REGISTRATION` | `false` par défaut. La valeur `true` est refusée en production. |
| `LOGIN_LIMIT_SCOPE` | `ip` par défaut ou `global` explicitement. Global partage un seul quota de connexion entre tous les visiteurs et ne limite pas par IP. |
| `CLIENT_IP_MODE` | En mode `ip` de production : `direct` ou `trusted_proxy` selon un trajet réseau vérifié. Doit être vide en mode `global`. |
| `CLIENT_IP_PROXY_HEADER` | En mode IP avec proxy seulement : `cf-connecting-ip` ou `x-real-ip`, selon l'en-tête réécrit et garanti par le proxy immédiat. |
| `CLIENT_IP_TRUSTED_PROXIES` | En mode IP avec proxy seulement : IP/CIDR stricts du pair TCP immédiat, séparés par des virgules ; aucune valeur par défaut et aucun `/0`. |
| `PUBLIC_API_ORIGIN` | Obligatoire pour le mode `global` de production : origine HTTPS publique exacte de l'API, sans chemin ni identifiants. Utilisée pour les redirections, sans vérifier elle-même le transport. Vide en mode IP. |
| `AI_ALLOWED_ORIGINS` | Liste facultative d'origines IA HTTPS exactes, séparées par des virgules, sans chemin ni secret ; vide par défaut et recommandé si l'IA n'est pas utilisée. |
| `AI_ALLOW_LOCAL_OLLAMA` | `false` par défaut ; `true` autorisé uniquement pour Ollama HTTP sur une machine de développement isolée, jamais en production. |
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

## Connexions : modes IP et global

Les deux routes de connexion ont, avant l'analyse du corps, une limite Redis
atomique de **30 requêtes en 15 minutes**, en plus de **10 tentatives par
identifiant**. Les corps invalides et les connexions réussies comptent. La
31e requête reçoit `429` et `Retry-After`. Une limite locale par processus
réduit une partie des appels Redis ; elle ne remplace ni une protection réseau
ni le suivi du quota. Voir [redis.md](redis.md).

`LOGIN_LIMIT_SCOPE` choisit explicitement la portée du premier compteur :

- **`ip` (défaut)** : le quota de 30 est séparé pour chaque adresse client
  vérifiée. La configuration de production doit correspondre au trajet réel :
  - `CLIENT_IP_MODE=direct` ignore les en-têtes et utilise le pair TCP public
    reçu par Uvicorn ; les pairs non publics sont refusés en production. Une
    adresse publique ne prouve pas qu'il s'agit du navigateur et non d'un proxy.
  - `CLIENT_IP_MODE=trusted_proxy` n'accepte que les pairs TCP des CIDR
    explicitement configurés, puis lit exactement l'en-tête choisi
    `cf-connecting-ip` ou `x-real-ip`. Il faut que le proxy écrase cet en-tête
    et qu'aucun autre émetteur ne puisse se faire passer pour lui. Une adresse
    manquante, double, invalide ou non publique renvoie `503`. IPv4-mappée est
    normalisée ; `X-Forwarded-For` est ignoré.
- **`global` (opt-in)** : les 30 requêtes sont **partagées par tous**, quels
  que soient leurs comptes, IP ou en-têtes ; la limite par compte reste active.
  Il ne s'agit **pas** d'une limite par IP. Un seul attaquant peut bloquer
  toutes les nouvelles connexions pendant la fenêtre, et prolonger le blocage
  en recommençant. Les sessions déjà émises restent utilisables. Aucun CIDR
  ou en-tête d'IP n'est utilisé : les trois variables `CLIENT_IP_*` doivent
  être vides. Si Redis est indisponible, les nouvelles connexions renvoient
  `503`. Ce choix est un compromis de disponibilité, pas une défense DDoS.

Dans les deux cas, conservez **`--no-proxy-headers`** au lancement d'Uvicorn.
En mode IP, le pair doit rester intact pour la vérification ; le contrôle du
port zéro ne détecte pas toutes les réécritures. En mode global de production,
`PUBLIC_API_ORIGIN` doit contenir l'origine HTTPS publique exacte de l'API,
par exemple un nom de service `onrender.com`, sans chemin ni identifiants.
Les redirections utilisent cette origine configurée, et non `Host`,
`X-Forwarded-Host` ou `X-Forwarded-Proto` fournis par la requête. Un nom de
domaine personnalisé exige donc de mettre à jour cette valeur. La validation
contrôle la syntaxe ; elle ne prouve ni la propriété du domaine, ni le DNS, ni
le certificat, ni que toutes les requêtes ont bien utilisé TLS.

**Dans tous les modes, l'opérateur doit imposer HTTPS sur chaque entrée
publique et empêcher un accès HTTP alternatif à l'application.** En mode
proxy IP, l'API rétablit le schéma HTTPS seulement pour le pair approuvé ; en
mode global elle utilise l'origine configurée sans authentifier le pair. Le
client doit appeler directement l'URL HTTPS : une redirection depuis HTTP ne
protège pas les données déjà envoyées en clair lors de la première requête.

Render documente la redirection HTTP vers HTTPS de son entrée publique et
indique que les web services Free ne reçoivent pas de trafic privé. Ces
indications ne remplacent pas un test de bout en bout ni la vérification de
la configuration réelle. La liste des CIDR du pair immédiat n'est pas établie :
ne pas la deviner pour le mode IP et ne pas utiliser `0.0.0.0/0` ou `::/0`.
Le mode global évite d'utiliser ces CIDR pour le compteur, mais ne résout pas
les autres prérequis de sécurité et de disponibilité.

Le Nginx frontend fourni écrase `X-Real-IP` avec son propre `$remote_addr` et
supprime `CF-Connecting-IP` pour `/api/`. Derrière un autre proxy,
`$remote_addr` peut désigner cet intermédiaire, pas l'utilisateur ; la chaîne
reste à vérifier si le mode IP est utilisé.

Pour limiter l'énumération, les réponses d'authentification ne publient plus
`X-Process-Time` et une vérification bcrypt factice est exécutée pour un compte
inexistant ou inactif. C'est une atténuation, **pas une garantie de temps
constant** : les différences de base de données, de hash, de réseau ou de
charge peuvent rester mesurables.

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
moment. Les réponses extérieures et exceptions ne sont pas reproduites dans
les messages d'erreur. Les fournisseurs externes peuvent être payants : laissez
l'IA désactivée si leur gratuité et leurs quotas ne sont pas établis.

## Destinations IA et réduction du risque SSRF

**Aucune destination n'est autorisée par défaut.** Le CRM fonctionne sans IA.
Avant d'utiliser un fournisseur distant, l'opérateur doit approuver son
origine HTTPS exacte dans l'environnement **du backend**, pas dans le frontend.
Par exemple, avec des noms fictifs :

```dotenv
AI_ALLOWED_ORIGINS=https://provider.example.invalid,https://second.example.invalid:8443
AI_ALLOW_LOCAL_OLLAMA=false
```

Ces valeurs d'exemple ne désignent aucun fournisseur réel. Une origine contient
seulement protocole, nom DNS et port éventuel : pas de chemin, joker, adresse IP,
identifiant, requête ou fragment. Le chemin `/v1` se configure dans l'URL du
fournisseur dans le CRM, pas dans l'allowlist. L'origine et le port doivent
correspondre exactement ; `https://provider.example.invalid` et
`https://provider.example.invalid:8443` sont différents. Sur Render, la variable non secrète sera définie dans **service →
Environment → Add Environment Variable** au moment du déploiement. Une valeur
invalide empêche le démarrage. Ne jamais y placer de clé, mot de passe ou URL
avec identifiants, et ne pas enregistrer de secret dans Git ou `VITE_*`. Une
variable d'environnement explicitement vide prime sur une ancienne valeur
`.env` ; les variables booléennes, elles, doivent contenir `true` ou `false`.

Pour chaque appel IA (test, modèles et génération), le backend revalide l'URL
et l'allowlist, résout les enregistrements DNS **A** et rejette toute réponse
contenant une adresse non publique, privée, de boucle locale, lien-local,
multicast, réservée ou spéciale. Il se connecte directement à une IPv4
validée et conserve le nom d'origine pour `Host`, SNI et la vérification TLS,
avec les CA `certifi`. Il n'utilise ni proxy d'environnement, ni redirection,
ni CA fournie par l'environnement. Les corps d'erreur sont ignorés ; une
réponse réussie est limitée à 2 Mio, sans compression, avec un délai maximal
pour la requête. Un fournisseur IPv6-only ou sans réponse A publique n'est pas
pris en charge. Une adresse publique choisie parmi plusieurs est utilisée,
sans nouvel essai sur les autres. Certains fournisseurs utilisant des
redirections, compression, proxy obligatoire ou réponses plus grandes ne seront
pas compatibles. Les adresses vérifiées ne prouvent pas la fiabilité
commerciale d'un fournisseur. Les prompts et données associées lui sont
transmis : ne pas y inclure de secrets et vérifier ses conditions de traitement.

La seule exception HTTP concerne `localhost`, `127.0.0.1` et
`host.docker.internal`, port `11434`, pour Ollama **uniquement si**
`APP_ENV=development` et `AI_ALLOW_LOCAL_OLLAMA=true`. Elle doit être limitée
à un poste de développement isolé ; les prompts y transitent sans TLS et un
Ollama mal exposé peut être appelé par d'autres machines. Elle est interdite
en production, où `true` bloque le démarrage. Voir [ollama.md](ollama.md).

Les fournisseurs enregistrés avec une ancienne URL non conforme, ou dont
l'origine a été retirée de l'allowlist, ne peuvent plus être testés ni utilisés.
Un administrateur peut les désactiver, les supprimer ou corriger leur URL ;
un changement d'URL exige aussi de remplacer ou supprimer la clé associée.
Aucune destination n'est activée automatiquement et aucun fournisseur réel
n'est contacté pendant les tests. Les tests locaux incluent un vrai serveur
TLS sur boucle locale avec CA éphémère pour vérifier IP, SNI, `Host` et
certificat, ainsi que le refus des redirections et des réponses DNS mixtes.

**Défense en profondeur nécessaire :** ce filtrage applicatif réduit le risque
SSRF mais ne remplace pas un pare-feu/une politique de sortie réseau bloquant
les réseaux internes et métadonnées, ni un audit de l'infrastructure. Une IP
publique peut correspondre à une route interne particulière ; un DNS ou un
fournisseur autorisé peut être compromis. Un administrateur de l'environnement
qui ajoute une origine autorise les envois vers celle-ci. Ne pas exposer le CRM
avant traitement des autres limitations de sécurité et de sauvegarde.

## Limitations connues

- Prévoir et tester une défense de sortie réseau indépendante du code pour
  les adresses internes, les métadonnées et les routes particulières.
- La limitation Redis couvre les connexions par IP ou globalement et par
  identifiant, ainsi que les changements de mot de passe par identifiant. Elle
  peut bloquer une IP partagée, un compte connu ou tous les utilisateurs en mode
  global. Elle ne protège pas seule contre une attaque distribuée ou l'épuisement
  des quotas. La chaîne HTTPS de l'hébergeur reste à vérifier ; le mode IP exige
  en outre une frontière proxy vérifiée. Voir [redis.md](redis.md).
- Les tests actuels ne constituent pas un audit complet des permissions,
  dépendances, sauvegardes, restauration, ni de l'isolation entre entreprises.

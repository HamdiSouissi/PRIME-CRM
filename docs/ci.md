# Intégration continue

Le workflow [CI](../.github/workflows/ci.yml) s'exécute sur les `push`, les
`pull_request` et, une fois présent sur la branche par défaut, sur lancement
manuel (`workflow_dispatch`). Il utilise uniquement la permission GitHub
`contents: read`. Les jobs backend et frontend n'utilisent aucun secret GitHub,
aucune URL Neon et aucune clé Redis hébergée. Les identifiants PostgreSQL
visibles dans le workflow ne servent qu'au conteneur jetable du job.

Pour un `push` du dépôt `HamdiSouissi/PRIME-CRM` sur la branche
`arena/a18b007f-prime-crm`, un troisième job peut **demander un déploiement
Render** après la réussite des deux jobs et l'approbation de l'environnement
GitHub `production`. Il compare l'empreinte Alembic à la variable
`PRODUCTION_ALEMBIC_FINGERPRINT`, valide le format du secret
`RENDER_DEPLOY_HOOK_URL`, vérifie que le commit est toujours en tête de branche,
puis envoie une seule requête au hook en précisant le SHA testé. Il ne lance
pas de migration et n'a aucun identifiant de base ou de Redis. Une variable
manquante ou une empreinte différente bloque la requête.

Le succès de ce job signifie **demande acceptée ou mise en file**, pas que
l'application est en ligne : vérifier le commit et l'état `Live` dans Render.
Le job n'enregistre donc pas un faux statut de déploiement GitHub. En cas de
réponse incertaine, vérifier Render avant de réessayer. L'empreinte ne vérifie
pas le schéma réel de Neon ; voir [deployment.md](deployment.md).

Pour tester un commit sans même demander de publication backend, ajouter
`[skip render]` au message du dernier commit du push. Les tests s'exécutent
normalement, mais le job Render est ignoré. Un push ultérieur sans ce marqueur
peut inclure toutes les modifications cumulées ; l'approbation et les autres
contrôles restent nécessaires. Ne pas confondre ce marqueur avec `[skip ci]`,
qui ferait ignorer les tests par GitHub.

Pour ce dépôt public, les runners GitHub standards utilisés par le workflow sont
gratuits selon les conditions GitHub. Aucun service payant n'est créé.

## Contrôles

- **Backend, Python 3.11** : installation des dépendances, `pip check`, Ruff,
  tests pytest sur SQLite en mémoire et compilation des fichiers Python.
- **Destinations IA** : allowlist, DNS fictif, adresses privées/mixtes,
  rebinding, redirections, limites, anciens fournisseurs et masquage des
  erreurs. Un serveur TLS réel sur boucle locale avec CA éphémère vérifie l'IP
  choisie, `Host`, SNI, la confiance et le nom du certificat. Aucun fournisseur
  IA réel ni secret réel n'est utilisé.
- **Redis et connexions** : un conteneur Redis 7.2 jetable teste le cache
  chiffré, l'isolation des entreprises, l'invalidation et les compteurs IP,
  global et identifiant, y compris sous concurrence. Les tests en mémoire
  vérifient les deux modes, les redirections HTTPS, la validation avant parsing,
  les proxys et les en-têtes falsifiés, le budget
  local, le cache négatif, les pannes et la réponse anti-énumération ; ils ne
  prouvent pas la configuration de l'hébergeur. La vérification TLS utilise un
  serveur local éphémère. Les tests Redis utilisent un préfixe aléatoire et ne
  lancent jamais `FLUSHDB` ; aucun Redis hébergé n'est contacté.
- **Migrations** : PostgreSQL 16 est créé pour le job, puis détruit. Le workflow
  teste la migration d'un compte fictif depuis `20261028_01` vers la nouvelle
  révision, la répétition d'`upgrade`, `alembic check`, `downgrade base`, un
  nouvel `upgrade` et un dernier `check`. Le `downgrade` est destructif : **ne
  jamais l'exécuter sur Neon ou sur une base contenant des données à conserver**.
  La CI teste ensuite le chiffrement IA, les courses entre connexion et
  révocation des sessions sur plusieurs connexions PostgreSQL, leur interaction
  avec Redis, puis le bootstrap privé. Les lignes IA sont annulées ; les tests de concurrence
  valident réellement leurs transactions et suppriment seulement leurs comptes
  fictifs. Les séquences peuvent avancer : la base doit rester jetable.
- **Images Docker** : `docker compose config --quiet` valide les deux fichiers
  Compose avec des valeurs fictives. Chaque job construit ensuite son image,
  sans la publier ; un conteneur frontend jetable vérifie la configuration Nginx
  sans exposer de port. Les fichiers `.dockerignore` excluent notamment les
  fichiers `.env`, les données et les dépendances locales des contextes de
  construction.
- **Frontend, Node 24** : `npm ci` depuis le lockfile, ESLint, tests Vitest,
  vérification TypeScript et build Vite, puis vérification des règles statiques
  `_redirects` et `_headers`. Node 20 est en fin de vie depuis le 30 avril 2026 ;
  Node 24 est utilisé pour la CI et le Dockerfile frontend. La CI ne publie pas
  son build sur Netlify.

Sur un push de la branche de travail du dépôt indiqué, la variable GitHub de
**dépôt** `VITE_API_URL` doit être exactement
`https://prime-crm-cqi3.onrender.com`. Le workflow vérifie cette adresse avant
le build et vérifie sa présence dans les fichiers JavaScript générés : une
variable absente ou différente fait échouer le job. Cette valeur est publique :
Vite l'intègre au code envoyé aux navigateurs. Ne jamais placer de secret dans
une variable `VITE_*`. Pour changer de backend, revoir et modifier ensemble la
variable et la valeur autorisée par le workflow.

Pour ces pushs, un `build-info.json` indiquant le SHA de l'exécution est aussi
créé dans le build de test. Le build reste sur le runner temporaire : il n'est
ni conservé comme artefact GitHub ni publié sur Netlify. Le dépôt GitHub est
public ; ne jamais y commiter de secret ni de données du CRM. Le site Netlify
existant conserve sa visibilité privée.

### Répétition frontend, sans publication

Si le message du dernier commit contient `[frontend preview]`, le job
`Frontend · répétition protégée sans publication` attend la réussite des deux
jobs de CI et l'approbation de l'environnement `production-frontend`. Dans cet
environnement, la variable `PRODUCTION_ALEMBIC_FINGERPRINT` doit correspondre
à l'empreinte enregistrée après la dernière migration autorisée. Ce contrôle
porte uniquement sur les fichiers Git ; il ne vérifie pas l'état réel de Neon.

Après approbation, le job vérifie l'empreinte, le SHA et le HEAD de la branche,
reconstruit le même commit dans le stage Docker `verified-static` avec l'URL
publique attendue, puis vérifie l'archive ZIP avec
`tools/frontend_release.py`. Le build est refait après la première CI, et non
copié depuis elle : le commit est identique, mais les octets ne sont pas
nécessairement identiques si une image de base ou une dépendance change. Le
fichier `build-info.json` indique le SHA déclaré, sans prouver à lui seul
l'intégrité des autres fichiers.

Ce job n'utilise aucun jeton Netlify, n'envoie aucune requête à Netlify et ne
crée aucun artefact GitHub. L'archive reste sur le runner temporaire. Pour
répéter ce test sans demander de déploiement backend, inclure aussi
`[skip render]` dans le message du dernier commit. Il ne s'agit pas d'une
publication frontend : le workflow ne déploie pas encore le frontend.

### Vérification Netlify en lecture seule

Si le message du dernier commit contient `[netlify preflight]`, après les deux
jobs de CI et l'approbation de `production-frontend`, le job
`Netlify · vérification en lecture seule sans publication` vérifie le commit,
le HEAD de la branche et l'empreinte Alembic, puis utilise le secret
d'environnement `NETLIFY_AUTH_TOKEN` pour lire le projet Netlify prédéfini.
Il vérifie l'identifiant et le nom du projet, que les builds Git sont arrêtés,
et refuse si les publications non-Git ou le déploiement publié sont explicitement
bloqués. Il sonde ensuite `/login` sans jeton pour confirmer la redirection
Netlify de protection privée correspondant au projet. Il n'envoie que des GET,
n'active pas les builds et ne crée ni déploiement ni artefact. Cette sonde
ponctuelle ne garantit pas que la visibilité restera privée par la suite.

Le jeton personnel Netlify peut donner des droits sur toutes les ressources
accessibles à son compte ; il doit être enregistré **uniquement** comme secret
GitHub de l'environnement `production-frontend`, jamais dans le dépôt ou les
logs. Les réviseurs doivent contrôler le workflow et le commit avant chaque
approbation ; un administrateur du dépôt peut modifier les règles de protection.
Prévoir l'expiration et la rotation du jeton. Le contrôle masque les réponses et
les détails d'erreur, désactive les proxys hérités et refuse les redirections de
l'API ; il ne prouve pas que le site fonctionnera après un futur déploiement.
Inclure aussi `[skip render]` pour éviter toute demande Render lors de ce test.

Pour diagnostiquer une réponse privée inattendue depuis le runner GitHub, un
commit `[netlify diagnose] [skip render]` lance un job distinct **sans secret** :
un seul GET anonyme de `/login`, sans suivre la redirection. Il affiche
seulement le code HTTP et des indicateurs de correspondance ; ni URL de
redirection, ni en-têtes, ni corps de réponse ne sont journalisés. Le succès du
job indique que le diagnostic est terminé, pas que la confidentialité est
validée. Ce job ne modifie rien et ne remplace pas le contrôle protégé.

Les tests frontend couvrent l'authentification, la modification du mot de
passe, la déconnexion, la révocation par l'admin et l'interface IA avec API
simulée ; ils ne sont pas des tests de bout en bout. La plupart des tests
fonctionnels backend utilisent SQLite ; PostgreSQL est aussi vérifié pour les
migrations, les clés IA, les courses de session et le bootstrap privé. Les
tests historiques activent l'inscription uniquement dans
leur processus de test isolé ; elle est interdite en production. Les tests Redis
utilisent un service jetable et non le futur fournisseur hébergé. La CI ne
remplace pas une revue de sécurité ni un audit des dépendances avant exposition
publique.

Ruff applique les règles de correction `E9` et `F`, mais ignore pour l'instant
les imports et variables inutilisés (`F401`, `F841`) ; l'import `*` d'Alembic
est toléré. ESLint utilise les règles recommandées et la règle des hooks React,
mais n'applique pas encore `no-unused-vars`, `no-undef`, `exhaustive-deps` et
accepte les `catch` vides existants. La compilation TypeScript vérifie aussi
le code, avec la configuration actuelle du projet. Ces exceptions sont une
base de départ, pas un audit complet. Les actions GitHub sont épinglées par
SHA ; elles devront être mises à jour et vérifiées périodiquement. Certaines
dépendances Python existantes ne sont pas figées exactement.

## Exécution locale sous Windows PowerShell

À la racine du dépôt, avec Python 3.11 dans `.venv\neon-migration` et Node 24
installé, après avoir synchronisé la branche :

```powershell
Set-Location "D:\Prime vision solution\projects\PRIME-CRM"

# PowerShell 5.1 ne transforme pas les codes d'erreur natifs en exceptions.
function Assert-CiExit {
    if ($LASTEXITCODE -ne 0) { throw "La commande précédente a échoué (code $LASTEXITCODE)." }
}

git status --short --branch
Assert-CiExit
git fetch origin
Assert-CiExit
git switch arena/a18b007f-prime-crm
Assert-CiExit
git pull --ff-only origin arena/a18b007f-prime-crm
Assert-CiExit

# Installer le linter en plus des dépendances backend existantes.
& .\.venv\neon-migration\Scripts\python.exe -m pip install -r backend\requirements-dev.txt
Assert-CiExit

Push-Location backend
try {
    & ..\.venv\neon-migration\Scripts\python.exe -m pip check
    Assert-CiExit
    & ..\.venv\neon-migration\Scripts\python.exe -m ruff check app alembic
    Assert-CiExit

    # Forcer SQLite pour les tests, puis restaurer la variable précédente.
    # Sans CI_TEST_REDIS_URL local jetable, les tests d'intégration Redis seront ignorés.
    $ancienneUrl = $env:DATABASE_URL
    try {
        $env:DATABASE_URL = "sqlite:///:memory:"
        & ..\.venv\neon-migration\Scripts\python.exe -m pytest -q app/tests
        Assert-CiExit
    } finally {
        if ($null -eq $ancienneUrl) {
            Remove-Item Env:\DATABASE_URL -ErrorAction SilentlyContinue
        } else {
            $env:DATABASE_URL = $ancienneUrl
        }
    }
    & ..\.venv\neon-migration\Scripts\python.exe -m compileall -q app alembic
    Assert-CiExit
} finally {
    Pop-Location
}

Push-Location frontend
try {
    $nodeMajor = & node -p "process.versions.node.split('.')[0]"
    Assert-CiExit
    if ([int]$nodeMajor -ne 24) { throw "Node.js 24 est requis pour reproduire la CI." }
    npm ci
    Assert-CiExit
    npm run lint
    Assert-CiExit
    npm run test -- --run
    Assert-CiExit
    npm run build
    Assert-CiExit
} finally {
    Pop-Location
}
```

La fonction `Assert-CiExit` arrête le bloc sur un code de sortie non nul. La
partie PostgreSQL et la construction de l'image sont vérifiées par GitHub
Actions ; elles nécessitent Docker pour être reproduites localement. Ces
commandes PowerShell sont fournies à titre pratique et n'ont pas été exécutées
sur Windows dans cet environnement.

### Tests Redis complets en local (facultatif, Docker Desktop requis)

Après avoir installé les dépendances backend ci-dessus, depuis la racine du dépôt :

```powershell
$conteneur = 'primecrm-test-' + [guid]::NewGuid().ToString('N')
$ancienneUrlRedisTest = $env:CI_TEST_REDIS_URL
$ancienneUrlBase = $env:DATABASE_URL
$demarre = $false
try {
    docker run --detach --rm --name $conteneur `
        --publish '127.0.0.1:56379:6379' redis:7.2-alpine
    if ($LASTEXITCODE -ne 0) { throw 'Impossible de démarrer le Redis de test.' }
    $demarre = $true
    $pret = $false
    for ($i = 0; $i -lt 20; $i++) {
        docker exec $conteneur redis-cli ping 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) { $pret = $true; break }
        Start-Sleep -Milliseconds 500
    }
    if (-not $pret) { throw 'Le Redis de test ne répond pas.' }
    $env:CI_TEST_REDIS_URL = 'redis://127.0.0.1:56379/0'
    $env:DATABASE_URL = 'sqlite:///:memory:'
    Push-Location backend
    try {
        & '..\.venv\neon-migration\Scripts\python.exe' -m pytest -q app/tests
        if ($LASTEXITCODE -ne 0) { throw 'Les tests backend ont échoué.' }
    } finally { Pop-Location }
} finally {
    if ($demarre) { docker stop $conteneur | Out-Null }
    if ($null -eq $ancienneUrlRedisTest) {
        Remove-Item Env:CI_TEST_REDIS_URL -ErrorAction SilentlyContinue
    } else { $env:CI_TEST_REDIS_URL = $ancienneUrlRedisTest }
    if ($null -eq $ancienneUrlBase) {
        Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
    } else { $env:DATABASE_URL = $ancienneUrlBase }
}
```

Le port `56379` doit être libre. Le conteneur est jetable et automatiquement
supprimé à l'arrêt. Ne remplacez pas son URL par celle de votre futur Redis
hébergé. Cette commande ne configure aucun fournisseur et ne déploie rien. Ce
bloc PowerShell n'a pas été exécuté sur Windows dans cet environnement.

Pour examiner les dépendances frontend après `npm ci`, exécuter `npm audit`
puis `npm audit --omit=dev` dans `frontend/`. La CI actuelle ne bloque pas sur
ces résultats. Ne pas lancer automatiquement `npm audit fix --force` : il peut
imposer des mises à jour majeures incompatibles.

## Sécurité

Ne jamais commiter ou partager des secrets. Les futurs secrets GitHub se règlent
à **Settings → Secrets and variables → Actions**, et ceux du backend hébergé
à **Render → service → Environment**. Aucune de ces valeurs n'est utilisée par
ce workflow. La CI ne modifie pas la base Neon.

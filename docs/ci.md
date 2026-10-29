# Intégration continue

Le workflow [CI](../.github/workflows/ci.yml) s'exécute sur les `push`, les
`pull_request` et, une fois présent sur la branche par défaut, sur lancement
manuel (`workflow_dispatch`). Il ne déploie rien et utilise uniquement des
permissions `contents: read`. Aucun secret GitHub, aucune URL Neon et aucune
clé Redis ne sont nécessaires pour la CI. Les identifiants PostgreSQL visibles
dans le workflow ne servent qu'au conteneur jetable du job.

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
- **Redis** : un conteneur Redis 7.2 jetable teste le cache chiffré, l'isolation
  des entreprises, l'invalidation, la limitation concurrente, les pannes et la
  vérification TLS locale. Les tests utilisent un préfixe aléatoire et ne
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
  vérification TypeScript et build Vite. Node 20 est en fin de vie depuis le
  30 avril 2026 ; Node 24 est utilisé pour la CI et le Dockerfile frontend.
  L'hébergement frontend reste à décider lors du déploiement.

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

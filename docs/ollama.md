# Ollama — option facultative

Aucune destination IA n'est autorisée par défaut. Le CRM fonctionne sans IA.

## Poste de développement isolé seulement

L'exception HTTP locale est **désactivée par défaut** et interdite en
production. Dans l'environnement du backend local ou le fichier `.env` ignoré
par Git, configurer explicitement :

```dotenv
APP_ENV=development
AI_ALLOW_LOCAL_OLLAMA=true
```

Avec `docker-compose.yml`, ces deux valeurs sont transmises au backend ; le
Compose de production force l'exception à `false`. Dans l'interface IA, une
URL locale doit être exactement `http://localhost:11434`,
`http://127.0.0.1:11434` ou `http://host.docker.internal:11434`, sans chemin,
identifiant, paramètre ni fragment. En Docker, `localhost` désigne le
conteneur ; `host.docker.internal` désigne l'hôte grâce à `extra_hosts`. La
résolution `host.docker.internal` est acceptée uniquement vers une adresse
locale privée ou `127.0.0.1`.

Installer Ollama et choisir un modèle uniquement après confirmation de
l'administrateur et vérification de sa licence. Depuis la machine qui héberge
Ollama, `ollama list` et `curl http://localhost:11434/api/tags` peuvent aider
à vérifier le service. Dans le CRM, choisir **Paramètres → IA → + Ollama Local**,
saisir l'URL et le modèle, puis utiliser **Tester**. L'application ne télécharge
pas de modèle automatiquement. Les variables historiques `OLLAMA_URL` et
`OLLAMA_MODEL` ne configurent pas un fournisseur dans le CRM.

**Attention :** HTTP n'est pas chiffré. Les prompts transitent en clair sur
ce trajet ; ne pas exposer Ollama à un réseau non fiable. Un service local
ou une machine hôte compromise reste dangereux. Un backend hébergé sur Render
ne peut pas utiliser automatiquement l'Ollama de votre ordinateur personnel.

## Production

Une destination Ollama distante doit avoir une origine HTTPS publique
approuvée dans `AI_ALLOWED_ORIGINS`, un certificat TLS valide pour son nom et
des réponses DNS IPv4 publiques. `AI_ALLOW_LOCAL_OLLAMA=true` empêche le
backend de démarrer en production. Les mêmes contrôles s'appliquent aux autres
fournisseurs IA. Consultez [security.md](security.md) avant toute utilisation ;
une défense de sortie réseau indépendante reste nécessaire.

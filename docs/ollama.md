# Ollama — IA locale gratuite

1. Installer https://ollama.com/download
2. `ollama pull llama3.2` (3B ~2GB, 8GB RAM) ou `ollama pull mistral` (7B ~4GB, 16GB RAM)
3. `ollama serve` (par défaut :11434)
4. Dans Prime CRM : Paramètres > IA > + Ollama Local > URL `http://host.docker.internal:11434` depuis Docker, sinon `http://localhost:11434` > Tester > modèles listés via /api/tags

Licences : Llama 3.2, Mistral 7B, Qwen2.5 autorisent usage commercial sous conditions (vérifiez modèle par modèle). Ne pas télécharger auto sans confirmation admin.
En Docker, utilisez host.docker.internal (extra_hosts: host-gateway déjà configuré).

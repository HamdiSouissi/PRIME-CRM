# CodeCraftAPI — Fournisseur compatible OpenAI

1. Créer compte https://www.codecraftapi.com → clé API
2. Prime CRM > Paramètres > IA > + CodeCraftAPI
   - Base URL : https://www.codecraftapi.com/v1 (préremplie)
   - Clé API (masquée)
   - Modèle (ou Actualiser via GET /models)
   - Tester connexion → GET /models avec Authorization Bearer
3. Génération via POST /chat/completions format OpenAI. Ne jamais supposer gratuit/illimité : afficher uniquement infos accessibles. Choix par fonctionnalité via feature_mapping JSON.

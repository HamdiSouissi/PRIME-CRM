# CodeCraftAPI — Fournisseur compatible OpenAI

> Les clés API IA sont actuellement stockées en clair. Ne pas enregistrer de
> clé réelle avant correction et revue de sécurité. Les tarifs de ce service
> ne sont pas garantis gratuits ; ils doivent être vérifiés avant utilisation.

1. Créer compte https://www.codecraftapi.com → clé API
2. Prime CRM > Paramètres > IA > + CodeCraftAPI
   - Base URL : https://www.codecraftapi.com/v1 (préremplie)
   - Clé API (masquée)
   - Modèle (ou Actualiser via GET /models)
   - Tester connexion → GET /models avec Authorization Bearer
3. Génération via POST /chat/completions format OpenAI. Ne jamais supposer gratuit/illimité : afficher uniquement infos accessibles. Choix par fonctionnalité via feature_mapping JSON.

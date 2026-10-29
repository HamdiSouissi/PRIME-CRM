# CodeCraftAPI — Fournisseur compatible OpenAI

> Les nouvelles clés API IA sont chiffrées dans la base ; les anciennes clés
> en clair ne sont pas migrées automatiquement et doivent être remplacées.
> La revue des destinations réseau IA n'est pas terminée : ne pas enregistrer
> de clé réelle ni exposer le CRM avant cette revue. Les tarifs de ce service ne
> sont pas garantis gratuits et doivent être vérifiés avant utilisation. Voir
> [security.md](security.md) pour les limites et la gestion de `SECRET_KEY`.

1. Créer compte https://www.codecraftapi.com → clé API
2. Prime CRM > Paramètres > IA > + CodeCraftAPI
   - Base URL : https://www.codecraftapi.com/v1 (préremplie)
   - Clé API (masquée)
   - Modèle (ou Actualiser via GET /models)
   - Tester connexion → GET /models avec Authorization Bearer
3. Génération via POST /chat/completions format OpenAI. Ne jamais supposer gratuit/illimité : afficher uniquement infos accessibles. Choix par fonctionnalité via feature_mapping JSON.

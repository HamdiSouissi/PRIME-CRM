# API Prime CRM — OpenAPI

En développement local, la documentation interactive est disponible à
`http://localhost:8000/docs`. Ne pas exposer le serveur de développement.

L'inscription publique est désactivée par défaut et interdite en production.
Sur une base vide, le premier administrateur est initialisé par la commande
locale documentée dans [security.md](security.md), après migration ; il peut
ensuite créer des comptes via **Paramètres → Utilisateurs**. L'ancien endpoint
`/api/v1/auth/seed-admin` a été supprimé.

L'authentification utilise un jeton Bearer. Ne jamais coller de mot de passe,
de jeton ou d'URL de base dans une commande partagée, un journal ou Git. Les
comptes nouvellement créés doivent respecter les mêmes limites de mot de passe
que le premier administrateur : 16 caractères minimum, 72 octets UTF-8 maximum,
sans espaces au début ou à la fin.

Les erreurs HTTP courantes comprennent 400, 401, 403, 404 et 500. La protection
des connexions et la revue des journaux doivent encore être finalisées avant
exposition publique.

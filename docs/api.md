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

## Connexion et limites

Les requêtes `POST /api/v1/auth/login` (formulaire) et
`POST /api/v1/auth/login-json` partagent une limite par IP et une limite par
identifiant. Les corps invalides consomment aussi la limite IP. `429` indique
une limite atteinte et fournit `Retry-After` en secondes ; `503` signale une
protection ou une identification IP indisponible. Les réponses
d'authentification ne sont pas mises en cache. Ces limites dépendent d'une
configuration de proxy vérifiée et de Redis en production ; elles peuvent
bloquer temporairement des utilisateurs derrière une même IP. Voir
[redis.md](redis.md) et [security.md](security.md).

## Mot de passe et sessions

Toutes les routes ci-dessous exigent un jeton Bearer valide ; les chemins sont
préfixés par `/api/v1`.

- `POST /auth/change-password` : objet JSON `old_password`, `new_password`.
  L'ancien mot de passe est obligatoire. Une réponse `200` confirme le
  changement et révoque toutes les sessions de ce compte, y compris le jeton
  utilisé. Un ancien mot de passe incorrect, un nouveau mot de passe invalide
  ou inchangé donnent `400` sans invalider la session. `429` signale la limite
  de tentatives et `503` une limitation indisponible ; une panne de réseau
  après l'envoi peut laisser le résultat incertain.
- `POST /auth/logout-all` : sans corps ; `200` confirme la révocation de toutes
  les sessions de ce compte. Un jeton déjà invalide reçoit `401` : cela ne
  confirme pas la révocation d'autres sessions. Pas de déconnexion par appareil.
- `POST /users/{id}/revoke-sessions` : réservé à un administrateur de la même
  entreprise ; `200` révoque toutes les sessions du compte ciblé, `403` refuse
  un rôle insuffisant et `404` masque les comptes d'une autre entreprise.

Ne pas transmettre les mots de passe et jetons dans une URL ou des journaux.
La configuration IP effective de l'hébergeur et la revue des journaux doivent
encore être vérifiées avant exposition publique. Voir [security.md](security.md).

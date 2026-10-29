# Fournisseur compatible OpenAI — exemple CodeCraftAPI

L'IA est facultative : aucune destination n'est autorisée par défaut. Les
fournisseurs externes **ne sont pas nécessairement gratuits** ; n'activez pas
un service avant d'avoir vérifié son tarif et ses quotas. Aucune création de
compte ni clé réelle n'est nécessaire pour utiliser le CRM sans IA.

Si un fournisseur a été choisi et sa destination approuvée, l'opérateur doit
ajouter son **origine HTTPS exacte**, sans chemin ni secret, à
`AI_ALLOWED_ORIGINS` dans l'environnement du backend. Par exemple, l'URL
`https://www.codecraftapi.com/v1` correspond à l'origine
`https://www.codecraftapi.com`. Cet exemple ne garantit ni disponibilité, ni
compatibilité, ni gratuité. Une liste vide bloque l'utilisation du fournisseur.
Voir les contrôles et limites dans [security.md](security.md).

Un administrateur peut ensuite enregistrer la base URL et la clé dans le CRM,
tester `GET /models` et utiliser `POST /chat/completions`. Les nouvelles clés
sont chiffrées dans la base et masquées dans l'interface. Les anciennes clés en
clair ne sont pas migrées automatiquement et doivent être remplacées. Ne jamais
placer une clé dans une URL, dans `AI_ALLOWED_ORIGINS`, dans Git, dans une
variable `VITE_*`, ni dans les journaux ou une conversation. La rotation de
`SECRET_KEY` rend les clés IA chiffrées illisibles : prévoir un plan de rotation.

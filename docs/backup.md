# Sauvegarde et restauration : à valider

Aucune procédure de sauvegarde ou de restauration n'a été validée dans le cadre
de la préparation du déploiement. Les volumes Docker ne constituent pas une
sauvegarde et l'export JSON de l'API ne contient qu'une partie des données.

Avant le premier déploiement, définir une stratégie adaptée à la base hébergée,
protéger et conserver les sauvegardes hors du dépôt, puis tester une
restauration complète sur une base jetable distincte. Ne jamais restaurer ni
exécuter une migration sur une base réelle sans avoir vérifié et confirmé sa
cible. Les commandes de restauration peuvent écraser des données.

Les nouvelles clés IA sont chiffrées avec une clé dérivée de `SECRET_KEY` et
liée aux identifiants de l'entreprise et du fournisseur. Pour restaurer ces
clés, la restauration doit conserver ces identifiants ainsi que le même
`SECRET_KEY`, conservé séparément dans un gestionnaire de secrets. Les anciennes
sauvegardes peuvent contenir des clés IA en clair : les protéger et révoquer
chez le fournisseur toute clé qui aurait été exposée. La perte ou la rotation
non planifiée de `SECRET_KEY` rend les clés chiffrées illisibles.

La restauration peut aussi rétablir d'anciennes valeurs de session et rendre
à nouveau valides certains jetons révoqués mais non expirés. Prévoir une
révocation globale de tous les comptes après restauration et tester la
procédure ; aucune commande dédiée de révocation globale de la base n'est
fournie actuellement. Ne pas changer `SECRET_KEY` à la légère : cela invalide
les jetons mais rend aussi les clés IA chiffrées illisibles.

Pour l'instance personnelle Windows, un outil prépare une sauvegarde et teste
une restauration locale isolée ; ses essais automatisés utilisent uniquement des
données fictives. La restauration de l'archive réelle n'est validée qu'après
l'exécution réussie sur le PC. Voir [operations_zero_euro.md](operations_zero_euro.md).

Ne commiter ni dump, ni fichier `.env`, ni URL contenant un mot de passe.

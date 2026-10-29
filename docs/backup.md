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

Ne commiter ni dump, ni fichier `.env`, ni URL contenant un mot de passe.

# Sauvegarde et restauration : à valider

Aucune procédure de sauvegarde ou de restauration n'a été validée dans le cadre
de la préparation du déploiement. Les volumes Docker ne constituent pas une
sauvegarde et l'export JSON de l'API ne contient qu'une partie des données.

Avant le premier déploiement, définir une stratégie adaptée à la base hébergée,
protéger et conserver les sauvegardes hors du dépôt, puis tester une
restauration complète sur une base jetable distincte. Ne jamais restaurer ni
exécuter une migration sur une base réelle sans avoir vérifié et confirmé sa
cible. Les commandes de restauration peuvent écraser des données.

Ne commiter ni dump, ni fichier `.env`, ni URL contenant un mot de passe.

# Sauvegarde, restauration de test et contrôle des quotas

Cette procédure vise l'instance personnelle Windows / Neon PostgreSQL 16. Elle
ne déploie pas le CRM, ne lance pas de migration et ne crée pas de service
hébergé. L'outil a été exercé avec des données fictives ; son succès sur la
sauvegarde réelle doit encore être confirmé par son exécution sur le PC.

## 1. Une sauvegarde récente et une vraie restauration locale

Prérequis : Windows, Python 3.11 et les binaires PostgreSQL 16 déjà extraits
dans `%USERPROFILE%\PRIME-CRM-Outils\PostgreSQL-16\pgsql\bin`. Le dossier doit
contenir `pg_dump.exe`, `pg_restore.exe`, `psql.exe`, `initdb.exe`, `pg_ctl.exe`,
`createdb.exe` et `postgres.exe`. Il ne suffit pas d'avoir les seuls clients.
Ouvrir **PowerShell normalement**, pas en administrateur.

Dans la console Neon du projet CRM existant, choisir **Connection Details**,
la base **neondb**, et la connexion **directe** (désactiver « pooled »). Copier
l'URL PostgreSQL complète. Elle contient un mot de passe : ne jamais la coller
dans un message, une commande, une capture d'écran, un dépôt ou un fichier.

Depuis la racine d'une copie du dépôt contenant cet outil :

```powershell
py -3.11 .\tools\backup_restore_windows.py
```

À l'invite masquée, coller l'URL et appuyer sur Entrée. Rien ne doit s'afficher.
Ne pas fermer la fenêtre pendant le test. L'outil :

1. crée si possible un rappel local Windows, lundi à 09 h, sans enregistrer de
   mot de passe ; il n'écrase pas une tâche existante du même nom ;
2. vérifie l'URL directe et la version 16, impose TLS `verify-full` avec les
   certificats racines de Windows et lit la source en transaction en lecture
   seule. `pg_dump` peut prendre des verrous de lecture pendant la sauvegarde ;
3. crée une archive **nouvelle** sous `%USERPROFILE%\PRIME-CRM-Sauvegardes`,
   dans un répertoire dont les ACL sont limitées à l'utilisateur, SYSTEM et
   Administrators ; les anciennes sauvegardes ne sont pas modifiées ;
4. démarre un PostgreSQL 16 jetable sur `127.0.0.1`, avec port et mot de passe
   aléatoires et authentification SCRAM, vérifie son répertoire de données,
   restaure l'archive dans une base locale vide et vérifie les tables, la
   révision `20261029_02` et au moins un super-administrateur actif ;
5. arrête le serveur de test et supprime ses données temporaires si son arrêt
   est confirmé. Il **ne restaure jamais sur Neon**.

Résultat attendu : `SAUVEGARDE=OK`, `RESTAURATION_LOCALE=OK` et
`NETTOYAGE_TEMPORAIRE=OK`. Une archive conservée après un échec de restauration
n'est pas considérée comme validée. Si le nettoyage est incertain, le chemin du
répertoire est affiché : ne pas le partager ni supprimer de force les fichiers
tant que le serveur local pourrait tourner. L'outil masque volontairement les
messages bruts de PostgreSQL, qui peuvent contenir des données ou des secrets.
Ne partager que les catégories d'erreur et les lignes de statut.

Ce test concerne la base et quelques contrôles applicatifs ; il ne prouve pas
la restauration de l'application complète. Les fichiers uploadés, la
`SECRET_KEY`, les rôles globaux PostgreSQL et la configuration des hébergeurs
ne sont pas sauvegardés dans le dump. L'archive contient des données privées et
n'est **pas chiffrée** par l'outil ; l'ACL locale n'est pas un chiffrement et ne
protège pas contre les administrateurs de la machine. Garder une copie chiffrée
sur un support distinct si possible, ainsi que la clé applicative séparément,
sans l'envoyer ici. Une clé exportée via DPAPI est liée au compte Windows et à
l'ordinateur. Un restaurateur PostgreSQL peut exécuter du code présent dans une
archive : ne restaurer que des données provenant d'une base de confiance.

Le contrôle de révision est volontairement fixé à la version CRM actuelle. Pour
une migration future, faire une revue, une sauvegarde récente et obtenir une
autorisation explicite distincte ; ne pas modifier l'attendu simplement pour
contourner un échec.

## 2. Vérifier ensemble les comptes gratuits

Le rappel Windows est une **invitation à vérifier manuellement**, pas un relevé
automatique ni une garantie de disponibilité. Il nécessite un PC allumé et une
session ouverte ; après un horaire manqué, Windows peut le lancer ultérieurement.
`RAPPEL_HEBDOMADAIRE=INSTALLE` signifie que la tâche a été enregistrée, pas
qu'un message a été reçu. Si la tâche `EXISTE`, vérifier son contenu sans la
remplacer ; si `NON_INSTALLE`, créer un rappel hebdomadaire dans son calendrier.

Une fois par semaine, puis avant un déploiement, consulter :

| Hébergeur | Où regarder | À vérifier |
| --- | --- | --- |
| [Netlify](https://app.netlify.com/) | Équipe → **Usage & billing** | Crédits restants et plan gratuit. Netlify indique envoyer des notifications email et dans l'interface à certains seuils ; vérifier l'adresse email. [Documentation](https://docs.netlify.com/manage/accounts-and-billing/billing/billing-for-credit-based-plans/monitor-usage-for-credit-based-plans/) |
| [Render](https://dashboard.render.com/billing) | **Billing → Monthly Included Usage** | Heures Free, bande passante et minutes de build du workspace, plan Hobby, montant éventuel et moyen de paiement. Render indique notifier par email à l'approche des limites. [Documentation](https://render.com/docs/free) |
| [Neon](https://console.neon.tech/) | Organisation → **Billing / Usage**, puis projet | Plan Free et consommations calcul / stockage / réseau. Les notifications de dépense documentées ne sont pas incluses dans Free : ne pas passer à un plan payant pour obtenir une alerte. [Plans](https://neon.com/docs/introduction/plans) |
| [Upstash](https://console.upstash.com/) | Redis → base existante → **Usage**, puis Billing | Plan Free, quotas indiqués dans la console et Auto Upgrade désactivé. Ne pas ajouter de carte : Upstash indique que cela peut convertir les ressources Free en PAYG. [Tarifs](https://upstash.com/docs/redis/overall/billing) |

Ne pas activer d'offre payante, créer de service ou modifier/supprimer de moyen
de paiement sans en comprendre les conséquences. Sur Render, une carte peut
permettre de facturer un dépassement de bande passante ou de pipeline ; un
plafond de pipeline ne couvre pas la bande passante. Une alerte n'est pas un
plafond de dépenses. Ces contrôles n'établissent donc pas une garantie absolue
de facture nulle.

Pour aider au diagnostic sans révéler de secret, transmettre ensemble seulement
les statuts de l'outil et les valeurs de quotas/plan. Ne pas transmettre l'URL
Neon, les mots de passe, la clé applicative, les jetons, la sauvegarde, les logs
bruts ni les numéros de carte.

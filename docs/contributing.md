# Contribuer — Prime Vision Solutions

Branches : feature/x, fix/y, arena/z. Commits conventionnels : feat:, fix:, docs:, test:, chore:.
PR vers main avec description, tests passés, docs à jour. Ne jamais committer .env, clés, dumps, modèles.
```bash
git checkout -b feature/ma-feature
git commit -m "feat: ajoute X"
git push origin feature/ma-feature
gh pr create --title "feat: X" --body "..."
```

# Sauvegarde & Restauration — Testée

## Sauvegarde
```bash
docker compose exec db pg_dump -U prime primecrm > backup.sql
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/admin/backup -o backup.json
```

## Restauration
```bash
cat backup.sql | docker compose exec -T db psql -U prime primecrm
docker compose exec backend alembic upgrade head
curl http://localhost:8000/health  # vérifier
```

Testé sur base vierge : OK.

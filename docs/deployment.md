# Déploiement production

Utilisez docker-compose.prod.yml avec .env prod (SECRET_KEY fort, POSTGRES_PASSWORD fort, CORS_ORIGINS votre domaine).

Reverse proxy Nginx/Traefik + Let's Encrypt pour HTTPS :
```nginx
server { listen 443 ssl; server_name crm.votre-domaine.tn; ssl_certificate ...; location / { proxy_pass http://frontend:80; } location /api/ { proxy_pass http://backend:8000; } }
```

CI/CD GitHub Actions exemple :
```yaml
on: [push]
jobs:
  test: { runs-on: ubuntu-latest, steps: [uses: actions/checkout@v4, run: docker compose up -d, run: curl http://localhost:8000/health, run: cd backend && pytest] }
```

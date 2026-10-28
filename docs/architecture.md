# Architecture — Prime CRM

## Choix techniques justifiés
- React + Vite : SPA rapide, HMR, typage, écosystème shadcn.
- FastAPI : async, OpenAPI auto, Pydantic validation.
- PostgreSQL : ACID, migrations Alembic.
- Docker Compose : reproductible Windows.

## Multi-tenant
Tous les modèles métier ont `company_id` foreign key. Chaque requête filtre `company_id == current_user.company_id`. Tests `test_company_isolation` vérifient.

## Diagramme BDD
Voir README. Relations : Company 1-* User/Client/Opportunity/Activity/Product/Quote/AIConfig/Audit.

## IA
AIServiceManager → OllamaProvider | OpenAICompatProvider → generate/list_models. Feature mapping par fonctionnalité.

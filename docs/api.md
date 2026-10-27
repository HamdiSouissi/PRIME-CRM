# API Prime CRM — OpenAPI

Docs interactives : http://localhost:8000/docs

Exemples curl :
```bash
curl -X POST http://localhost:8000/api/v1/auth/register -H "Content-Type: application/json" -d '{"email":"a@b.tn","password":"A123!a","first_name":"A","last_name":"B","company_name":"Test"}'
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login-json -H "Content-Type: application/json" -d '{"email":"a@b.tn","password":"A123!a"}' | jq -r .access_token)
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/clients
```
Codes : 200 OK, 201 Created, 400 Bad Request, 401 Unauthorized, 403 Forbidden, 404 Not Found, 500 Internal (jamais de secret leak).

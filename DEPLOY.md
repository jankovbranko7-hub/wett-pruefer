# Server

Variablen auf Railway:
- FOOTYSTATS_API_KEY
- PRUEFER_TOKEN

Start: uvicorn server:app --host 0.0.0.0 --port $PORT

POST /pruef  {"spiele": ["Brentford Chelsea"]}
GET /health

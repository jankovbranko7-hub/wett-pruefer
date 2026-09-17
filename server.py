#!/usr/bin/env python3
from __future__ import annotations
import os
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from analyze import analyze
from footystats import FootyStats, FootyStatsError

app = FastAPI(title="Wett-Pruefer", version="1.0")
APP_TOKEN = os.environ.get("PRUEFER_TOKEN", "").strip()

class ListeIn(BaseModel):
    spiele: list[str] = Field(..., min_length=1, max_length=10)

def _key(x_api_key: str | None) -> str:
    key = (x_api_key or os.environ.get("FOOTYSTATS_API_KEY") or "").strip()
    if not key:
        raise HTTPException(500, "FOOTYSTATS_API_KEY fehlt auf dem Server")
    return key

def _auth(authorization: str | None) -> None:
    if not APP_TOKEN:
        return
    if not authorization or authorization.replace("Bearer ", "") != APP_TOKEN:
        raise HTTPException(401, "Token falsch")

@app.get("/health")
def health():
    return {"ok": True, "kalibrierung": "17685/50"}

@app.post("/pruef")
def pruef(body: ListeIn, authorization: str | None = Header(default=None), x_footystats_key: str | None = Header(default=None)):
    _auth(authorization)
    try:
        api = FootyStats(_key(x_footystats_key))
    except FootyStatsError as exc:
        raise HTTPException(400, str(exc)) from exc
    out = []
    for name in body.spiele:
        try:
            out.append({"spiel": name, "ok": True, "text": analyze(api, name)})
        except Exception as exc:
            out.append({"spiel": name, "ok": False, "text": str(exc)})
    return {"n": len(out), "ergebnisse": out}

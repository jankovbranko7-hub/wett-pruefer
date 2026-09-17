#!/usr/bin/env python3
from __future__ import annotations
import os
from fastapi import FastAPI, Form, Header, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from analyze import analyze
from footystats import FootyStats, FootyStatsError

app = FastAPI(title="Wett-Pruefer", version="1.1")
APP_TOKEN = os.environ.get("PRUEFER_TOKEN", "").strip()

PAGE = """<!doctype html>
<html><head><meta name=viewport content="width=device-width,initial-scale=1">
<title>Pruefer</title>
<style>
body { font-family: sans-serif; background: #111; color: #eee; margin: 16px; }
textarea, input { width: 100%; background: #222; color: #eee; border: 1px solid #444; border-radius: 8px; padding: 10px; }
button { margin-top: 12px; padding: 12px 16px; border: 0; border-radius: 8px; background: #7c3aed; color: #fff; font-size: 16px; }
pre { white-space: pre-wrap; background: #1a1a1a; padding: 12px; border-radius: 8px; }
</style></head><body>
<h2>Spiel pruefen</h2>
<p>Eine Zeile pro Spiel, max 10.</p>
<form method=post action=/form>
<label>Token</label>
<input name=token type=password placeholder=pruefer-2026>
<label>Spiele</label>
<textarea name=spiele rows=12></textarea>
<button>Pruefen</button>
</form>
RESULT
</body></html>
"""

class ListeIn(BaseModel):
    spiele: list[str] = Field(..., min_length=1, max_length=10)

def _key():
    key = (os.environ.get("FOOTYSTATS_API_KEY") or "").strip()
    if not key:
        raise HTTPException(500, "FOOTYSTATS_API_KEY fehlt")
    return key

def _auth_ok(token: str | None) -> bool:
    if not APP_TOKEN:
        return True
    return (token or "") == APP_TOKEN

def _clean_lines(raw: str) -> list[str]:
    out = []
    for line in (raw or "").splitlines():
        s = line.strip()
        if not s:
            continue
        if s[0].isdigit() and "." in s[:4]:
            s = s.split(".", 1)[1].strip()
        out.append(s)
    return out[:10]

def _run(spiele: list[str]) -> str:
    api = FootyStats(_key())
    blocks = []
    for name in spiele:
        try:
            blocks.append(analyze(api, name))
        except Exception as exc:
            blocks.append(name + "\nFehler: " + str(exc))
    return "\n\n---\n\n".join(blocks) if blocks else "Keine Spiele."

@app.get("/", response_class=HTMLResponse)
def home():
    return PAGE.replace("RESULT", "")

@app.get("/health")
def health():
    return {"ok": True, "kalibrierung": "17685/50"}

@app.post("/form", response_class=HTMLResponse)
def form(spiele: str = Form(""), token: str = Form("")):
    if not _auth_ok(token):
        return PAGE.replace("RESULT", "<pre>Token falsch.</pre>")
    try:
        text = _run(_clean_lines(spiele))
    except Exception as exc:
        text = str(exc)
    safe = text.replace("&", "&").replace("<", "<")
    return PAGE.replace("RESULT", "<pre>" + safe + "</pre>")

@app.post("/pruef")
def pruef(body: ListeIn, authorization: str | None = Header(default=None)):
    tok = (authorization or "").replace("Bearer ", "")
    if not _auth_ok(tok):
        raise HTTPException(401, "Token falsch")
    try:
        api = FootyStats(_key())
    except FootyStatsError as exc:
        raise HTTPException(400, str(exc)) from exc
    out = []
    for name in body.spiele:
        try:
            out.append({"spiel": name, "ok": True, "text": analyze(api, name)})
        except Exception as exc:
            out.append({"spiel": name, "ok": False, "text": str(exc)})
    return {"n": len(out), "ergebnisse": out}

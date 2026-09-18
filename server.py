#!/usr/bin/env python3
from __future__ import annotations
import os
from fastapi import FastAPI, Form, Header, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from analyze import analyze, analyze_html
from footystats import FootyStats, FootyStatsError

app = FastAPI(title="Wett-Pruefer", version="1.4")
APP_TOKEN = os.environ.get("PRUEFER_TOKEN", "").strip()

PAGE = """<!doctype html>
<html><head><meta name=viewport content="width=device-width,initial-scale=1">
<title>Pruefer</title>
<style>
body { font-family: sans-serif; background: #111; color: #eee; margin: 16px; }
textarea, input { width: 100%; background: #222; color: #eee; border: 1px solid #444; border-radius: 8px; padding: 10px; }
button { margin-top: 12px; padding: 12px 16px; border: 0; border-radius: 8px; background: #7c3aed; color: #fff; font-size: 16px; }
table { width: 100%; border-collapse: collapse; margin: 12px 0 24px; font-size: 15px; }
th, td { text-align: left; padding: 8px 6px; border-bottom: 1px solid #333; }
th { color: #aaa; font-weight: 600; }
.hinweis { color: #aaa; font-size: 13px; }
.err { background: #1a1a1a; padding: 12px; border-radius: 8px; }
</style></head><body>
<h2>Spiel pruefen</h2>
<p>Eine Zeile pro Spiel, max 10.</p>
<form method=post action=/>
<label>Token</label>
<input name=token type=text autocomplete=off autocapitalize=off value="pruefer-2026">
<label>Spiele</label>
<textarea name=spiele rows=8></textarea>
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
    return (token or "").strip() == APP_TOKEN

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

def _run_html(spiele: list[str]) -> str:
    api = FootyStats(_key())
    blocks = []
    for name in spiele:
        try:
            blocks.append(analyze_html(api, name))
        except Exception as exc:
            blocks.append("<p class=err>" + name + ": " + str(exc) + "</p>")
    return "".join(blocks) if blocks else "<p>Keine Spiele.</p>"

def _page(result: str = "") -> str:
    return PAGE.replace("RESULT", result)

@app.get("/", response_class=HTMLResponse)
@app.get("/form", response_class=HTMLResponse)
def home():
    return _page()

@app.post("/", response_class=HTMLResponse)
@app.post("/form", response_class=HTMLResponse)
def form(spiele: str = Form(""), token: str = Form("")):
    if not _auth_ok(token):
        return _page("<p class=err>Token falsch. Genau pruefer-2026.</p>")
    try:
        html = _run_html(_clean_lines(spiele))
    except Exception as exc:
        html = "<p class=err>" + str(exc) + "</p>"
    return _page(html)

@app.get("/health")
def health():
    return {"ok": True, "kalibrierung": "17685/50"}

@app.post("/pruef")
def pruef(body: ListeIn, authorization: str | None = Header(default=None)):
    tok = (authorization or "").replace("Bearer ", "").strip()
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

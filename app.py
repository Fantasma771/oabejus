"""
Servidor FastAPI — Buscador OAB → JusBrasil (v1.3)

Endpoints:
    GET  /                                   -> serve index.html
    GET  /api/oab/processos?state=&number=   -> fluxo principal
    GET  /api/oab/por-nome?name=             -> modo secundário
    GET  /healthz                             -> healthcheck
"""
import os
import re
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from oab_search import (
    run_oab_search_by_name,
    run_processos_por_oab,
)

SERPAPI_KEY = os.environ.get("SERPAPI_KEY")
STATIC_DIR = Path(__file__).parent

app = FastAPI(
    title="Buscador OAB → JusBrasil",
    description=(
        "Recebe OAB (UF + número) e devolve URL JusBrasil, OAB confirmada e "
        "nome completo — usando múltiplas fontes em paralelo. Retorna também "
        "links diretos de verificação manual (cna.oab.org.br, confirmadv.oab.org.br)."
    ),
    version="1.3.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


def _validate_oab(state: str, number: str) -> tuple:
    s = re.sub(r"[^A-Za-z]", "", (state or "")).upper()
    n = re.sub(r"[^0-9]", "", (number or ""))
    if not s or len(s) != 2:
        raise HTTPException(status_code=400, detail="UF inválida (use 2 letras, ex: SP).")
    if len(n) < 4:
        raise HTTPException(status_code=400, detail="Número OAB deve ter ao menos 4 dígitos.")
    return s, n


@app.get("/healthz")
async def healthz():
    return {
        "status": "ok",
        "serpapi_key_set": bool(SERPAPI_KEY),
        "note": "SERPAPI_KEY ausente faz o sistema cair no modo padrão (links de verificação manual).",
    }


@app.get("/api/oab/processos")
async def oab_processos(state: str, number: str):
    s, n = _validate_oab(state, number)
    try:
        out = run_processos_por_oab(s, n, SERPAPI_KEY or "")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Falha: {e}")
    return JSONResponse(out)


@app.get("/api/oab/por-nome")
async def oab_por_nome(name: str):
    name = (name or "").strip()
    if len(name) < 3:
        raise HTTPException(status_code=400, detail="Nome deve ter ao menos 3 caracteres.")
    try:
        out = run_oab_search_by_name(name, SERPAPI_KEY or "")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Falha: {e}")
    return JSONResponse(out)


@app.get("/")
async def root():
    return FileResponse(STATIC_DIR / "index.html")

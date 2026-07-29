"""
Servidor FastAPI — Buscador OAB + JusBrasil

Endpoints:
    GET  /                            -> serve index.html (frontend)
    GET  /api/oab/por-nome?name=...   -> busca OAB pelo nome (cna.oab.org.br)
    GET  /api/oab/processos?state=&number=   -> busca processos pela OAB
    GET  /api/jusbrasil?nome=...      -> busca processos JusBrasil pelo nome
    GET  /api/search?nome=...         -> LEGADO: alias para /api/jusbrasil
    GET  /healthz                     -> healthcheck

Variável de ambiente obrigatória: SERPAPI_KEY
Execução local:
    pip install -r requirements.txt
    export SERPAPI_KEY=sua_chave_aqui
    uvicorn app:app --reload --port 8000
"""
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from oab_search import (
    run_oab_search_by_name,
    run_oab_search_processes,
    run_jusbrasil_search,
)

SERPAPI_KEY = os.environ.get("SERPAPI_KEY")
STATIC_DIR = Path(__file__).parent

app = FastAPI(
    title="Buscador OAB + JusBrasil",
    description=(
        "Microsserviço que faz três buscas jurídicas em paralelo: "
        "OAB por nome no CNA, processos pela OAB, e JusBrasil por nome."
    ),
    version="1.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


def _require_key():
    if not SERPAPI_KEY:
        raise HTTPException(
            status_code=500,
            detail=(
                "SERPAPI_KEY não configurada. Defina a variável de ambiente "
                "SERPAPI_KEY no host (ex: Render → Environment → Add env var)."
            ),
        )


@app.get("/healthz")
async def healthz():
    _require_key()
    return {"status": "ok", "serpapi_key_set": bool(SERPAPI_KEY)}


@app.get("/api/oab/por-nome")
async def oab_por_nome(name: str):
    name = (name or "").strip()
    if len(name) < 3:
        raise HTTPException(status_code=400, detail="Nome deve ter ao menos 3 caracteres.")
    _require_key()
    try:
        out = run_oab_search_by_name(name, SERPAPI_KEY)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Falha na busca: {e}")
    return JSONResponse(out)


@app.get("/api/oab/processos")
async def oab_processos(state: str, number: str):
    state_clean = "".join(c for c in (state or "") if c.isalpha()).upper()
    number_clean = "".join(c for c in (number or "") if c.isdigit())
    if not state_clean or len(state_clean) != 2:
        raise HTTPException(status_code=400, detail="UF deve ter 2 letras (ex: SP, RJ).")
    if len(number_clean) < 4:
        raise HTTPException(status_code=400, detail="Número OAB deve ter ao menos 4 dígitos.")
    _require_key()
    try:
        out = run_oab_search_processes(state_clean, number_clean, SERPAPI_KEY)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Falha na busca: {e}")
    return JSONResponse(out)


@app.get("/api/jusbrasil")
async def jusbrasil(nome: str):
    nome = (nome or "").strip()
    if len(nome) < 3:
        raise HTTPException(status_code=400, detail="Nome deve ter ao menos 3 caracteres.")
    _require_key()
    try:
        out = run_jusbrasil_search(nome, SERPAPI_KEY)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Falha na busca: {e}")
    return JSONResponse(out)


# Compatibilidade com chamadas antigas do agente original
@app.get("/api/search")
async def search_legacy(nome: str):
    return await jusbrasil(nome)


@app.get("/")
async def root():
    return FileResponse(STATIC_DIR / "index.html")

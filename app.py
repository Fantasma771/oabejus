"""
Servidor FastAPI — Buscador OAB → JusBrasil (v1.2)

Endpoints:
    GET  /                              -> serve index.html (frontend 1 aba simples)
    GET  /api/oab/processos?state=&number=    -> fluxo PRINCIPAL: OAB → CNA → JusBrasil
    GET  /api/oab/por-nome?name=              -> modo secundário: nome → OAB + CNA
    GET  /healthz                            -> healthcheck

Variável de ambiente obrigatória: SERPAPI_KEY
"""
import os
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
        "Receba a OAB (UF + número) e devolva a URL canônica do JusBrasil "
        "com todos os processos, junto com a OAB confirmada e o nome completo "
        "do advogado conforme o Cadastro Nacional (cna.oab.org.br)."
    ),
    version="1.2.0",
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
            detail="SERPAPI_KEY não configurada. Defina a env var no host.",
        )


@app.get("/healthz")
async def healthz():
    _require_key()
    return {"status": "ok", "serpapi_key_set": bool(SERPAPI_KEY)}


def _validate_oab(state: str, number: str) -> tuple:
    s = re.sub(r"[^A-Za-z]", "", (state or "")).upper()
    n = re.sub(r"[^0-9]", "", (number or ""))
    if not s or len(s) != 2:
        raise HTTPException(status_code=400, detail="UF inválida (use 2 letras, ex: SP, RJ).")
    if len(n) < 4:
        raise HTTPException(status_code=400, detail="Número OAB deve ter ao menos 4 dígitos.")
    return s, n


import re  # noqa: E402


@app.get("/api/oab/processos")
async def oab_processos(state: str, number: str):
    """
    Fluxo PRINCIPAL:
        1. Consulta `{OAB SP 123456 site:cna.oab.org.br}` no Google
        2. Extrai nome completo + confirma OAB/UF/status
        3. Consulta `{nome} site:jusbrasil.com.br processos` no Google
        4. Devolve a URL canônica do JusBrasil + total de processos + OAB correta + nome
    """
    s, n = _validate_oab(state, number)
    _require_key()
    try:
        out = run_processos_por_oab(s, n, SERPAPI_KEY)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Falha na busca: {e}")
    return JSONResponse(out)


@app.get("/api/oab/por-nome")
async def oab_por_nome(name: str):
    """Modo secundário: nome completo → OAB + URL CNA."""
    name = (name or "").strip()
    if len(name) < 3:
        raise HTTPException(status_code=400, detail="Nome deve ter ao menos 3 caracteres.")
    _require_key()
    try:
        out = run_oab_search_by_name(name, SERPAPI_KEY)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Falha na busca: {e}")
    return JSONResponse(out)


@app.get("/")
async def root():
    return FileResponse(STATIC_DIR / "index.html")

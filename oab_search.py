"""
Buscador OAB + JusBrasil — lógica central usada tanto pelo app FastAPI
quanto pelo CLI standalone e pelo agente CREAO.

Funções públicas:
    slugify_oab(state, number)
    build_query_oab_by_name(name)
    build_query_processes_by_oab(state, number)
    build_query_jusbrasil_by_name(name)    -> re-exportada por jusbrasil_search.py
    serpapi_search(query, api_key)
    extract_oab_data(title, description, url)
    run_oab_search_by_name(name, api_key) -> dict
    run_oab_search_processes(state, number, api_key) -> dict
    run_jusbrasil_search(name, api_key) -> dict
"""
import json
import os
import re
import sys
import unicodedata
import urllib.parse
import urllib.request
from typing import Optional

# Permite import quando esse arquivo é executado direto (CLI)
try:
    from jusbrasil_search import (
        slugify as jb_slugify,
        build_query as jb_build_query,
        find_jusbrasil_url,
        extract_total_processos,
    )
except ImportError:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from jusbrasil_search import (
        slugify as jb_slugify,
        build_query as jb_build_query,
        find_jusbrasil_url,
        extract_total_processos,
    )


CNA_DOMAIN = "cna.oab.org.br"
JUSBRASIL_DOMAIN = "jusbrasil.com.br"
SERPAPI_ENDPOINT = "https://serpapi.com/search.json"


# ============================================================================
# Normalização
# ============================================================================

def normalize_text(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text or "")
    only_ascii = "".join(c for c in nfkd if not unicodedata.combining(c))
    only_ascii = only_ascii.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", only_ascii).strip()


def slugify_oab(state: str, number: str) -> str:
    """Normaliza OAB no formato 'sp-123456'."""
    s = re.sub(r"[^A-Za-z]", "", (state or "")).upper()
    n = re.sub(r"[^0-9]", "", (number or ""))
    return f"{s.lower()}-{n}" if s and n else ""


def _strip_number(num: str) -> str:
    return re.sub(r"\D", "", num or "")


# ============================================================================
# Construção de queries Google + wrapper SerpAPI
# ============================================================================

def build_query_oab_by_name(name: str) -> str:
    if not name or not name.strip():
        raise ValueError("Nome vazio.")
    n = normalize_text(name)
    if len(n) < 3:
        raise ValueError("Nome deve ter ao menos 3 caracteres.")
    quoted = f'"{n}"'
    return f"{quoted} site:{CNA_DOMAIN}"


def build_query_processes_by_oab(state: str, number: str) -> str:
    s = re.sub(r"[^A-Za-z]", "", (state or "")).upper()
    n = re.sub(r"[^0-9]", "", (number or ""))
    if not s or not n:
        raise ValueError("UF e número da OAB são obrigatórios.")
    if len(n) < 4:
        raise ValueError("Número da OAB deve ter ao menos 4 dígitos.")
    return (
        f'"OAB" "{s}" "{n}" '
        f"(site:{CNA_DOMAIN} OR site:{JUSBRASIL_DOMAIN})"
    )


def serpapi_search(query: str, api_key: str, num: int = 10) -> dict:
    if not api_key:
        raise RuntimeError("SERPAPI_KEY ausente — defina a variável de ambiente no host.")
    params = {
        "q": query,
        "api_key": api_key,
        "num": num,
        "gl": "br",
        "hl": "pt-BR",
    }
    url = f"{SERPAPI_ENDPOINT}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "oab-search/1.1"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def serpapi_results_flat(data: dict):
    out = []
    for r in (data.get("organic_results") or []):
        out.append({
            "title": r.get("title", "") or "",
            "url": r.get("link") or r.get("url") or "",
            "description": r.get("snippet") or r.get("snippet_highlighted_words_text") or "",
        })
    return out


# ============================================================================
# Parsers dos snippets de busca
# ============================================================================

# Padrão "OAB/SP 123.456" ou "OAB n.º 123456 / SP"
OAB_FULL_PATTERN = re.compile(
    r"OAB\s*[/\s]\s*([A-Z]{2})\s*[\.\-ºnº]*\s*(\d{1,3}(?:\.\d{3})*|\d{4,8})",
    re.IGNORECASE,
)
# Padrão alternativo só com número
OAB_MISSING_UF = re.compile(r"OAB\s*[\.\-ºnº]*\s*(\d{2,8})", re.IGNORECASE)
# Estado isolado perto de um número
OAB_STATE_NEAR_NUM = re.compile(r"\b([A-Z]{2})\b\s*[\.\-/]?\s*(\d{2,8})")
STATUS_PATTERN = re.compile(
    r"\b(ATIVA|REGULAR|SUSPENSA|CANCELADA|LICENCIADA|LICENCIADO|IRREGULAR|REGISTRADO|REGISTRADA|BAIXA)\b",
    re.IGNORECASE,
)


def extract_oab_data(title: str, description: str, url: str) -> dict:
    blob = f"{title or ''}\n{description or ''}"
    oab_state: Optional[str] = None
    oab_number: Optional[str] = None

    m = OAB_FULL_PATTERN.search(blob)
    if m:
        oab_state = m.group(1).upper()
        oab_number = _strip_number(m.group(2))
    else:
        m_num = OAB_MISSING_UF.search(blob)
        m_state = re.search(r"\bOAB\s*/\s*([A-Z]{2})\b", blob, re.IGNORECASE)
        if m_num:
            oab_number = _strip_number(m_num.group(1))
        if m_state:
            oab_state = m_state.group(1).upper()

    status = None
    m_st = STATUS_PATTERN.search(blob)
    if m_st:
        status = m_st.group(1).upper()

    name = (title or "").strip()
    # Corta sufixos "... - CNA" etc
    name = re.split(r"\s*[-–\|]\s*(?:CNA|OAB|Cadastro|Brasil|Conselho Federal)", name, maxsplit=1)[0].strip()

    return {
        "name": name,
        "oab_number": oab_number,
        "oab_state": oab_state,
        "status": status,
        "cna_url": url if (url and CNA_DOMAIN in url.lower()) else None,
    }


# ============================================================================
# Funções de alto nível (chamadas pelos endpoints)
# ============================================================================

def _first_match(results, predicate):
    for r in results:
        url = r.get("url") or ""
        if predicate(url):
            return r
    return None


def run_oab_search_by_name(name: str, api_key: str) -> dict:
    query = build_query_oab_by_name(name)
    data = serpapi_search(query, api_key=api_key, num=10)
    flat = serpapi_results_flat(data)

    cna_match = _first_match(flat, lambda u: CNA_DOMAIN in u.lower())
    cna_url = cna_match["url"] if cna_match else None

    oab_info = None
    if cna_match:
        oab_info = extract_oab_data(cna_match["title"], cna_match["description"], cna_match["url"])

    return {
        "modo": "oab_por_nome",
        "nome_inserido": name,
        "google_query": query,
        "cna_url": cna_url,
        "oab": oab_info,
        "raw_results": flat[:5],
    }


def run_oab_search_processes(state: str, number: str, api_key: str) -> dict:
    s = re.sub(r"[^A-Za-z]", "", state or "").upper()
    n = re.sub(r"[^0-9]", "", number or "")

    # 1) Perfil no CNA
    query_cna = f'"OAB" "{s}" "{n}" site:{CNA_DOMAIN}'
    data_cna = serpapi_search(query_cna, api_key=api_key, num=10)
    flat_cna = serpapi_results_flat(data_cna)
    cna_match = _first_match(flat_cna, lambda u: CNA_DOMAIN in u.lower())
    profile = None
    cna_url = None
    if cna_match:
        profile = extract_oab_data(cna_match["title"], cna_match["description"], cna_match["url"])
        cna_url = cna_match["url"]

    # 2) Processos vinculados (CNA + JusBrasil)
    query_proc = build_query_processes_by_oab(s, n)
    data_proc = serpapi_search(query_proc, api_key=api_key, num=10)
    flat_proc = serpapi_results_flat(data_proc)

    process_links = []
    for r in flat_proc:
        url = r.get("url") or ""
        if not url:
            continue
        if CNA_DOMAIN in url.lower():
            process_links.append({"title": r["title"], "url": url, "source": "cna", "snippet": r["description"]})
        elif JUSBRASIL_DOMAIN in url.lower():
            process_links.append({"title": r["title"], "url": url, "source": "jusbrasil", "snippet": r["description"]})

    return {
        "modo": "processos_por_oab",
        "oab_inserida": f"{s.lower()}-{n}" if s and n else None,
        "google_query_cna": query_cna,
        "google_query_processos": query_proc,
        "cna_url": cna_url,
        "profile": profile,
        "process_links": process_links,
        "raw_results_cna": flat_cna[:3],
        "raw_results_processos": flat_proc[:5],
    }


def run_jusbrasil_search(name: str, api_key: str) -> dict:
    slug = jb_slugify(name)
    query = jb_build_query(name)
    data = serpapi_search(query, api_key=api_key, num=10)
    flat = serpapi_results_flat(data)
    url, reason = find_jusbrasil_url(flat, slug)
    total = extract_total_processos(flat)
    return {
        "modo": "jusbrasil_por_nome",
        "nome_inserido": name,
        "slug": slug,
        "google_query": query,
        "jusbrasil_url": url,
        "match_quality": reason,
        "total_processos": total,
        "raw_results": flat[:5],
    }


# ============================================================================
# CLI
# ============================================================================

def _cli():
    import argparse
    p = argparse.ArgumentParser(description="Buscador OAB + JusBrasil via SerpAPI")
    p.add_argument("--mode", required=True,
                   choices=["name", "oab", "jusbrasil-name"])
    p.add_argument("--name", help="Nome completo (--mode name ou jusbrasil-name)")
    p.add_argument("--state", help="UF da OAB, ex: SP (--mode oab)")
    p.add_argument("--number", help="Número da OAB, ex: 123456 (--mode oab)")
    p.add_argument("--api-key", default=os.environ.get("SERPAPI_KEY", ""))
    args = p.parse_args()

    if args.mode == "name":
        out = run_oab_search_by_name(args.name, args.api_key)
    elif args.mode == "oab":
        out = run_oab_search_processes(args.state, args.number, args.api_key)
    else:
        out = run_jusbrasil_search(args.name, args.api_key)

    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    _cli()

"""
Buscador OAB → JusBrasil (versão 1.2)

Fluxo único principal:
    Entrada:  UF + número da OAB (ex: SP, 123.456)
    Passo 1:  Google → site:cna.oab.org.br com essa OAB → extrai nome correto
              + confirma OAB/UF/status daquele advogado.
    Passo 2:  Google → jusbrasil.com.br buscando pelo nome extraído → obtém
              a URL canônica do JusBrasil (/processos/nome/{id}/{slug}) com
              todos os processos daquela pessoa.
    Saída:    {
                "jusbrasil_url": "https://www.jusbrasil.com.br/processos/nome/.../slug",
                "total_processos": 1234,
                "match_quality": "exact_slug_match",
                "oab_correta":   { "numero": "...", "uf": "SP", "status": "ATIVA" },
                "nome_completo": "...",
                "cna_url":       "https://cna.oab.org.br/...",
                "google_query_cna":        "...",
                "google_query_jusbrasil":  "...",
                "raw_results_cna":       [...],
                "raw_results_jusbrasil": [...]
              }

Modo secundário preservado: `oab_por_nome` (recebe nome, devolve OAB + URL CNA).
"""
import json
import os
import re
import sys
import unicodedata
import urllib.parse
import urllib.request
from typing import Optional

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
    if not text:
        return ""
    nfkd = unicodedata.normalize("NFKD", text)
    only_ascii = "".join(c for c in nfkd if not unicodedata.combining(c))
    only_ascii = only_ascii.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", only_ascii).strip()


def slugify_oab(state: str, number: str) -> str:
    s = re.sub(r"[^A-Za-z]", "", (state or "")).upper()
    n = re.sub(r"[^0-9]", "", (number or ""))
    return f"{s.lower()}-{n}" if s and n else ""


# ============================================================================
# Wrapper SerpAPI
# ============================================================================

def serpapi_search(query: str, api_key: str, num: int = 10) -> dict:
    if not api_key:
        raise RuntimeError("SERPAPI_KEY ausente — defina a variável de ambiente no host.")
    params = {"q": query, "api_key": api_key, "num": num, "gl": "br", "hl": "pt-BR"}
    url = f"{SERPAPI_ENDPOINT}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "oab-search/1.2"})
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
# Parsers dos snippets CNA
# ============================================================================

OAB_FULL_PATTERN = re.compile(
    r"OAB\s*[/\s]\s*([A-Z]{2})\s*[\.\-ºnº]*\s*(\d{1,3}(?:\.\d{3})*|\d{4,8})",
    re.IGNORECASE,
)
OAB_MISSING_UF = re.compile(r"OAB\s*[\.\-ºnº]*\s*(\d{2,8})", re.IGNORECASE)
STATUS_PATTERN = re.compile(
    r"\b(ATIVA|REGULAR|SUSPENSA|CANCELADA|LICENCIADA|LICENCIADO|IRREGULAR|REGISTRADO|REGISTRADA|BAIXA)\b",
    re.IGNORECASE,
)
# Sufixo do Conselho Federal na URL CNA, ex:
# ".../detalhe/inscricao/123" → /detalhe/inscricao/<id>
CNA_DETAIL_RE = re.compile(r"/detalhe/(?:inscricao|advogado|inscric[ao]+es?)/([\w\-]+)", re.IGNORECASE)


def extract_cna_profile(title: str, description: str, url: str) -> dict:
    """Extrai nome, OAB, UF, status de um resultado CNA do Google."""
    blob = f"{title or ''}\n{description or ''}"

    oab_state: Optional[str] = None
    oab_number: Optional[str] = None
    m = OAB_FULL_PATTERN.search(blob)
    if m:
        oab_state = m.group(1).upper()
        oab_number = re.sub(r"\D", "", m.group(2))
    else:
        m_num = OAB_MISSING_UF.search(blob)
        m_state = re.search(r"\bOAB\s*/\s*([A-Z]{2})\b", blob, re.IGNORECASE)
        if m_num:
            oab_number = re.sub(r"\D", "", m_num.group(1))
        if m_state:
            oab_state = m_state.group(1).upper()

    status = None
    m_st = STATUS_PATTERN.search(blob)
    if m_st:
        status = m_st.group(1).upper()

    # Título CNA típico: "Dr. Fulano de Tal - OAB/SP 123.456 - Cadastro Nacional"
    name = (title or "").strip()
    name = re.split(
        r"\s*[-–\|]\s*(?:OAB|CNA|Cadastro|Brasil|Conselho Federal|SITUAÇÃO|INSCRIÇÃO|Situação|Inscrição|-\s+\d)",
        name,
        maxsplit=1,
    )[0].strip()
    # Remove prefixos honoríficos (Dr., Dra., etc) — eles voltam no campo title se quisermos.
    # Mas aqui preservamos para exibição.
    if not name:
        name = None

    return {
        "name": name,
        "oab_number": oab_number,
        "oab_state": oab_state,
        "status": status,
        "cna_url": url if (url and CNA_DOMAIN in url.lower()) else None,
    }


# ============================================================================
# Modos de busca
# ============================================================================

def _first_match(flat, predicate):
    for r in flat:
        if predicate(r.get("url") or ""):
            return r
    return None


def run_oab_search_by_name(name: str, api_key: str) -> dict:
    """Modo secundário: nome → OAB + URL CNA."""
    n = normalize_text(name)
    if len(n) < 3:
        raise ValueError("Nome deve ter ao menos 3 caracteres.")

    query = f'"{n}" site:{CNA_DOMAIN}'
    data = serpapi_search(query, api_key=api_key, num=10)
    flat = serpapi_results_flat(data)

    cna_match = _first_match(flat, lambda u: CNA_DOMAIN in u.lower())
    oab_info = extract_cna_profile(cna_match["title"], cna_match["description"], cna_match["url"]) if cna_match else None
    cna_url = cna_match["url"] if cna_match else None

    return {
        "modo": "oab_por_nome",
        "nome_inserido": name,
        "google_query_cna": query,
        "cna_url": cna_url,
        "oab_correta": oab_info,
        "nome_completo": (oab_info or {}).get("name"),
        "raw_results_cna": flat[:5],
    }


def run_processos_por_oab(state: str, number: str, api_key: str) -> dict:
    """
    Fluxo principal: OAB (UF + número) → CNA confirma nome + OAB correta,
    depois JusBrasil pelo nome → URL canônica com todos os processos.
    """
    s = re.sub(r"[^A-Za-z]", "", (state or "")).upper()
    n = re.sub(r"[^0-9]", "", (number or ""))
    if not s or len(s) != 2:
        raise ValueError("UF inválida. Use 2 letras (ex: SP, RJ, MG).")
    if len(n) < 4:
        raise ValueError("Número OAB deve ter ao menos 4 dígitos.")

    # 1) Verifica a OAB no CNA e extrai o nome correto
    query_cna = f'"OAB" "{s}" "{n}" site:{CNA_DOMAIN}'
    data_cna = serpapi_search(query_cna, api_key=api_key, num=10)
    flat_cna = serpapi_results_flat(data_cna)
    cna_match = _first_match(flat_cna, lambda u: CNA_DOMAIN in u.lower())
    profile = None
    cna_url = None
    if cna_match:
        profile = extract_cna_profile(cna_match["title"], cna_match["description"], cna_match["url"])
        cna_url = cna_match["url"]

    # O nome extraído do CNA é o que vamos usar pro JusBrasil.
    extracted_name = (profile or {}).get("name")

    # 2) JusBrasil: busca pelo nome correto extraído do CNA.
    # Se não foi possível extrair o nome, faz fallback buscando direto pela OAB.
    if extracted_name and len(normalize_text(extracted_name)) >= 3:
        name_for_jb = normalize_text(extracted_name)
        query_jb = jb_build_query(name_for_jb)
    else:
        # Fallback:  "OAB SP 123456" no JusBrasil
        name_for_jb = None
        query_jb = f'"OAB" "{s}" "{n}" site:{JUSBRASIL_DOMAIN}'
    data_jb = serpapi_search(query_jb, api_key=api_key, num=10)
    flat_jb = serpapi_results_flat(data_jb)

    slug = jb_slugify(name_for_jb) if name_for_jb else None
    jb_url, jb_reason = find_jusbrasil_url(flat_jb, slug) if slug else (None, "no_name_extracted_from_cna")
    jb_total = extract_total_processos(flat_jb)

    return {
        "modo": "processos_por_oab",
        "oab_inserida": f"{s.lower()}-{n}",
        "google_query_cna": query_cna,
        "google_query_jusbrasil": query_jb,
        "cna_url": cna_url,
        "jusbrasil_url": jb_url,
        "match_quality": jb_reason,
        "total_processos": jb_total,
        "oab_correta": {
            "numero": (profile or {}).get("oab_number"),
            "uf":     (profile or {}).get("oab_state"),
            "status": (profile or {}).get("status"),
        } if profile else None,
        "nome_completo": extracted_name,
        "raw_results_cna": flat_cna[:5],
        "raw_results_jusbrasil": flat_jb[:5],
    }


# ============================================================================
# CLI
# ============================================================================

def _cli():
    import argparse
    p = argparse.ArgumentParser(description="Buscador OAB → JusBrasil via SerpAPI")
    p.add_argument("--mode", required=True,
                   choices=["oab", "name"])
    p.add_argument("--state", help="UF (ex: SP) — modo oab")
    p.add_argument("--number", help="Número da OAB (ex: 123456) — modo oab")
    p.add_argument("--name", help="Nome completo — modo name")
    p.add_argument("--api-key", default=os.environ.get("SERPAPI_KEY", ""))
    args = p.parse_args()

    if args.mode == "oab":
        out = run_processos_por_oab(args.state, args.number, args.api_key)
    else:
        out = run_oab_search_by_name(args.name, args.api_key)

    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    _cli()

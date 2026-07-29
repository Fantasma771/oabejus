"""
Lógica de busca no Cadastro Nacional dos Advogados (CNA) — https://cna.oab.org.br/

Estratégia:
    O site do CNA renderiza os resultados dinamicamente (JS), então raspagem direta
    não funciona sem um navegador headless. Para evitar essa dependência, fazemos
    consultas via SerpAPI (Google) com `site:cna.oab.org.br` — o Google já indexou
    as páginas de detalhe dos advogados, então os snippets.title/snippet/url
    devolvidos pelo SerpAPI contêm: nome, número OAB, seccional, situação e URL canônica.

Funções públicas:
    slugify_oab(state, number)        -> str   ex: 'sp-123456'
    build_query_oab_by_name(name)     -> str
    build_query_processes_by_oab(...) -> str   (busca processos públicos nas fuentes indexadas)
    find_cna_url(...)                 -> (url | None, reason)
    extract_oab_data(snippet, title)  -> dict{cna_url, oab_number, oab_state, status, name}
    run_serpapi(...)                  -> JSON   wrapper simples para evitar dependencia extra
"""
import json
import os
import re
import unicodedata
import urllib.parse
import urllib.request


CNA_DOMAIN = "cna.oab.org.br"
JUSBRASIL_DOMAIN = "jusbrasil.com.br"
SERPAPI_ENDPOINT = "https://serpapi.com/search.json"

# URLs canônicas CNA — páginas de detalhe de advogado em cna.oab.org.br
# O site serve páginas do tipo: https://cna.oab.org.br/.../<slug>
CNA_DETAIL_PATTERN = re.compile(
    r"^https?://cna\.oab\.org\.br/(?:[^?\s]+)?",
    re.IGNORECASE,
)

# Padrões para extrair OAB do snippet
# Ex: "Inscrição nº 123.456 - Seccional: São Paulo - OAB/SP 123456"
# Ex: "OAB/SP 123.456", "OAB/SP 123456", "OAB n.º 123456/SP"
OAB_NUMBER_PATTERN = re.compile(
    r"(?:OAB\s*/?\s*[A-Z]{2}\s*[\.\-]?\s*)?(\d{1,3}(?:\.\d{3})*|\d{4,8})",
    re.IGNORECASE,
)
# Padrão "OAB/SP 123456" ou "OAB n.º 123456 / SP"
OAB_FULL_PATTERN = re.compile(
    r"OAB\s*[/\s]\s*([A-Z]{2})\s*[\.\-]?\s*(\d{1,3}(?:\.\d{3})*|\d{4,8})",
    re.IGNORECASE,
)
# Estado brasileiro (seccional) — UF
UF_PATTERN = re.compile(r"\b(?:OAB/([A-Z]{2})|\b([A-Z]{2})\b\s*[/\-]?\s*\d)")
# Status: ativa, regular, suspenso, cancelado, licenciado, irregular
STATUS_PATTERN = re.compile(
    r"\b(ATIVA|REGULAR|SUSPENSA|CANCELADA|LICENCIADA|LICENCIADO|IRREGULAR|REGISTRADO|REGISTRADA)\b",
    re.IGNORECASE,
)


def slugify_oab(state: str, number: str) -> str:
    """Normaliza OAB no formato 'sp-123456'."""
    state_clean = re.sub(r"[^A-Za-z]", "", (state or "")).upper()
    number_clean = re.sub(r"[^0-9]", "", (number or ""))
    return f"{state_clean.lower()}-{number_clean}" if state_clean and number_clean else ""


def normalize_name(name: str) -> str:
    nfkd = unicodedata.normalize("NFKD", name or "")
    only_ascii = "".join(c for c in nfkd if not unicodedata.combining(c))
    only_ascii = only_ascii.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", only_ascii).strip()


def build_query_oab_by_name(name: str) -> str:
    """Busca Google: nome entre aspas + filtro site:cna.oab.org.br."""
    if not name or not name.strip():
        raise ValueError("Nome vazio.")
    n = normalize_name(name).strip()
    quoted = f'"{n}"'
    return f"{quoted} site:cna.oab.org.br"


def build_query_processes_by_oab(state: str, number: str) -> str:
    """Busca Google: número OAB + estado + processos — filtra site:cna.oab.org.br E jusbrasil."""
    state_clean = re.sub(r"[^A-Za-z]", "", (state or "")).upper()
    number_clean = re.sub(r"[^0-9]", "", (number or ""))
    if not state_clean or not number_clean:
        raise ValueError("Estado (UF) e número da OAB são obrigatórios.")
    return (
        f'"OAB" "{state_clean}" "{number_clean}" '
        f"(site:cna.oab.org.br OR site:jusbrasil.com.br)"
    )


def serpapi_search(query: str, api_key: str, num: int = 10) -> dict:
    """Wrapper SerpAPI GET — devolve o JSON da resposta."""
    params = {
        "q": query,
        "api_key": api_key,
        "num": num,
        "gl": "br",
        "hl": "pt-BR",
    }
    url = f"{SERPAPI_ENDPOINT}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "oab-search/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def serpapi_results_to_flat(data: dict):
    """Achata `organic_results` em [{title, url, description}, ...]."""
    out = []
    for r in (data.get("organic_results") or []):
        out.append({
            "title": r.get("title", "") or "",
            "url": r.get("link") or r.get("url") or "",
            "description": r.get("snippet") or r.get("snippet_highlighted_words_text") or "",
        })
    return out


def find_cna_url(results, expected_name: str = ""):
    """Filtra resultados para URLs do CNA. Prioriza páginas de detalhe."""
    matches = []
    expected_norm = normalize_name(expected_name).lower()
    for r in results:
        url = r.get("url") or ""
        # Queremos URLs do CNA — `cna.oab.org.br/detalhe/...` ou `cna.oab.org.br/...`
        if CNA_DOMAIN not in url.lower():
            continue
        matches.append(r)

    if not matches:
        return None, "no_cna_url_in_results"

    # Se encontrou, retorna a primeira (Google já ranqueia).
    return matches[0]["url"], "cna_url_found"


def find_first_cna(results):
    """Busca a primeira URL cujo domínio é cna.oab.org.br."""
    for r in results:
        url = r.get("url") or ""
        if CNA_DOMAIN in url.lower():
            return url, "cna_url_found"
    return None, "no_cna_url_in_results"


def _strip_oab_formatted(num: str) -> str:
    """Remove pontos/milhar: 123.456 -> 123456."""
    return re.sub(r"\D", "", num or "")


def extract_oab_data(title: str, description: str, url: str):
    """
    Extrai nome, número OAB, estado e status a partir do título + snippet do Google.
    Retorna dict com chaves: name, oab_number, oab_state, status, cna_url.
    """
    blob = f"{title or ''}\n{description or ''}"
    oab_full = OAB_FULL_PATTERN.search(blob)
    oab_state = None
    oab_number = None
    if oab_full:
        oab_state = (oab_full.group(1) or "").upper()
        oab_number = _strip_oab_formatted(oab_full.group(2))
    else:
        # Tenta apenas o número — fallback
        # Procura padrão 'OAB 123456' etc
        m_num = re.search(r"OAB\s*[\.\-ºnº]*\s*(\d{2,8})", blob, re.IGNORECASE)
        m_uf = re.search(r"\bOAB\s*/\s*([A-Z]{2})\b", blob, re.IGNORECASE)
        if m_num:
            oab_number = _strip_oab_formatted(m_num.group(1))
        if m_uf:
            oab_state = m_uf.group(1).upper()

    status = None
    m_st = STATUS_PATTERN.search(blob)
    if m_st:
        status = m_st.group(1).upper()

    # Título geralmente já contém o nome do advogado
    name = title or ""
    # Remove sufixos "... - CNA" etc
    name = re.split(r"\s*[-–\|]\s*(?:CNA|OAB|Cadastro|Brasil)", name)[0].strip()

    return {
        "name": name,
        "oab_number": oab_number,
        "oab_state": oab_state,
        "status": status,
        "cna_url": url,
    }


def run_oab_search_by_name(name: str, api_key: str):
    """
    Modo 1: recebe nome do advogado e devolve OAB + URL do CNA.

    Saída:
        {
            "nome_inserido": "...",
            "google_query":   "...",
            "cna_url":        "..." | None,
            "oab": {
                "name":       "...",
                "oab_number": "123456",
                "oab_state":  "SP",
                "status":     "ATIVA" | None,
                "cna_url":    "..." 
            },
            "raw_results": [
                {"title", "url", "description"},
                ...
            ]
        }
    """
    if not name or len(name.strip()) < 3:
        raise ValueError("Nome deve ter ao menos 3 caracteres.")
    if not api_key:
        raise ValueError("api_key (SerpAPI) ausente — defina no formulário.")

    query = build_query_oab_by_name(name)
    data = serpapi_search(query, api_key=api_key, num=10)
    flat = serpapi_results_to_flat(data)

    cna_url, reason = find_first_cna(flat)

    oab_info = None
    for r in flat:
        url = r.get("url") or ""
        if CNA_DOMAIN in url.lower():
            oab_info = extract_oab_data(r.get("title", ""), r.get("description", ""), url)
            break

    return {
        "nome_inserido": name,
        "google_query": query,
        "cna_url": cna_url,
        "cna_url_reason": reason,
        "oab": oab_info,
        "raw_results": flat[:5],
    }


def run_oab_search_processes(state: str, number: str, api_key: str):
    """
    Modo 2: recebe UF + número da OAB e devolve páginas CNA + JusBrasil.

    Saída:
        {
            "oab_inserida": "sp-123456",
            "google_query": "...",
            "cna_url":      ... | None,
            "profile":     {name, oab_number, oab_state, status, cna_url},
            "process_links": [{title, url, source: "cna"|"jusbrasil"}],
            "raw_results": [...]
        }
    """
    state_clean = re.sub(r"[^A-Za-z]", "", (state or "")).upper()
    number_clean = re.sub(r"[^0-9]", "", (number or ""))
    if not state_clean or not number_clean:
        raise ValueError("Estado (UF) e número da OAB são obrigatórios.")
    if not api_key:
        raise ValueError("api_key (SerpAPI) ausente — defina no formulário.")

    # 1ª consulta: perfil no CNA
    query_cna = f'"OAB" "{state_clean}" "{number_clean}" site:cna.oab.org.br'
    data_cna = serpapi_search(query_cna, api_key=api_key, num=10)
    flat_cna = serpapi_results_to_flat(data_cna)

    profile = None
    cna_url = None
    for r in flat_cna:
        url = r.get("url") or ""
        if CNA_DOMAIN in url.lower():
            profile = extract_oab_data(r.get("title", ""), r.get("description", ""), url)
            cna_url = url
            break

    # 2ª consulta: processos relacionados nas fontes indexadas
    query_proc = build_query_processes_by_oab(state_clean, number_clean)
    data_proc = serpapi_search(query_proc, api_key=api_key, num=10)
    flat_proc = serpapi_results_to_flat(data_proc)

    process_links = []
    for r in flat_proc:
        url = r.get("url") or ""
        if not url:
            continue
        if CNA_DOMAIN in url.lower():
            process_links.append({"title": r["title"], "url": url, "source": "cna"})
        elif JUSBRASIL_DOMAIN in url.lower():
            process_links.append({"title": r["title"], "url": url, "source": "jusbrasil"})

    return {
        "oab_inserida": f"{state_clean.lower()}-{number_clean}",
        "google_query_cna": query_cna,
        "google_query_processos": query_proc,
        "cna_url": cna_url,
        "profile": profile,
        "process_links": process_links,
        "raw_results_cna": flat_cna[:3],
        "raw_results_processos": flat_proc[:5],
    }


# CLI auxiliar — também pode ser importado como módulo.
def _cli():
    import argparse
    p = argparse.ArgumentParser(description="Busca OAB no CNA via SerpAPI")
    p.add_argument("--mode", choices=["name", "oab", "jusbrasil-name"], required=True)
    p.add_argument("--name", help="Nome completo (modo name ou jusbrasil-name)")
    p.add_argument("--state", help="UF da OAB (modo oab)")
    p.add_argument("--number", help="Número da OAB (modo oab)")
    p.add_argument("--api-key", default=os.environ.get("SERPAPI_KEY", ""))
    args = p.parse_args()

    if args.mode == "name":
        out = run_oab_search_by_name(args.name, args.api_key)
    elif args.mode == "oab":
        out = run_oab_search_processes(args.state, args.number, args.api_key)
    elif args.mode == "jusbrasil-name":
        from jusbrasil_search import slugify, build_query as build_q_jb, find_jusbrasil_url, extract_total_processos
        slug = slugify(args.name)
        q = build_q_jb(args.name)
        data = serpapi_search(q, api_key=args.api_key, num=10)
        flat = serpapi_results_to_flat(data)
        url, reason = find_jusbrasil_url(flat, slug)
        total = extract_total_processos(flat)
        out = {
            "nome_inserido": args.name,
            "slug": slug,
            "google_query": q,
            "jusbrasil_url": url,
            "match_quality": reason,
            "total_processos": total,
            "raw_results": flat[:5],
        }

    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    _cli()

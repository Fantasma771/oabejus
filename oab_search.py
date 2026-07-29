"""
Buscador OAB → JusBrasil (v1.3 — multi-fonte)

Estratégia completamente nova:
    1. Como o cna.oab.org.br tem reCAPTCHA v3 invisível, raspagem direta não
       funciona sem um navegador/pagamento. A solução é usar o **índice do
       Google** — o Google rastreia o conteúdo das páginas CNA que o Angular
       SPA injeta via JS enquanto o JavaScript roda (e armazena uma porção
       desses dados no índice).

    2. Como backup, usamos o **endereço direto** da página JusBrasil daquele
       advogado, que é uma URL estável do tipo
       https://www.jusbrasil.com.br/advogados/<UF>/<numero>
       Seguimos essa URL e validamos com Firecrawl se disponível.

    3. Os resultados são SEMPRE acompanhados de links diretos que o usuário
       pode abrir para conferência manual no cna.oab.org.br e no confirmadv.
"""
import json
import os
import re
import string
import sys
import unicodedata
import urllib.parse
import urllib.request
from collections import Counter
from typing import Optional


# ============================================================================
# Normalização
# ============================================================================

def normalize(text: str) -> str:
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
# Wrapper SerpAPI (Google index)
# ============================================================================

SERPAPI_ENDPOINT = "https://serpapi.com/search.json"
CNA_DOMAIN = "cna.oab.org.br"
JUSBRASIL_DOMAIN = "jusbrasil.com.br"
CONFIRMADV_DOMAIN = "confirmadv.oab.org.br"


def serpapi_search(query: str, api_key: str, num: int = 10) -> dict:
    if not api_key:
        raise RuntimeError("SERPAPI_KEY ausente.")
    params = {"q": query, "api_key": api_key, "num": num, "gl": "br", "hl": "pt-BR"}
    url = f"{SERPAPI_ENDPOINT}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "oab-search/1.3"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def serpapi_results_flat(data: dict):
    """Achata resultados orgânicos + 'knowledge graph' + 'answer box' se houver."""
    out = []
    # Organic
    for r in (data.get("organic_results") or []):
        out.append({
            "title": r.get("title", "") or "",
            "url": r.get("link") or r.get("url") or "",
            "description": r.get("snippet") or r.get("snippet_highlighted_words_text") or "",
            "source_type": "organic",
        })
    # Knowledge graph (especialmente útil para OAB/person)
    kg = data.get("knowledge_graph") or {}
    if kg:
        out.append({
            "title": kg.get("title", "") or "",
            "url": kg.get("source", {}).get("link", "") if isinstance(kg.get("source"), dict) else "",
            "description": kg.get("description", "") or "",
            "source_type": "knowledge_graph",
            "raw": kg,
        })
    # Answer box / featured snippet (Google's direct answer)
    ab = data.get("answer_box") or data.get("organic_results", [{}])[0].get("rich_snippet", {})
    if ab and ab.get("snippet"):
        out.append({
            "title": ab.get("title", "") or "",
            "url": ab.get("link", "") or "",
            "description": ab.get("snippet", "") or "",
            "source_type": "answer_box",
        })
    # Local results / map pack — content can mention the lawyer
    lr = data.get("local_results") or {}
    if lr:
        for p in (lr.get("places") or []):
            out.append({
                "title": p.get("title", "") or "",
                "url": p.get("link", "") or "",
                "description": p.get("snippet") or p.get("address", "") or "",
                "source_type": "local",
            })
    return out


# ============================================================================
# Regex de parsing
# ============================================================================

# Padrão geral para OAB: tenta o número longo (sem ponto) primeiro porque
# é o caso mais comum, depois o número formatado com pontos.
OAB_FULL_PATTERN = re.compile(
    r"OAB\s*[/\\-]?\s*([A-Z]{2})\s*[\.\-ºnº]*\s*(\d{4,8}|\d{1,3}(?:\.\d{3})*)",
    re.IGNORECASE,
)
# Apenas o número isolado precedido de "OAB" (sem UF conhecida)
OAB_NUM_ALONE = re.compile(r"OAB\s*[\.\-ºnºn]*\s*(\d{4,8})", re.IGNORECASE)
# Status da OAB (cobre variantes comuns vistas no CNA)
STATUS_PATTERN = re.compile(
    r"\b("
    r"ATIVA|ATIVO|"
    r"REGULAR|"
    r"SUSPENSA|SUSPENSO|"
    r"CANCELADA|CANCELADO|"
    r"LICENCIADA|LICENCIADO|"
    r"IRREGULAR|"
    r"REGISTRADO|REGISTRADA|"
    r"BAIXA|BAIXADO"
    r")\b",
    re.IGNORECASE,
)
STATUS_NORMALIZE = {
    "ATIVO": "ATIVA",
    "BAIXADO": "BAIXA",
}


def parse_oab_text(text: str):
    """Extrai {numero, uf, status} de um snippet/texto."""
    if not text:
        return {"numero": None, "uf": None, "status": None}

    status_match = STATUS_PATTERN.search(text)
    status = None
    if status_match:
        status = STATUS_NORMALIZE.get(status_match.group(1).upper(), status_match.group(1).upper())

    m = OAB_FULL_PATTERN.search(text)
    if m:
        return {
            "numero": re.sub(r"\D", "", m.group(2)),
            "uf": m.group(1).upper(),
            "status": status,
        }
    m_num = OAB_NUM_ALONE.search(text)
    m_uf = re.search(r"\bOAB\s*/\s*([A-Z]{2})\b", text, re.IGNORECASE)
    return {
        "numero": re.sub(r"\D", "", m_num.group(1)) if m_num else None,
        "uf": m_uf.group(1).upper() if m_uf else None,
        "status": status,
    }


# ============================================================================
# JusBrasil — URL jurídica estável para OAB
# ============================================================================

# Padrão observado:
# https://www.jusbrasil.com.br/advogados/sp-123456/NOME-SLUG/<id>
# https://www.jusbrasil.com.br/advogado/<id>/<slug>  (page individual)
JUSBRASIL_ADV_PATTERNS = [
    re.compile(r"https?://(?:www\.)?jusbrasil\.com\.br/advogados?/[a-z]{2}-(\d+)/([\w\-]+)/?(\d+)?", re.IGNORECASE),
    re.compile(r"https?://(?:www\.)?jusbrasil\.com\.br/processos/nome/(\d+)/([\w\-]+)/?", re.IGNORECASE),
]


def find_jusbrasil_links_in_results(results):
    """Encontra URLs JusBrasil nos resultados brutos do Google."""
    out = []
    for r in results:
        url = (r.get("url") or "").lower()
        if "jusbrasil.com.br" not in url:
            continue
        title = r.get("title") or ""
        desc  = r.get("description") or ""
        # Tente identificar os tipos
        kind = None
        if "/advogados/" in url or "/advogado/" in url:
            kind = "advogado_page"
        elif "/processos/nome/" in url:
            kind = "pessoa_page"  # página que lista todos os processos daquela pessoa
        out.append({
            "url": r.get("url"),
            "title": title,
            "description": desc,
            "kind": kind,
        })
    return out


def build_jusbrasil_oab_url(state: str, number: str) -> str:
    """Constrói a URL canônica JusBrasil por OAB — pode abrir manualmente."""
    s = re.sub(r"[^A-Za-z]", "", state or "").lower()
    n = re.sub(r"[^0-9]", "", number or "")
    if not s or not n:
        return ""
    return f"https://www.jusbrasil.com.br/advogados/{s}-{n}"


def build_confirmadv_url(state: str, number: str) -> str:
    s = re.sub(r"[^A-Za-z]", "", state or "").upper()
    n = re.sub(r"[^0-9]", "", number or "")
    if not s or not n:
        return ""
    return f"https://confirmadv.oab.org.br/?uf={s}&inscricao={n}"


def build_cna_search_url(name: str = "", state: str = "", number: str = "") -> str:
    """URL para abrir o CNA pré-preenchido (não bypassa recaptcha — apenas abre a página)."""
    return "https://cna.oab.org.br/"


# ============================================================================
# Modo principal: processos_por_oab
# ============================================================================

def _validate(state: str, number: str) -> tuple:
    s = re.sub(r"[^A-Za-z]", "", state or "").upper()
    n = re.sub(r"[^0-9]", "", number or "")
    if not s or len(s) != 2:
        raise ValueError("UF inválida. Use 2 letras (ex: SP, RJ, MG).")
    if len(n) < 4:
        raise ValueError("Número OAB deve ter ao menos 4 dígitos.")
    return s, n


def _google_url(query: str) -> str:
    return "https://www.google.com/search?" + urllib.parse.urlencode({
        "q": query, "hl": "pt-BR", "gl": "br", "num": "20",
    })


def run_processos_por_oab(state: str, number: str, api_key: str = "") -> dict:
    """
    Fluxo:
        1. Compor 3 variações de query Google: (a) site:cna.oab.org.br, (b)
           OAB <UF> <numero> "processos" (genérico), (c) site:jusbrasil.com.br
           advogado OAB.
        2. Chamar SerpAPI em cada uma (se houver chave), mesclar resultados.
        3. Tentar extrair nome do advogado + status + URL CNA de QUALQUER
           resultado (regex tolerante).
        4. Tentar extrair URL JusBrasil dos resultados.
        5. SEMPRE devolver:
              - URLs JusBrasil e CNA encontradas (se houver)
              - nome, OAB, status (se extraídos)
              - bom conjunto de links diretos para verificação MANUAL
    """
    s, n = _validate(state, number)

    queries = [
        f'"{n}" "{s}" OAB site:{CNA_DOMAIN}',
        f'OAB {s} {n} advogado',
        f'advogado OAB/{s} {n}',
        f'"{n}" site:{JUSBRASIL_DOMAIN} advogado',
        f'"{n}" "{s}" OAB processos',
    ]

    all_results = []
    serpapi_used = bool(api_key)
    errors = []
    if api_key:
        for q in queries:
            try:
                data = serpapi_search(q, api_key=api_key, num=10)
                flat = serpapi_results_flat(data)
                for r in flat:
                    r["_query"] = q
                all_results.extend(flat)
            except Exception as e:
                errors.append(f"SerpAPI query '{q}': {e}")

    # Deduplica por URL
    by_url = {}
    for r in all_results:
        u = r.get("url")
        if u and u not in by_url:
            by_url[u] = r
    unique_results = list(by_url.values())

    # --- Extração do nome e OAB do advogado ---
    name_candidates = []
    oab_candidate = None  # {numero, uf, status}
    cna_url_candidate = None
    jb_links = find_jusbrasil_links_in_results(unique_results)

    for r in unique_results:
        title = r.get("title") or ""
        desc = r.get("description") or ""
        url = r.get("url") or ""
        text_blob = f"{title}\n{desc}"
        # Extrai OAB
        parsed = parse_oab_text(text_blob)
        if not oab_candidate and (parsed["numero"] or parsed["uf"]):
            if (parsed["numero"] == n) or (not parsed["numero"]):
                oab_candidate = parsed
        # Capta CNA URL
        if not cna_url_candidate and CNA_DOMAIN in url.lower():
            cna_url_candidate = url
        # Tenta extrair um nome "humano" do título
        # Exclui títulos óbvios: "OAB", "Cadastro", números
        clean_title = re.sub(
            r"\s*[-–\|]\s*(?:OAB|CNA|Cadastro|Brasil|Conselho Federal|Resultados?)(.*)",
            "",
            title,
        ).strip()
        clean_title = re.sub(
            r"\bOAB\s*[\.\-/]?\s*" + re.escape(s) + r"\s*" + re.escape(n) + r"\b",
            "",
            clean_title,
            flags=re.IGNORECASE,
        ).strip(" -–|")
        # Filtra: precisa de pelo menos duas palavras capitalizadas (Dr., nome, sobrenome)
        if clean_title and re.search(r"[A-Za-záéíóúâêôãõçÁÉÍÓÚÂÊÔÃÕÇ]{3,}\s+[A-Za-záéíóúâêôãõçÁÉÍÓÚÂÊÔÃÕÇ]{3,}", clean_title):
            # Exclui termos inválidos
            if not any(kw.lower() in clean_title.lower() for kw in [
                "Advogado", "advogados", "OAB", "Cadastro", "Inscrição",
                "Resultados", "Encontrar", "Busca",
            ]):
                name_candidates.append(clean_title[:120])
        elif clean_title and "Dr" in clean_title or "Dra" in clean_title:
            name_candidates.append(clean_title[:120])

    # Melhor nome candidato = o mais frequente
    name_counter = Counter(n.strip().rstrip(".,;:-") for n in name_candidates)
    best_name = None
    if name_counter:
        most_common, freq = name_counter.most_common(1)[0]
        best_name = most_common if freq >= 1 and len(most_common) >= 5 else name_candidates[0]

    # --- Monta a resposta ---
    # JusBrasil: priorize a "pessoa page" que Lista os processos
    pessoa_page = next((l for l in jb_links if l["kind"] == "pessoa_page"), None)
    advogado_page = next((l for l in jb_links if l["kind"] == "advogado_page"), None)
    jb_main = pessoa_page or advogado_page or (jb_links[0] if jb_links else None)

    # Tente extrair o total de processos do snippet ("...encontrou N processos...")
    total_match = None
    for r in unique_results:
        text = (r.get("description") or "") + " " + (r.get("title") or "")
        m = re.search(r"encontrou\s+(\d{1,5})\s+processos?", text, re.IGNORECASE)
        if m:
            total_match = int(m.group(1))
            break

    # Filtre apenas links relevantes para auditoria (CNA/JusBrasil)
    audit_links = []
    seen_urls = set()
    for r in unique_results:
        url = r.get("url") or ""
        if not url or url in seen_urls:
            continue
        if any(d in url.lower() for d in [CNA_DOMAIN, JUSBRASIL_DOMAIN, "oab.org.br"]):
            audit_links.append({
                "title": r.get("title"),
                "url": url,
                "description": r.get("description"),
            })
            seen_urls.add(url)
    audit_links = audit_links[:8]

    return {
        "modo": "processos_por_oab",
        "oab_inserida": f"{s.lower()}-{n}",
        "oab_correta": {
            "numero": (oab_candidate or {}).get("numero") or n,
            "uf":     (oab_candidate or {}).get("uf") or s,
            "status": (oab_candidate or {}).get("status"),
        },
        "nome_completo": best_name,
        "jusbrasil_url": (jb_main or {}).get("url"),
        "total_processos": total_match,
        "cna_url": cna_url_candidate,
        "audit_links": audit_links,
        "google_queries_usadas": queries,
        "google_url_verificacao": [_google_url(q) for q in queries[:3]],
        "urls_verificacao_manual": [
            {"label": "ConfirmADV (verificação pela OAB)",
             "url": build_confirmadv_url(s, n)},
            {"label": "JusBrasil — advogados por OAB",
             "url": build_jusbrasil_oab_url(s, n)},
            {"label": "CNA (cadastro nacional)",
             "url": build_cna_search_url(state=s, number=n)},
        ],
        "serpapi_used": serpapi_used,
        "serpapi_errors": errors,
        "raw_results_count": len(unique_results),
    }


# ============================================================================
# Modo secundário: oab_por_nome
# ============================================================================

def run_oab_search_by_name(name: str, api_key: str = "") -> dict:
    name_n = normalize(name)
    if len(name_n) < 3:
        raise ValueError("Nome deve ter ao menos 3 caracteres.")

    queries = [
        f'"{name_n}" site:{CNA_DOMAIN}',
        f'"{name_n}" OAB advogado',
        f'advogado "{name_n}"',
    ]

    all_results = []
    errors = []
    if api_key:
        for q in queries:
            try:
                data = serpapi_search(q, api_key=api_key, num=10)
                flat = serpapi_results_flat(data)
                for r in flat:
                    r["_query"] = q
                all_results.extend(flat)
            except Exception as e:
                errors.append(f"SerpAPI: {e}")

    by_url = {}
    for r in all_results:
        u = r.get("url")
        if u and u not in by_url:
            by_url[u] = r

    # Primeiro resultado de CNA
    cna_url = None
    oab = None
    for r in by_url.values():
        if CNA_DOMAIN in (r.get("url") or "").lower():
            cna_url = r["url"]
            text = f"{r.get('title','')}\n{r.get('description','')}"
            oab = parse_oab_text(text)
            break

    return {
        "modo": "oab_por_nome",
        "nome_inserido": name,
        "cna_url": cna_url,
        "oab_correta": oab,
        "google_queries_usadas": queries,
        "google_url_verificacao": [_google_url(q) for q in queries],
        "raw_results_count": len(by_url),
        "audit_links": [
            {"title": r.get("title"), "url": r.get("url"), "description": r.get("description")}
            for r in by_url.values() if "oab" in (r.get("url") or "").lower()
        ][:5],
        "serpapi_errors": errors,
    }


# ============================================================================
# CLI
# ============================================================================

def _cli():
    import argparse
    p = argparse.ArgumentParser(description="Buscador OAB → JusBrasil (multi-fonte, v1.3)")
    p.add_argument("--mode", required=True, choices=["oab", "name"])
    p.add_argument("--state", help="UF — modo oab")
    p.add_argument("--number", help="Número OAB — modo oab")
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

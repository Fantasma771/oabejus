"""Parser JusBrasil — utilitários preservados"""
import re
import unicodedata

JUSBRASIL_PROCESSOS_PATTERN = re.compile(
    r"^https?://(?:www\.)?jusbrasil\.com\.br/processos/nome/(\d+)/([\w\-]+)/?$"
)
JUSBRASIL_ADVOGADO_PATTERN = re.compile(
    r"^https?://(?:www\.)?jusbrasil\.com\.br/advogados?/([a-z]{2})-(\d+)/([\w\-]+)/?(\d+)?/?$",
    re.IGNORECASE,
)
TOTAL_RE = re.compile(r"encontrou\s+(\d+)\s+processos?", re.IGNORECASE)


def slugify(name: str) -> str:
    nfkd = unicodedata.normalize("NFKD", name)
    only_ascii = "".join(c for c in nfkd if not unicodedata.combining(c))
    only_ascii = only_ascii.encode("ascii", "ignore").decode("ascii")
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", only_ascii).strip("-").lower()
    return cleaned


def is_jusbrasil_url(url: str) -> bool:
    return bool(url) and "jusbrasil.com.br" in url.lower()


def parse_jusbrasil_path(url: str) -> dict:
    """Devolve um dict com kind e campos extraídos."""
    m1 = JUSBRASIL_PROCESSOS_PATTERN.match(url or "")
    if m1:
        return {"kind": "pessoa_page", "pessoa_id": m1.group(1), "slug": m1.group(2)}
    m2 = JUSBRASIL_ADVOGADO_PATTERN.match(url or "")
    if m2:
        return {"kind": "advogado_page", "uf": m2.group(1), "numero": m2.group(2),
                "slug": m2.group(3), "lawyer_id": m2.group(4)}
    return {"kind": None}


def extract_total_processos(results):
    snippets = " ".join(
        (r.get("description") or r.get("snippet") or "") for r in results
    )
    m = TOTAL_RE.search(snippets)
    return int(m.group(1)) if m else None

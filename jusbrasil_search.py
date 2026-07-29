"""
Lógica da busca JusBrasil por nome (preservada do agente original).
"""
import re
import unicodedata

JUSBRASIL_PATTERN = re.compile(
    r"^https?://(?:www\.)?jusbrasil\.com\.br/processos/nome/(\d+)/([\w\-]+)/?$"
)
TOTAL_RE = re.compile(r"encontrou\s+(\d+)\s+processos?", re.IGNORECASE)


def slugify(name: str) -> str:
    nfkd = unicodedata.normalize("NFKD", name)
    only_ascii = "".join(c for c in nfkd if not unicodedata.combining(c))
    only_ascii = only_ascii.encode("ascii", "ignore").decode("ascii")
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", only_ascii).strip("-").lower()
    return cleaned


def build_query(name: str) -> str:
    quoted = f'"{name.strip()}"'
    return f"{quoted} site:jusbrasil.com.br processos"


def find_jusbrasil_url(results, expected_slug):
    matches = []
    for r in results:
        url = r.get("url") or r.get("link") or ""
        m = JUSBRASIL_PATTERN.match(url)
        if not m:
            continue
        _id, slug = m.group(1), m.group(2)
        matches.append((url, slug, _id))

    if not matches:
        return None, "no_jusbrasil_url_in_results"

    for url, slug, _id in matches:
        if slug == expected_slug:
            return url, "exact_slug_match"
    for url, slug, _id in matches:
        if slug.replace("-", "") == expected_slug.replace("-", ""):
            return url, "slug_strip_match"
    return matches[0][0], "first_jusbrasil_match"


def extract_total_processos(results):
    snippets = " ".join(
        (r.get("description") or r.get("snippet") or "") for r in results
    )
    m = TOTAL_RE.search(snippets)
    return int(m.group(1)) if m else None

# Buscador OAB → JusBrasil (v1.2)

Microsserviço FastAPI, mínimo, com **fluxo principal único**:

1. Você informa **UF + número da OAB**.
2. O sistema consulta o Google restrito a `site:cna.oab.org.br` para **confirmar
   o nome completo e a OAB correta** daquele advogado.
3. Em seguida, consulta o Google restrito a `site:jusbrasil.com.br` usando o nome
   extraído, e devolve a **URL canônica do JusBrasil** com todos os processos.

## Saída entregue ao usuário

Para uma consulta `OAB SP 123456`, a resposta traz:

| # | Campo                | Exemplo                                                                  |
|---|----------------------|--------------------------------------------------------------------------|
| 1 | **JusBrasil URL**    | `https://www.jusbrasil.com.br/processos/nome/59940841/slug-do-nome`     |
| 2 | **Total de processos**| `475 processos`                                                          |
| 3 | **OAB correta**      | `OAB/SP 123456` + status (ATIVA / SUSPENSA / ...)                       |
| 4 | **Nome completo**    | `Jamila Drielly Moura Oliveira`                                          |
| 5 | **URL CNA**          | `https://cna.oab.org.br/...`                                             |

## Estrutura

```
.
├── app.py                # FastAPI server (2 endpoints)
├── oab_search.py         # fluxo OAB→CNA→JusBrasil em uma chamada
├── jusbrasil_search.py   # parser de snippets do JusBrasil
├── index.html            # frontend minimalista (1 formulário)
├── requirements.txt
└── README.md
```

## Variáveis de ambiente

| Variável      | Obrigatória | Descrição                                                              |
|---------------|-------------|------------------------------------------------------------------------|
| `SERPAPI_KEY` | sim         | chave SerpAPI (cadastro grátis em https://serpapi.com — ~100/mês free). |
| `PORT`        | não         | porta que o uvicorn escuta (Render/Railway/Fly setam automaticamente). |

## Rodar local

```bash
pip install -r requirements.txt
export SERPAPI_KEY=sua_chave_aqui
uvicorn app:app --reload --port 8000
```

Abra http://localhost:8000 — o frontend já está pronto.

## Hospedagem

### 🔵 Render (recomendado)

1. Suba esses 5 arquivos (sem `__pycache__`) num repo GitHub.
2. Render → **New + → Web Service → Connect repo**.
3. **Build Command**: `pip install -r requirements.txt`
4. **Start Command**: `uvicorn app:app --host 0.0.0.0 --port $PORT`
5. **Environment → Add**: `SERPAPI_KEY=sua_chave`.
6. **Create Web Service** → abra `https://<service>.onrender.com`.

### 🟢 Railway

1. **New Project → Deploy from GitHub Repo**.
2. Em **Variables**, defina `SERPAPI_KEY`.
3. Ajuste o **Start Command** para `uvicorn app:app --host 0.0.0.0 --port $PORT`.
4. Gere um domínio público em **Settings**.

### 🟣 Fly.io

```bash
fly launch --name buscador-oab --no-deploy
fly secrets set SERPAPI_KEY=sua_chave_aqui
fly deploy
```

### 🟠 VPS Ubuntu + nginx + HTTPS com certbot

```bash
apt update && apt install -y python3-pip python3-venv nginx
git clone <repo> /opt/buscador
cd /opt/buscador && python3 -m venv venv
source venv/bin/activate && pip install -r requirements.txt
echo 'export SERPAPI_KEY=sua_chave' >> /root/.bashrc
source /root/.bashrc

# /etc/systemd/system/buscador.service
# [Service]
# WorkingDirectory=/opt/buscador
# EnvironmentFile=/root/.bashrc
# ExecStart=/opt/buscador/venv/bin/uvicorn app:app --host 127.0.0.1 --port 8000
# Restart=always
systemctl daemon-reload && systemctl enable --now buscador

# /etc/nginx/sites-available/buscador
# server { server_name seu-dominio; location / { proxy_pass http://127.0.0.1:8000; } }
ln -s /etc/nginx/sites-available/buscador /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx
certbot --nginx -d seu-dominio
```

## Endpoints

### `GET /api/oab/processos?state=<UF>&number=<numero>` — **fluxo principal**

```bash
curl "https://seu-host/api/oab/processos?state=SP&number=123456"
```

Resposta:
```json
{
  "modo": "processos_por_oab",
  "oab_inserida": "sp-123456",
  "google_query_cna":       "\"OAB\" \"SP\" \"123456\" site:cna.oab.org.br",
  "google_query_jusbrasil": "\"Jamila Drielly Moura Oliveira\" site:jusbrasil.com.br processos",
  "cna_url":       "https://cna.oab.org.br/...",
  "jusbrasil_url": "https://www.jusbrasil.com.br/processos/nome/59940841/jamila-drielly-moura-oliveira",
  "match_quality": "exact_slug_match",
  "total_processos": 475,
  "oab_correta": { "numero": "123456", "uf": "SP", "status": "ATIVA" },
  "nome_completo": "Jamila Drielly Moura Oliveira",
  "raw_results_cna": [...],
  "raw_results_jusbrasil": [...]
}
```

### `GET /api/oab/por-nome?name=<nome>` — modo secundário

Útil quando você **não sabe** a OAB mas quer descobrir:

```bash
curl "https://seu-host/api/oab/por-nome?name=Jamila%20Drielly%20Moura%20Oliveira"
```

Resposta (resumo):
```json
{
  "modo": "oab_por_nome",
  "nome_inserido": "Jamila Drielly Moura Oliveira",
  "google_query_cna": "\"Jamila Drielly Moura Oliveira\" site:cna.oab.org.br",
  "cna_url": "https://cna.oab.org.br/...",
  "oab_correta": { "name": "...", "oab_number": "123456", "oab_state": "SP", "status": "ATIVA" },
  "nome_completo": "Jamila Drielly Moura Oliveira",
  "raw_results_cna": [...]
}
```

### `GET /healthz`

```
{"status":"ok","serpapi_key_set":true}
```

### `GET /`

Serve o `index.html` (frontend).

## Limitações conhecidas

- A SerpAPI free tier permite **~100 buscas/mês** — cada chamada OAB usa 2 consultas (CNA + JusBrasil), então o limite conta dobrado.
- Para tráfego alto, considere cachear por `(uf, number) → resposta` por 24h.
- O CNA é uma SPA; raspagem direta seria frágil. Por isso usamos o índice do Google (`site:cna.oab.org.br`), que já tem nome + OAB + UF + status + link canônico nos snippets.

## Solução de problemas

| Sintoma                                       | Causa                                          | Como resolver                                       |
|-----------------------------------------------|-------------------------------------------------|-----------------------------------------------------|
| `SERPAPI_KEY não configurada` (HTTP 500)      | env var ausente                                | Adicione em Render/Railway/Fly secrets              |
| `HTTP 502 — Falha na busca`                   | quota SerpAPI excedida / 429                    | Aguarde reset mensal ou upgrade do plano            |
| `cna_url` / `jusbrasil_url` ausentes          | Google não indexou aquela OAB/nome             | Tente variações (com e sem zeros à esquerda)         |
| `match_quality: no_jusbrasil_url_in_results` | advogado não tem página JusBrasil              | Pode não existir — tente abrir o CNA direto         |

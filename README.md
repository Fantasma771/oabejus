# Buscador OAB + JusBrasil — pacote para hospedagem

Microsserviço FastAPI que oferece três buscas jurídicas em uma única interface
web (frontend pronto), todas alimentadas via SerpAPI:

| # | Endpoint                          | Entrada                            | O que devolve                                                                  |
|---|-----------------------------------|------------------------------------|--------------------------------------------------------------------------------|
| 1 | `GET /api/oab/por-nome?name=`     | nome completo do advogado          | número OAB, UF, status, URL canônica do CNA em `cna.oab.org.br`                  |
| 2 | `GET /api/oab/processos?state=&number=` | sigla da seccional + número da OAB | perfil do advogado no CNA + lista de links de processos (CNA + JusBrasil)         |
| 3 | `GET /api/jusbrasil?nome=`        | nome completo do advogado          | URL canônica do JusBrasil + total de processos + qualidade do match             |

A interface `/` (servida automaticamente quando você roda `uvicorn`) tem 3 abas
que correspondem aos três endpoints, então o serviço já é utilizável pelo
navegador — basta hospedar.

---

## Estrutura

```
.
├── app.py                # servidor FastAPI
├── oab_search.py         # lógica de busca OAB + JusBrasil (regex, queries, parser)
├── jusbrasil_search.py   # lógica JusBrasil por nome (preservada)
├── index.html            # frontend (3 abas: OAB por nome / processos OAB / JusBrasil)
├── requirements.txt      # fastapi, uvicorn, httpx
└── README.md             # este arquivo
```

A chave SerpAPI é lida da env `SERPAPI_KEY`.

---

## Variáveis de ambiente

| Nome         | Obrigatória | Descrição                                                                  |
|--------------|-------------|----------------------------------------------------------------------------|
| `SERPAPI_KEY`| sim         | chave em https://serpapi.com (free tier: ~100 buscas/mês).                  |
| `PORT`       | não         | porta que o uvicorn deve escutar (Render/Railway/Fly setam automaticamente). |

---

## Rodar local

```bash
pip install -r requirements.txt
export SERPAPI_KEY=sua_chave_aqui
uvicorn app:app --reload --port 8000
```

Abra http://localhost:8000.

Endpoint de saúde (para healthcheck da hospedagem):

```
GET /healthz   -> {"status":"ok","serpapi_key_set":true}
```

---

## Hospedagem — passo a passo

### 🔵 Opção 1 — Render (recomendado, free tier com HTTPS automático)

1. Suba os 6 arquivos para um repositório no GitHub (commit tudo).
2. Acesse https://render.com → **New + → Web Service → Connect repo**.
3. Preencha:
   - **Runtime**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn app:app --host 0.0.0.0 --port $PORT`
   - **Instance Type**: `Free`
4. Na aba **Environment → Add Environment Variable**:
   - `SERPAPI_KEY` = sua chave
5. Clique **Create Web Service**. O Render publica `https://<service>.onrender.com`.
6. Pronto: abra a URL e use as três abas.

> Health check opcional: aponte o Render para `/healthz`.

### 🟢 Opção 2 — Railway (crédito grátis inicial, sem cartão)

1. Suba para o GitHub.
2. Acesse https://railway.app → **New Project → Deploy from GitHub Repo**.
3. Railway detecta Python e roda `pip install -r requirements.txt` automaticamente.
4. Em **Variables** adicione `SERPAPI_KEY`.
5. Em **Settings → Start Command** ajuste para:
   `uvicorn app:app --host 0.0.0.0 --port $PORT`
6. Em **Settings** gere um domínio público (Railway.now).
7. Abra o domínio.

### 🟣 Opção 3 — Fly.io (`fly launch`)

1. Instale o CLI: `curl -L https://fly.io/install.sh | sh`
2. `fly auth signup` (cria conta + instala token).
3. Dentro do diretório do projeto:
   ```bash
   fly launch --name buscador-oab --no-deploy
   fly secrets set SERPAPI_KEY=sua_chave_aqui
   fly deploy
   ```
4. O Fly cria `https://buscador-oab.fly.dev`.

### 🟠 Opção 4 — VPS (DigitalOcean/Hetzner/AWS Lightsail) com nginx

1. VPS Ubuntu 22.04+, IP público, porta 80/443 liberada.
2. `ssh root@<ip>`
3. Instale Python e clone o repo:
   ```bash
   apt update && apt install -y python3-pip python3-venv nginx
   git clone <seu-repo>.git /opt/buscador
   cd /opt/buscador && python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   echo 'export SERPAPI_KEY=sua_chave' >> /root/.bashrc
   source /root/.bashrc
   ```
4. Systemd service (`/etc/systemd/system/buscador.service`):
   ```ini
   [Unit]
   Description=Buscador OAB FastAPI
   After=network.target
   [Service]
   User=root
   WorkingDirectory=/opt/buscador
   EnvironmentFile=/root/.bashrc
   ExecStart=/opt/buscador/venv/bin/uvicorn app:app --host 127.0.0.1 --port 8000
   Restart=always
   [Install]
   WantedBy=multi-user.target
   ```
   ```bash
   systemctl daemon-reload
   systemctl enable --now buscador
   systemctl status buscador
   ```
5. Nginx HTTPS:
   ```bash
   apt install -y certbot python3-certbot-nginx
   ```
   `/etc/nginx/sites-available/buscador`:
   ```nginx
   server {
       server_name seu-dominio.com.br;
       location / {
           proxy_pass http://127.0.0.1:8000;
           proxy_set_header Host $host;
           proxy_set_header X-Forwarded-For $remote_addr;
       }
   }
   ```
   ```bash
   ln -s /etc/nginx/sites-available/buscador /etc/nginx/sites-enabled/
   nginx -t && systemctl reload nginx
   certbot --nginx -d seu-dominio.com.br
   ```

---

## Endpoints — referência completa

### `GET /api/oab/por-nome?name=<nome>`

```bash
curl "https://seu-host/api/oab/por-nome?name=Jamila%20Drielly%20Moura%20Oliveira"
```

```json
{
  "modo": "oab_por_nome",
  "nome_inserido": "Jamila Drielly Moura Oliveira",
  "google_query": "\"JAMILA DRIELLY MOURA OLIVEIRA\" site:cna.oab.org.br",
  "cna_url": "https://cna.oab.org.br/...",
  "oab": {
    "name": "...",
    "oab_number": "123456",
    "oab_state": "SP",
    "status": "ATIVA",
    "cna_url": "https://cna.oab.org.br/..."
  },
  "raw_results": [...]
}
```

### `GET /api/oab/processos?state=<UF>&number=<numero>`

```bash
curl "https://seu-host/api/oab/processos?state=SP&number=123456"
```

```json
{
  "modo": "processos_por_oab",
  "oab_inserida": "sp-123456",
  "google_query_cna": "\"OAB\" \"SP\" \"123456\" site:cna.oab.org.br",
  "google_query_processos": "\"OAB\" \"SP\" \"123456\" (site:cna.oab.org.br OR site:jusbrasil.com.br)",
  "cna_url": "https://cna.oab.org.br/...",
  "profile": { "name": "...", "oab_number": "123456", "oab_state": "SP", "status": "ATIVA" },
  "process_links": [
    { "title": "...", "url": "https://...", "source": "cna", "snippet": "..." },
    { "title": "...", "url": "https://www.jusbrasil.com.br/...", "source": "jusbrasil", "snippet": "..." }
  ]
}
```

### `GET /api/jusbrasil?nome=<nome>`

```bash
curl "https://seu-host/api/jusbrasil?nome=Jamila%20Drielly%20Moura%20Oliveira"
```

```json
{
  "modo": "jusbrasil_por_nome",
  "nome_inserido": "Jamila Drielly Moura Oliveira",
  "slug": "jamila-drielly-moura-oliveira",
  "google_query": "\"Jamila Drielly Moura Oliveira\" site:jusbrasil.com.br processos",
  "jusbrasil_url": "https://www.jusbrasil.com.br/processos/nome/59940841/jamila-drielly-moura-oliveira",
  "match_quality": "exact_slug_match",
  "total_processos": 475
}
```

### `GET /healthz`

```json
{ "status": "ok", "serpapi_key_set": true }
```

> **Legado**: `GET /api/search?nome=<nome>` ainda funciona como alias para `/api/jusbrasil` (compatibilidade com a versão antiga do agente).

---

## Limitações conhecidas

- A SerpAPI free tier permite **~100 buscas/mês**. Para mais volume: plano pago a partir de ~USD 50/mês por 5.000 buscas.
- A busca é síncrona (~1-3s por chamada SerpAPI). Para tráfego alto, considere cachear resultados por `(slug)` ou `(oab_inserida)` por 24h.
- O CNA serve os resultados dinamicamente (SPA React); raspagem direta é frágil. Por isso usamos o índice do Google (`site:cna.oab.org.br`) — funciona em qualquer navegador e é confiável.

## Solução de problemas

| Sintoma                                  | Causa provável                                | Solução                                              |
|------------------------------------------|-----------------------------------------------|------------------------------------------------------|
| `SERPAPI_KEY não configurada` (HTTP 500) | env var ausente no host                       | Adicione `SERPAPI_KEY` em Render/Railway/Fly secrets |
| `HTTP 502 — Falha na busca`              | cota da SerpAPI excedida ou CAPTCHA           | Aguarde reset mensal ou faça upgrade de plano         |
| `cna_url: null`                          | Google não indexou a página CNA daquele nome | Tente variações do nome (com/sem preposições)          |
| `match_quality: no_jusbrasil_url`        | Não existe página JusBrasil canônica          | A pessoa pode não ter página JusBrasil ainda         |

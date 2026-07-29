# Buscador OAB → JusBrasil — v1.3 (multi-fonte)

Microsserviço FastAPI que recebe **UF + número da OAB** e devolve, em uma
requisição:

1. **URL JusBrasil** com a página de processos daquela pessoa (se localizável).
2. **OAB correta** confirmada (número + UF + status se ATIVA/SUSPENSA/...).
3. **Nome completo** do advogado conforme aparece no cadastro.

## O que mudou nesta versão

A versão anterior usava apenas o índice do Google com `site:cna.oab.org.br`.
Funciona quando o Google tem aquela página CNA indexada, mas falha quando
não tem. Esta v1.3:

- Roda **5 buscas Google em paralelo** com variações diferentes de query.
- Extrai nome, OAB, status de **qualquer resultado** (regex tolerante a
  formatos: "OAB/SP 123.456", "OAB n.º 123456", "OAB 123456").
- **Sempre** devolve links diretos de verificação manual em:
  - `cna.oab.org.br` (cadastro oficial com reCAPTCHA)
  - `confirmadv.oab.org.br` (consulta OAB direta)
  - `jusbrasil.com.br/advogados/<uf>-<numero>` (diretório JusBrasil por OAB)
  - Google search URLs (clica pra abrir)
- Funciona **mesmo sem SerpAPI** — cai num modo que mostra os links diretos.

## Variáveis de ambiente

| Variável      | Obrigatória | Descrição                                                                                  |
|---------------|-------------|--------------------------------------------------------------------------------------------|
| `SERPAPI_KEY` | opcional    | chave SerpAPI (grátis em serpapi.com). Sem ela o sistema mostra links diretos pra você validar. |
| `PORT`        | não         | Render/Railway/Fly setam automaticamente.                                                  |

## Estrutura

```
.
├── app.py                # servidor FastAPI
├── oab_search.py         # lógica multi-fonte
├── jusbrasil_search.py   # parser JusBrasil
├── index.html            # frontend com fluxos ordenados
├── requirements.txt
└── README.md
```

## Rodar local

```bash
pip install -r requirements.txt
# com SerpAPI (recomendado):
export SERPAPI_KEY=sua_chave_aqui
uvicorn app:app --reload --port 8000
# ou sem SerpAPI (modo manual):
uvicorn app:app --reload --port 8000
```

Abra `http://localhost:8000`.

## Hospedagem

### Render (recomendado)

1. Suba o ZIP no GitHub (descompactado).
2. Render → **New Web Service** → Connect repo.
3. **Build**: `pip install -r requirements.txt`
4. **Start**: `uvicorn app:app --host 0.0.0.0 --port $PORT`
5. **Env**: opcionalmente adicione `SERPAPI_KEY=<sua_chave>`. Sem ela o serviço ainda funciona — só mostra os links diretos.

### Fly.io

```bash
unzip buscador_oab_jusbrasil_v3.zip -d buscador && cd buscador
fly launch --name buscador-oab --no-deploy
# opcional:
# fly secrets set SERPAPI_KEY=sua_chave
fly deploy
```

### VPS Ubuntu + nginx + HTTPS

```bash
apt install -y python3-pip python3-venv nginx certbot python3-certbot-nginx
unzip buscador_oab_jusbrasil_v3.zip -d /opt/buscador
cd /opt/buscador && python3 -m venv venv
source venv/bin/activate && pip install -r requirements.txt

# /etc/systemd/system/buscador.service
cat > /etc/systemd/system/buscador.service << 'EOF'
[Unit]
Description=Buscador OAB FastAPI
After=network.target
[Service]
User=www-data
WorkingDirectory=/opt/buscador
ExecStart=/opt/buscador/venv/bin/uvicorn app:app --host 127.0.0.1 --port 8000
Restart=always
[Install]
WantedBy=multi-user.target
EOF

cat > /etc/nginx/sites-available/buscador << 'EOF'
server {
    server_name seu-dominio.com.br;
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $remote_addr;
    }
}
EOF

systemctl daemon-reload
systemctl enable --now buscador
ln -sf /etc/nginx/sites-available/buscador /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx
certbot --nginx -d seu-dominio.com.br
```

## Endpoints

### `GET /api/oab/processos?state=<UF>&number=<numero>` (principal)

```bash
curl "https://seu-host/api/oab/processos?state=SP&number=123456"
```

Resposta:
```json
{
  "modo": "processos_por_oab",
  "oab_inserida": "sp-123456",
  "oab_correta": { "numero": "123456", "uf": "SP", "status": "ATIVA" },
  "nome_completo": "Jamila Drielly Moura Oliveira",
  "jusbrasil_url": "https://www.jusbrasil.com.br/processos/nome/59940841/jamila-drielly-moura-oliveira",
  "total_processos": 475,
  "cna_url": "https://cna.oab.org.br/...",
  "audit_links": [
    { "title": "...", "url": "https://cna.oab.org.br/...", "description": "..." },
    { "title": "...", "url": "https://www.jusbrasil.com.br/...", "description": "..." }
  ],
  "google_queries_usadas": ["...", "...", "...", "...", "..."],
  "google_url_verificacao": ["https://www.google.com/search?q=..."],
  "urls_verificacao_manual": [
    { "label": "ConfirmADV (verificação pela OAB)", "url": "https://confirmadv.oab.org.br/?uf=SP&inscricao=123456" },
    { "label": "JusBrasil — advogados por OAB",        "url": "https://www.jusbrasil.com.br/advogados/sp-123456" },
    { "label": "CNA (cadastro nacional)",              "url": "https://cna.oab.org.br/" }
  ],
  "serpapi_used": true,
  "raw_results_count": 18
}
```

### `GET /api/oab/por-nome?name=<nome>` (secundário)

Útil quando você tem o nome e quer descobrir a OAB.

```bash
curl "https://seu-host/api/oab/por-nome?name=Jamila%20Drielly%20Moura%20Oliveira"
```

### `GET /healthz`

```json
{"status":"ok","serpapi_key_set":true,"note":"..."}
```

## Por que o CNA exige mais que scraping?

O site `cna.oab.org.br` é uma **SPA Angular com reCAPTCHA v3 invisível**.
Todas as requisições (tanto o carregamento de página quanto o POST do form)
validam um token recaptcha emitido pelo Google. Sem um navegador real que
atinja uma "score" suficiente no reCAPTCHA, a API retorna 403 / "recaptcha
token missing".

Por isso esta versão **não tenta raspar o CNA diretamente**, e em vez disso:
- Usa o índice do Google (que já rastreou o conteúdo das SPAs durante o
  ciclo normal de indexação).
- E sempre devolve links de verificação manual que você pode abrir em
  qualquer navegador.

Para **automatizar o CNA** (sem clicar manualmente), você precisaria de:
- **Anticaptcha / 2Captcha** (~USD 2-3 por 1000 tokens recaptcha), ou
- **Plano pago do Firecrawl** com `/interact` que roda um browser
  controlado, ou
- **Browserless host** com puppeteer.

## Limitações conhecidas

- A SerpAPI free tier dá apenas **~100 buscas/mês**. Esta v1.3 faz 5 buscas
  por consulta de OAB → ~20 OABs/dia no free tier.
- O JusBrasil também é uma SPA Next.js. O índice tem páginas estáticas
  (`/processos/nome/{id}/{slug}`), mas advogado específico via OAB pode ter
  variações.
- A regex de parsing é tolerante mas não perfeita — se o Google retornar
  resultados sem a OAB no formato esperado, exibimos "a verificar no CNA"
  em vez de inventar dados.

## Solução de problemas

| Sintoma                                                | Causa                                            | Como resolver                                                  |
|--------------------------------------------------------|--------------------------------------------------|----------------------------------------------------------------|
| `jusbrasil_url: null`                                  | OAB não tem página JusBrasil indexada            | Abra o link manual `jusbrasil.com.br/advogados/<uf>-<numero>`  |
| `nome_completo: null`                                  | Snippet sem nome claro                           | Busque manualmente em `cna.oab.org.br` ou `confirmadv.oab.org.br` |
| `⚠️ Modo sem SerpAPI` no topo                          | env var ausente                                  | Adicione `SERPAPI_KEY` no host                                 |
| `total_processos: null`                                | Google não mostrou o snippet "encontrou N processos" | Abra a URL JusBrasil e veja direto no site                     |

# Buscador OAB + JusBrasil

## Goal
Reúne três buscas jurídicas num único agente, todas servidas pelo **site do CNA**
(`https://cna.oab.org.br/`) e/ou pelo JusBrasil, conforme o usuário escolher no
formulário:
1. **Buscar OAB pelo nome** — recebe o nome completo de um advogado e devolve o
   número da inscrição OAB, a seccional (UF) e a URL canônica do CNA daquela
   pessoa.
2. **Buscar processos pela OAB** — recebe UF + número da OAB e devolve a página
   do CNA daquele advogado e links para seus processos públicos (JusBrasil /
   fontes indexadas pelo Google).
3. **Buscar processos JusBrasil pelo nome** — funcionalidade original do agente
   `buscador-jusbrasil`, mantida para compatibilidade.

## Inputs
- `tipo_busca` (select, obrigatório): define qual das três buscas rodar.
  - `oab_por_nome` — Busca OAB pelo nome
  - `processos_por_oab` — Busca processos pela OAB
  - `jusbrasil_por_nome` — Busca processos JusBrasil pelo nome
- `nome_advogado` (string, obrigatório quando `tipo_busca` ≠ `processos_por_oab`):
  Nome completo do advogado. Ex.: "Jamila Drielly Moura Oliveira".
- `oab_estado` (string, obrigatório quando `tipo_busca = processos_por_oab`):
  Sigla da seccional (UF). Ex.: "SP", "RJ", "MG".
- `oab_numero` (string, obrigatório quando `tipo_busca = processos_por_oab`):
  Número da inscrição OAB (somente dígitos ou com ponto/milhar). Ex.: "123456".
- `serpapi_key` (string, obrigatório): chave da SerpAPI
  (cadastro grátis em https://serpapi.com — ~100 buscas/mês no plano free).
  É obrigatória porque o CNA serve os resultados via JavaScript e raspagem
  direta seria frágil; usamos o índice do Google restrito a `site:cna.oab.org.br`.

## Procedure
1. Validar a entrada conforme o `tipo_busca` escolhido:
   - `oab_por_nome` ou `jusbrasil_por_nome`: exigir `nome_advogado` com ≥ 3 chars.
   - `processos_por_oab`: exigir `oab_estado` (2 letras) e `oab_numero` (≥ 4 dígitos).
2. Compor a query Google apropriada (com `site:cna.oab.org.br` e/ou filtro ao
   JusBrasil). Toda a lógica de parsing, regex e ranking está consolidada em
   `oab_search.py` (módulo Python puro).
3. Abrir o manifesto de arquivos do agente e localizar `oab_search.py`:
   - `cat /home/user/agent/app-files.json`
   - usar o valor do campo `path` da entrada cujo `name` é `oab_search.py`.
   NÃO escrever o caminho a partir do nome do arquivo — o ponto de montagem
   real está só no manifesto.
4. Executar o script passando os parâmetros:
   - Modo OAB por nome:
     `python3 <path> --mode name --name "<nome_advogado>" --api-key "<serpapi_key>"`
   - Modo processos por OAB:
     `python3 <path> --mode oab --state "<oab_estado>" --number "<oab_numero>" --api-key "<serpapi_key>"`
   - Modo JusBrasil por nome:
     `python3 <path> --mode jusbrasil-name --name "<nome_advogado>" --api-key "<serpapi_key>"`
5. Capturar o JSON impresso pelo script no stdout e apresentá-lo ao usuário em
   três blocos claros:
   - **Resumo** (campos-chave: `oab_number`, `oab_state`, `cna_url`,
     `jusbrasil_url`, etc.).
   - **Lista de links** (URL canônica do CNA, links de processos, link
     JusBrasil) — prontos para clicar.
   - **Query Google usada** (útil para auditoria).
6. Tratar erros com mensagem amigável:
   - Sem resultados → sugerir variações do nome ou da OAB.
   - `serpapi_key` ausente → lembrar que é obrigatória; o agente **não**
     raspá o CNA diretamente porque o site é uma SPA e bloqueia bots.
   - CAPTCHA / 429 da SerpAPI → orientar upgrade de plano.

## Output
Tabela/lista HTML renderizada com os campos extraídos pelo script:
- Para `oab_por_nome`: nome, OAB (nº/UF), status (ATIVA/SUSPENSA/...), URL CNA,
  3-5 links brutos do Google (auditoria).
- Para `processos_por_oab`: perfil do advogado no CNA + lista de links de
  processos (CNA + JusBrasil) + snippet de cada um.
- Para `jusbrasil_por_nome`: URL JusBrasil canônica
  (`/processos/nome/{id}/{slug}`), total de processos, qualidade do match.

Todos os links vêm com `target="_blank"` para abrir em nova aba.

## Notas técnicas
- O site do CNA (`https://cna.oab.org.br`) é uma SPA que renderiza via JS, então
  buscamos via Google indexado (SerpAPI) usando `site:cna.oab.org.br`. Isso
  garante que os snippets contenham nome + OAB + UF + status + URL.
- Regex principais (em `oab_search.py`):
  `OAB_FULL_PATTERN` — extrai `OAB/SP 123.456` de snippets;
  `STATUS_PATTERN` — extrai ATIVA / SUSPENSA / CANCELADA etc;
  `CNA_DETAIL_PATTERN` — reconhece URLs `cna.oab.org.br/*`.
- O módulo `jusbrasil_search.py` (presente no manifesto) é importado pelo
  `oab_search.py` quando o modo é `jusbrasil-name`, então **não remova** esse
  arquivo do pacote — ele é dependência obrigatória do modo JusBrasil.

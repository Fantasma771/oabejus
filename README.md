# Buscador OAB + JusBrasil

Agente persistente que reúne três buscas jurídicas em uma única interface:

1. **Buscar OAB pelo nome** — informa o nome do advogado, recebe o número OAB, a
   seccional (UF) e a URL canônica do CNA (https://cna.oab.org.br/).
2. **Buscar processos pela OAB** — informa UF + número OAB, recebe o perfil do
   advogado no CNA + links para processos públicos (JusBrasil e fontes indexadas).
3. **Buscar processos JusBrasil pelo nome** — funcionalidade original
   mantida para compatibilidade.

## Arquivos

| Arquivo                  | Função                                                                 |
|--------------------------|------------------------------------------------------------------------|
| `SKILL.md`               | Procedure do agente (Goal / Inputs / Procedure / Output)                |
| `oab_search.py`          | Lógica completa: regex, queries Google, parser de snippets, CLI       |
| `jusbrasil_search.py`    | Lógica do modo JusBrasil por nome (preservada do agente original)      |

## Como executar o script fora do agente

Defina sua chave SerpAPI:

```bash
export SERPAPI_KEY=sua_chave_aqui
```

Buscar OAB por nome:

```bash
python3 oab_search.py --mode name --name "Fulano de Tal"
```

Buscar processos pela OAB:

```bash
python3 oab_search.py --mode oab --state SP --number 123456
```

Buscar processos JusBrasil por nome:

```bash
python3 oab_search.py --mode jusbrasil-name --name "Fulano de Tal"
```

Todos os comandos emitem JSON estruturado no stdout.

## Por que SerpAPI e não raspagem direta do CNA?

O site https://cna.oab.org.br é uma SPA React/JavaScript que retorna os
resultados dinamicamente. Raspagem direta é frágil e bloqueia bots.
Usamos o índice do Google restrito a `site:cna.oab.org.br` — assim obtemos
nome + OAB + UF + status + URL canônica nos próprios snippets do Google,
sem precisar de navegador headless.

## Limites

A SerpAPI free tier oferece ~100 buscas/mês. Para volume maior, plano pago
(a partir de ~USD 50/mês por 5.000 buscas).

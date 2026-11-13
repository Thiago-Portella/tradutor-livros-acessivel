# Proposal 0001: Refatoração Modular e Correção Integral de Bugs

- **Status:** Accepted
- **Data:** 2026-11-13

## 1. Contexto e Problema (Por quê)
A base original era composta por 4 monolitos (`extractor.py` com 2.046 linhas, `book_translator.py` com 1.187 linhas, `epub_builder.py` com 1.131 linhas e `translator.py` com 417 linhas) sem suíte de testes automatizados e com bugs ativos em todas as camadas:
1. **Tradução e Rede:** Parágrafos longos ou em alfabetos não-ASCII estouravam o tamanho da URL GET; idioma detectado via `auto` era descartado deixando `lang="en"` errado no modo bilíngue; título original do livro era sobrescrito; contexto SSL global era desabilitado para todo o processo; cache SQLite não utilizava modo WAL.
2. **Extração:** Leitor EPUB baseado em regex falhava em tags aninhadas, ignorava `<div>` e deixava entidades HTML literais e URLs com `%20` sem decodificação; extrator Markdown destruía `#` legítimos com `lstrip`; `start_page`/`end_page` eram ignorados fora de PDF e sem validação; PDF descartava capítulos na página 2 em obras > 40 páginas e perdia capítulos que compartilhavam a mesma página no sumário embutido.
3. **Exportação e Pipeline:** Gravação do arquivo inteiro a cada ~20 parágrafos misturava texto traduzido e original e travava se aberto em outro leitor; temporários `.tmp_pdf_{pid}` colidiam; PDF quebrava fora da margem em URLs longas, não possuía fallback de fontes não-latinas e usava rótulos fixos em português.
4. **GUI e Executável:** `Testar Descoberta de Sumário` travava a thread principal e o NVDA; Aba 2 fixava `doc_lang="pt"`; colisões de mnemônicos `Alt+&`; fechamento abrupto de threads daemon; `TradutorLivros.exe` compilado com `console=False` quebrava em `--cli`/`--help` por `sys.stdout` ser `None`.

## 2. Condições de Sucesso
- **Decided:** Fatiar integralmente os 4 monolitos em módulos coesos em `src/` + fachadas compatíveis na raiz, garantindo que **100% dos arquivos `.py` de produção tenham <= 250 linhas físicas** e cabeçalho `# Role:`.
- **Decided:** Corrigir todos os bugs mapeados nas 4 camadas mantendo compatibilidade com as assinaturas públicas existentes e garantindo 100% de passagem em `tools/dev.py check`.
- **Decided:** Recompilar `TradutorLivros.exe` via `build --if-stale` e validar a acessibilidade da interface real com NVDA via `screen-readers-mcp`.

## 3. Não-Objetivos (Out of Scope)
- Alterar o motor de tradução para API paga com chave de usuário ou OCR de PDFs puramente escaneados.
- Redesenhar visualmente a interface além das correções de acessibilidade, responsividade e seleção de idioma na Aba 2.

## 4. Alternativas Rejeitadas (`Rejected`)
- **Rejected:** Manter os 4 monolitos originais em allowlist de legados — dificulta manutenção, testes isolados e viola a decisão de fatiamento integral.
- **Rejected:** Regravar o arquivo de saída inteiro a cada lote de 20 parágrafos — corrompe a leitura parcial com capítulos não traduzidos e gera `PermissionError` frequente.
- **Rejected:** Continuar usando regex para extrair XHTML de EPUBs — falha em estruturas HTML reais aninhadas e entidades.
- **Rejected:** Desativar `ssl._create_default_https_context` globalmente — compromete a segurança SSL de outras bibliotecas no mesmo processo.

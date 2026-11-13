# Tech Spec 0001: Arquitetura Modular, Papéis e Invariantes

## 1. Decisões Técnicas Congeladas
- **Decided:** Todo arquivo Python de produção (raiz, `src/` e `tools/`) deve ter no máximo **250 linhas físicas** e declarar `# Role: <papel>` nas primeiras 5 linhas.
- **Decided:** Fica proibido o uso de módulos genéricos (`utils.py`, `helpers.py`, `common.py`, `shared.py`, `misc.py`).
- **Decided:** A tradução grava progresso exclusivamente em `TranslationCacheDB` (SQLite WAL) durante os lotes; exporta o destino final apenas em 100% e gera `<nome>_parcial.<ext>` ao pausar.
- **Decided:** O fallback SSL permanece confinado ao `HTTPSHandler` do `opener` HTTP do cliente de tradução, nunca modificando `ssl._create_default_https_context` globalmente.
- **Decided:** A leitura de EPUB utiliza `html.parser.HTMLParser` da biblioteca padrão com `urllib.parse.unquote` e `html.unescape`.
- **Decided:** `TradutorLivros.exe` mantém `--windowed` com `AttachConsole(-1)` + proteção de `sys.stdout`/`sys.stderr` para suportar `--cli` e `--help` sem falha.

## 2. Mapa de Módulos e Papéis (`<= 250` linhas por arquivo)

| Arquivo | Papel (`Role`) | Responsabilidade Única | Colaboradores Permitidos |
| :--- | :--- | :--- | :--- |
| `src/domain/models.py` | `value` | Dataclasses e exceções do livro e opções | stdlib |
| `src/policies/i18n_labels.py` | `policy` | Catálogo `LANGUAGES` e rótulos localizados | `src/domain/models.py` |
| `src/policies/text_normalizer.py` | `policy` | Normalização Unicode, ligaturas, reflow e títulos | stdlib |
| `src/policies/sentence_splitter.py` | `policy` | Fatiamento por sentença e orçamento URL-encoded | stdlib |
| `src/policies/path_policy.py` | `policy` | Validação de páginas, `MAX_PATH`, `_parcial` e temporários | `src/domain/models.py` |
| `src/policies/pdf_heuristics.py` | `policy` | Regras de cabeçalho, rodapé, notas e subtítulos PDF | `src/policies/text_normalizer.py` |
| `src/policies/pdf_metadata_policy.py` | `policy` | Extração de metadados de capa e fonte base PDF | `src/policies/text_normalizer.py`, `pdf_heuristics.py` |
| `src/policies/pdf_chapter_layers_explicit.py` | `policy` | Camadas 1 e 2 de capítulos (marcadores e numerados) | `pdf_heuristics.py`, `text_normalizer.py` |
| `src/policies/pdf_chapter_discovery.py` | `policy` | Camadas 3 a 5 e detecção de sumário impresso | `pdf_chapter_layers_explicit.py`, `pdf_heuristics.py` |
| `src/adapters/pdf_page_units.py` | `adapter` | Conversão de blocos `pymupdf` em unidades e itens | `src/domain/models.py`, `pdf_heuristics.py` |
| `src/adapters/pdf_extractor.py` | `adapter` | Orquestração da extração de PDF e TOC embutido | `pdf_page_units.py`, `pdf_chapter_discovery.py`, `pdf_metadata_policy.py` |
| `src/adapters/epub_parser.py` | `adapter` | Parser estrutural `HTMLParser` para arquivos EPUB | `src/domain/models.py`, `text_normalizer.py`, `path_policy.py` |
| `src/adapters/text_md_parser.py` | `adapter` | Extração de `.txt` e `.md` com filtro de seções | `src/domain/models.py`, `text_normalizer.py`, `path_policy.py` |
| `src/adapters/sqlite_cache.py` | `adapter` | Cache SQLite em modo WAL thread-safe | `text_normalizer.py` |
| `src/adapters/google_translate_client.py` | `adapter` | Cliente HTTP `translate-pa` com SSL local e lotes | `models.py`, `sentence_splitter.py`, `sqlite_cache.py` |
| `src/adapters/atomic_file_writer.py` | `adapter` | Escrita atômica e erro acionável para arquivo travado | `models.py`, `path_policy.py` |
| `src/adapters/epub_exporter.py` | `adapter` | Geração de EPUB 3 acessível localizado | `models.py`, `i18n_labels.py`, `atomic_file_writer.py` |
| `src/adapters/html_exporter.py` | `adapter` | Geração de HTML5 acessível bilíngue/localizado | `models.py`, `i18n_labels.py`, `atomic_file_writer.py` |
| `src/adapters/md_txt_exporter.py` | `adapter` | Geração de Markdown e TXT estruturados | `models.py`, `i18n_labels.py`, `atomic_file_writer.py` |
| `src/adapters/pdf_fonts_layout.py` | `adapter` | Seleção de fontes Unicode, quebra de URLs e layout A4 | `models.py`, `i18n_labels.py` |
| `src/adapters/pdf_exporter.py` | `adapter` | Renderização PDF, `/Outlines`, `/Names` e gravação | `pdf_fonts_layout.py`, `atomic_file_writer.py` |
| `src/services/batch_translator.py` | `service` | Tradução em lotes com fatiamento por sentença e cache SQLite | `google_translate_client.py`, `sqlite_cache.py`, `sentence_splitter.py` |
| `src/services/book_io_dispatch.py` | `service` | Despacho unificado de extração e exportação multi-formato | `src/adapters/*` |
| `src/services/book_pipeline.py` | `service` | Pipelines `translate` e `enhance_only` | `batch_translator.py`, `book_io_dispatch.py`, `path_policy.py` |
| `src/controllers/gui_controls_builder.py` | `controller` | Construção de widgets `wx` com mnemônicos únicos | `models.py`, `i18n_labels.py` |
| `src/controllers/gui_tab_dialogs.py` | `controller` | Diálogos de arquivo, validação de intervalo e prévia de sumário | `models.py`, `path_policy.py` |
| `src/controllers/gui_workflow_tab.py` | `controller` | Painel de aba, preview assíncrono e worker thread | `gui_controls_builder.py`, `gui_tab_dialogs.py`, `book_pipeline.py` |
| `src/controllers/gui_frame.py` | `controller` | Janela principal `BookProcessorFrame` e `run_gui` | `gui_workflow_tab.py` |
| `extractor.py` | `service` | Fachada pública compatível de extração | `src/adapters/*`, `src/policies/*` |
| `translator.py` | `service` | Fachada pública compatível de tradução | `src/adapters/*`, `src/policies/*` |
| `epub_builder.py` | `service` | Fachada pública compatível de exportação | `src/adapters/*` |
| `book_translator.py` | `controller` | Entrada CLI, `AttachConsole` e dispatch para GUI | `src/services/*`, `src/controllers/*` |
| `tools/dev.py` | `controller` | CLI de verificação (`doctor`, `build`, `check`) | `tools/arch_checks.py` |
| `tools/arch_checks.py` | `policy` | Linters de governança (`Role`, 250 linhas, docs) | stdlib |

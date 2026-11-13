# Behaviour Spec 0001: Contratos Observáveis e Cenários de Aceitação

## Exemplo Concreto de Uso (Aprovado pelo Humano)
```python
from extractor import EnhancementOptions, extract_book
from book_translator import translate_book_pipeline, enhance_only_book_pipeline

opts = EnhancementOptions(
    normalize_chars=True,
    reflow_sentences=True,
    remove_headers_footers=True,
    organize_toc=True,
    footnote_mode="move_end",
    include_back_to_toc=False,
)
book = translate_book_pipeline(
    input_path="livro_espanhol.epub",
    output_path="saida/livro_pt.html",
    output_format="html",
    source_lang="auto",
    target_lang="pt",
    bilingual=True,
    options=opts,
    start_page=1,
    end_page=5,
)
assert book.original_title != ""
assert book.detected_source_lang == "es"

enhanced = enhance_only_book_pipeline(
    input_path="obra_em_ingles.pdf",
    output_path="saida/obra_limpa.epub",
    output_format="epub",
    doc_lang="en",
    options=opts,
)
```

## Cenários Observáveis (Casos Antes da Aceitação)

### Cenário 1: Exemplo Concreto e Propagação de Idioma Detectado
- **Dado (Given):** Um EPUB em espanhol e um PDF em inglês com cliente HTTP mockado retornando idioma detectado `"es"`.
- **Quando (When):** Executa-se literalmente o snippet do Exemplo Concreto de Uso.
- **Então (Then):** `book.original_title` preserva o título original distinto de `book.title` traduzido, `book.detected_source_lang == "es"`, o HTML bilíngue traz `lang="es"` nos blocos originais e `enhance_only_book_pipeline` gera EPUB com `dc:language` `"en"`.

### Cenário 2: Fatiamento de Parágrafos Longos e Não-ASCII na Tradução
- **Dado (Given):** Um parágrafo latino com > 4.500 caracteres e um parágrafo cirílico/CJK cuja codificação URL excede 12.000 bytes.
- **Quando (When):** `translate_paragraphs_batch` traduz ambos usando `google_translate`.
- **Então (Then):** Nenhuma requisição GET excede 3.600 caracteres ou 10.500 bytes codificados de payload, as fatias são divididas em fronteiras de sentenças, recombinadas 1:1 e salvas inteiras no cache SQLite.

### Cenário 3: SQLite em Modo WAL e Isolamento SSL Local
- **Dado (Given):** Inicialização de `TranslationCacheDB` e chamadas ao cliente `google_translate`.
- **Quando (When):** O cache SQLite é aberto e uma requisição é montada.
- **Então (Then):** `PRAGMA journal_mode` retorna `"wal"` e `ssl._create_default_https_context` global permanece inalterado (igual ao valor original do módulo `ssl`).

### Cenário 4: Salvamento em Progresso no SQLite e Arquivo `_parcial` na Pausa
- **Dado (Given):** Um livro com 2 capítulos onde `cancel_check()` retorna `True` após traduzir o 1º capítulo.
- **Quando (When):** `translate_book_pipeline` é executado com destino `saida/livro.epub`.
- **Então (Then):** Durante os lotes o arquivo `saida/livro.epub` não é criado nem sobrescrito; ao pausar é gerado `saida/livro_parcial.epub` contendo exclusivamente os capítulos/itens traduzidos. Ao rodar até 100%, `saida/livro.epub` completo é gravado.

### Cenário 5: Parser Estrutural de EPUB (`HTMLParser`)
- **Dado (Given):** Um EPUB com arquivo `OEBPS/Text/Cap%201.xhtml` no `content.opf`, contendo `<div>`, `<p>` aninhado, `&nbsp;`, `&mdash;`, `&#8217;`, `<script>` e `<style>`.
- **Quando (When):** `extract_epub_book` extrai o livro.
- **Então (Then):** O caminho `%20` é resolvido sem erro, entidades viram caracteres Unicode reais, conteúdo de `<script>`/`<style>` é descartado e textos de `<div>`/`<p>` são extraídos na ordem correta.

### Cenário 6: Extração Markdown/TXT e Validação Universal de Páginas/Seções
- **Dado (Given):** Um arquivo Markdown com título `# C# Avançado` e 4 capítulos, além de intervalo inválido `start_page=4, end_page=2`.
- **Quando (When):** `extract_book` é chamado com intervalo válido (`1..2`) e com intervalo inválido (`4..2`).
- **Então (Then):** O título preserva `C# Avançado` (não corta o `#` interno), o intervalo `1..2` filtra os 2 primeiros capítulos e `start_page > end_page` ou `< 1` lança `ValueError` claro.

### Cenário 7: Correções no Extrator de PDF (Página 2, Mesmo Page TOC e Reflow)
- **Dado (Given):** (A) PDF sintético de 45 páginas com capítulo legítimo na página 2; (B) PDF com Sumário Embutido (`doc.set_toc`) contendo 2 capítulos iniciando na mesma página 5; (C) frase cortada entre página 1 e página 2.
- **Quando (When):** `extract_pdf_book` processa esses PDFs.
- **Então (Then):** O capítulo da página 2 não é descartado, ambos os capítulos na mesma página são preservados sem sumir nem duplicar texto, e a frase dividida entre páginas é reunida.

### Cenário 8: Rótulos Localizados e Idioma Bilíngue na Exportação
- **Dado (Given):** Um `BookStructure` com `original_title="El Libro"`, `title="The Book"`, `detected_source_lang="es"`.
- **Quando (When):** Exportado para EPUB, HTML, Markdown, TXT e PDF com `target_lang="en"` e `bilingual=True`.
- **Então (Then):** Rótulos estruturais usam inglês (`Table of Contents`, `Author`, `Chapter`, `Back to Table of Contents`), título original aparece preservado e EPUB/HTML marcam blocos originais com `lang="es"`.

### Cenário 9: Tipografia Segura em PDF (URLs Longas, Fontes Unicode e `/Names`)
- **Dado (Given):** Um livro com título contendo parênteses `(Edição Especial)`, uma URL contínua de 180 caracteres sem espaço e um parágrafo em cirílico/chinês.
- **Quando (When):** `build_pdf` gera o arquivo PDF.
- **Então (Then):** Nenhum texto ultrapassa a margem direita A4, caracteres não-latinos são renderizados com fonte Unicode do sistema sem perda e a tabela `/Names` escapa parênteses corretamente sem erro ao abrir no PyMuPDF.

### Cenário 10: Arquivo de Saída Bloqueado por Outro Leitor
- **Dado (Given):** Falha simulada de `PermissionError` durante a troca atômica `os.replace`.
- **Quando (When):** `export_book` tenta salvar o PDF/EPUB.
- **Então (Then):** Lança `TranslationError` com mensagem acionável em português informando que o arquivo está aberto em outro programa e não deixa nenhum arquivo `.tmp_*` órfão no diretório.

### Cenário 11: Interface Gráfica Acessível (`wxPython`)
- **Dado (Given):** Instanciação real de `BookProcessorFrame` em uma `wx.App`.
- **Quando (When):** Inspecionam-se os controles e mnemônicos das duas abas e aciona-se a lógica de preview assíncrono e fechamento.
- **Então (Then):** Nenhuma aba tem letra aceleradora `Alt+&` duplicada, a Aba 2 possui seletor `Idioma do Livro`, `_on_preview_toc` executa em thread secundária sem travar o loop principal, `Esc` fecha quando ocioso e `Destroy()` encerra sem erro.

### Cenário 12: CLI e Executável Compilado (`TradutorLivros.exe`)
- **Dado (Given):** O binário compilado `dist/TradutorLivros/TradutorLivros.exe`.
- **Quando (When):** Executado em linha de comando com `--help` e com um arquivo `.md` usando `--cli --enhance-only --doc-lang pt -f epub`.
- **Então (Then):** Retorna código de saída `0`, gera o `.epub` válido sem abrir janela GUI travada e funciona mesmo com binário `--windowed`.

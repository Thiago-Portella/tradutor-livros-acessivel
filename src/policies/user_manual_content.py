# Role: policy
"""Gerador puro em HTML5 acessível do Manual Completo do Usuário (sem I/O)."""

from __future__ import annotations

import html

from src.domain.models import FOOTNOTE_MODES, SUPPORTED_FORMATS
from src.domain.version import APP_NAME, APP_VERSION, GITHUB_REPO

_MANUAL_CSS = """
  :root { color-scheme: light dark; --bg: #fdfdfd; --fg: #181a1b; --card: #ffffff;
    --border: #c9d1d9; --accent: #005fcc; --muted: #4b5563; --code-bg: #f3f4f6; }
  @media (prefers-color-scheme: dark) {
    :root { --bg: #111418; --fg: #f3f4f6; --card: #1a1f26; --border: #374151;
      --accent: #60a5fa; --muted: #9ca3af; --code-bg: #0d1117; }
  }
  body { font-family: "Segoe UI", system-ui, sans-serif; line-height: 1.7; max-width: 920px;
    margin: 0 auto; padding: 1.5rem 1.25rem 3rem; background: var(--bg); color: var(--fg); }
  .visually-hidden:where(:not(:focus-within, :active)) { position: absolute !important;
    clip-path: inset(50%) !important; overflow: hidden !important; width: 1px !important;
    height: 1px !important; margin: -1px !important; padding: 0 !important; border: 0 !important;
    white-space: nowrap !important; }
  .skip-link:focus { position: fixed; top: 0.75rem; left: 0.75rem; z-index: 999;
    padding: 0.65rem 1rem; background: var(--accent); color: #ffffff; font-weight: 700;
    border-radius: 6px; text-decoration: none; }
  :where(a:any-link, button, summary, pre[tabindex="0"], [tabindex="-1"]):focus-visible {
    outline: 3px solid var(--accent); outline-offset: 3px; }
  header, nav, section, footer { background: var(--card); border: 1px solid var(--border);
    border-radius: 8px; padding: 1.35rem 1.6rem; margin-bottom: 1.5rem; }
  h1 { font-size: 1.85rem; margin: 0 0 0.4rem; }
  h2 { font-size: 1.38rem; border-bottom: 1px solid var(--border); padding-bottom: 0.35rem; }
  h3 { font-size: 1.12rem; margin-top: 1.25rem; }
  table { width: 100%; border-collapse: collapse; margin: 0.9rem 0 1.2rem; }
  caption { text-align: left; font-weight: 700; margin-bottom: 0.45rem; }
  th, td { border: 1px solid var(--border); padding: 0.55rem 0.7rem; text-align: left; }
  thead th { background: var(--code-bg); }
  kbd, code { font-family: Consolas, "Courier New", monospace; background: var(--code-bg);
    padding: 0.12rem 0.35rem; border-radius: 4px; font-size: 0.94em; }
  pre { background: var(--code-bg); border: 1px solid var(--border); border-radius: 6px;
    padding: 0.9rem 1rem; overflow-x: auto; line-height: 1.5; }
  pre code { background: transparent; padding: 0; }
  figure { margin: 1rem 0; }
  figcaption { font-weight: 600; margin-bottom: 0.4rem; }
  details { border: 1px solid var(--border); border-radius: 6px; padding: 0.65rem 0.9rem;
    margin-bottom: 0.7rem; }
  summary { cursor: pointer; font-weight: 600; }
  .meta { color: var(--muted); font-size: 0.95rem; margin: 0; }
"""


def _table(caption: str, headers: tuple[str, ...], rows: list[tuple[str, ...]]) -> str:
    ths = "".join(f'<th scope="col">{html.escape(h)}</th>' for h in headers)
    trs: list[str] = []
    for row in rows:
        cells = [f'<th scope="row">{row[0]}</th>'] + [f"<td>{c}</td>" for c in row[1:]]
        trs.append("<tr>" + "".join(cells) + "</tr>")
    return (
        f"<table><caption>{html.escape(caption)}</caption><thead><tr>{ths}</tr></thead>"
        f"<tbody>{''.join(trs)}</tbody></table>"
    )


def _code_block(fig_id: str, caption: str, code_text: str) -> str:
    return (
        f'<figure><figcaption id="{fig_id}">{html.escape(caption)}</figcaption>'
        f'<pre role="region" aria-labelledby="{fig_id}" tabindex="0">'
        f"<code>{html.escape(code_text)}</code></pre></figure>"
    )


def _build_shortcuts_tables() -> str:
    app_rows = [
        ("<kbd>F1</kbd>", "Abre este Manual Completo do Usuário em HTML5 no navegador padrão."),
        ("<kbd>F5</kbd>", "Verifica imediatamente se há nova versão disponível no GitHub Releases."),
        ("<kbd>Esc</kbd>", "Fecha a janela quando nenhuma tradução/processamento estiver em andamento."),
        ("<kbd>Ctrl</kbd> + <kbd>Tab</kbd>", "Alterna entre a Aba 1 (Traduzir) e a Aba 2 (Aprimorar / Converter)."),
        ("<kbd>Alt</kbd> + <kbd>J</kbd>", "Abre o menu Ajuda na barra superior."),
        ("<kbd>Alt</kbd> + <kbd>A</kbd> / <kbd>L</kbd>", "Foca o campo Arquivo do livro ou aciona Procurar Livro."),
        ("<kbd>Alt</kbd> + <kbd>F</kbd>", "Seleciona o formato de saída (EPUB, PDF, HTML, Markdown ou TXT)."),
        ("<kbd>Alt</kbd> + <kbd>E</kbd> / <kbd>O</kbd>", "Edita o caminho de saída ou abre o diálogo Escolher Destino."),
        ("<kbd>Alt</kbd> + <kbd>R</kbd> / <kbd>D</kbd> / <kbd>B</kbd>", "Na Aba 1: Idioma de Origem, Destino e Modo Bilíngue."),
        ("<kbd>Alt</kbd> + <kbd>M</kbd>", "Na Aba 2: define o Idioma do Livro para metadados e leitor de tela."),
        ("<kbd>Alt</kbd> + <kbd>N</kbd>, <kbd>C</kbd>, <kbd>Ç</kbd>, <kbd>S</kbd>, <kbd>V</kbd>, <kbd>K</kbd>, <kbd>U</kbd>, <kbd>T</kbd>",
         "Alterna normalização, reconstrução de frases, cabeçalhos, sumário, algoritmo visual, link voltar, bipes e notas."),
        ("<kbd>Alt</kbd> + <kbd>1</kbd> / <kbd>Z</kbd> / <kbd>W</kbd>", "Define página inicial, página final e testa descoberta de sumário."),
        ("<kbd>Alt</kbd> + <kbd>H</kbd>", "Foca a caixa Histórico, sumário detectado e prévia em tempo real."),
        ("<kbd>Alt</kbd> + <kbd>I</kbd> / <kbd>P</kbd> / <kbd>G</kbd> / <kbd>X</kbd>",
         "Inicia ou retoma, pausa salvando parcial, abre pasta de saída ou fecha o programa."),
    ]
    nvda_rows = [
        ("<kbd>H</kbd> / <kbd>Shift</kbd> + <kbd>H</kbd>", "Salta entre os títulos e seções deste manual."),
        ("<kbd>1</kbd>, <kbd>2</kbd>, <kbd>3</kbd>", "Navega diretamente por níveis de título (Principal, Seções, Subtópicos)."),
        ("<kbd>D</kbd>", "Alterna entre regiões semânticas (Cabeçalho, Sumário, Conteúdo Principal, Rodapé)."),
        ("<kbd>T</kbd>", "Vai diretamente para as tabelas de atalhos, formatos e sinais sonoros."),
        ("<kbd>K</kbd> ou <kbd>Tab</kbd>", "Percorre rapidamente os links do Sumário e os blocos expansíveis."),
    ]
    return (
        _table("Atalhos de teclado e mnemônicos da interface do programa", ("Atalho", "Função"), app_rows)
        + _table("Comandos recomendados do NVDA para ler este manual no navegador", ("Tecla no NVDA", "Ação de navegação"), nvda_rows)
    )


def _build_formats_and_options() -> str:
    fmt_rows = [
        ("<code>.epub</code>", "Entrada e Saída", "EPUB 3 semântico com sumário hierárquico, metadados de idioma e notas linkadas."),
        ("<code>.pdf</code>", "Entrada e Saída", "Entrada extrai texto/TOC; saída gera A4 com fontes Unicode, marcadores e quebra segura de URLs."),
        ("<code>.html</code>", "Saída", "Página única HTML5 acessível com landmarks, <code>lang</code> real e estilo claro para leitura."),
        ("<code>.md</code>", "Entrada e Saída", "Markdown estruturado com títulos e âncoras preservando <code>#</code> legítimos no texto."),
        ("<code>.txt</code>", "Entrada e Saída", "Texto puro organizado com sumário textual e marcadores de capítulos."),
    ]
    fn_items = "".join(f"<li><code>{html.escape(k)}</code>: {html.escape(v)}</li>" for k, v in FOOTNOTE_MODES.items())
    sec_fmt = (
        '<section id="sec-formatos"><h2>4. Formatos de Entrada e Saída</h2>'
        f"<p>O programa suporta {len(SUPPORTED_FORMATS)} formatos finais de exportação acessíveis.</p>"
        + _table("Matriz de compatibilidade de formatos", ("Extensão", "Papel", "Características principais"), fmt_rows)
        + "</section>"
    )
    sec_enh = (
        '<section id="sec-aprimoramento"><h2>5. Aprimoramento, Sumário e Notas de Rodapé</h2>'
        "<ul>"
        "<li><strong>Normalização tipográfica:</strong> corrige ligaturas (<code>ﬁ</code>, <code>ﬀ</code>), hifens invisíveis e espaços múltiplos.</li>"
        "<li><strong>Reconstrução de frases:</strong> une linhas e sentenças quebradas entre páginas sem cortar parágrafos válidos.</li>"
        "<li><strong>Remoção de cabeçalhos e rodapés:</strong> limpa numeração de página solta e títulos repetidos em cada folha.</li>"
        "<li><strong>Descoberta de sumário:</strong> lê o sumário embutido do PDF/EPUB ou usa algoritmo visual tipográfico (<code>Testar Descoberta de Sumário</code>).</li>"
        "<li><strong>Link Voltar ao Sumário e Intervalo de Páginas:</strong> permite traduzir trechos específicos (ex.: páginas 10 a 25) e voltar facilmente ao índice.</li>"
        "</ul><h3>Modos de notas de rodapé disponíveis</h3><ul>" + fn_items + "</ul></section>"
    )
    return sec_fmt + sec_enh


def _build_cache_cli_update_faq() -> str:
    beep_rows = [
        ("520 Hz (curto)", "Início de um novo capítulo durante a tradução."),
        ("660 Hz seguido de 880 Hz", "Processamento concluído com 100% de sucesso."),
        ("300 Hz (médio)", "Pausa concluída com segurança e arquivo <code>_parcial</code> salvo."),
        ("220 Hz (grave)", "Aviso de limite temporário da API ou erro de processamento."),
    ]
    cli_sample = (
        "# Traduzir um EPUB para HTML bilíngue em Português\n"
        "TradutorLivros.exe livro.epub --cli -f html -s auto -t pt -b\n\n"
        "# Apenas aprimorar PDF do inglês entre páginas 1 e 40 gerando EPUB\n"
        "TradutorLivros.exe obra.pdf --cli --enhance-only --doc-lang en -f epub --start-page 1 --end-page 40\n\n"
        "# Abrir o manual no navegador ou verificar atualizações\n"
        "TradutorLivros.exe --help-manual\n"
        "TradutorLivros.exe --check-update"
    )
    cli_rows = [
        ("<code>--cli</code>", "Executa no terminal sem abrir a janela gráfica."),
        ("<code>--enhance-only</code>", "Ativa o modo da Aba 2 (limpa, organiza e converte sem traduzir)."),
        ("<code>-f / --format</code>", "Define a saída: <code>epub</code>, <code>pdf</code>, <code>html</code>, <code>md</code> ou <code>txt</code>."),
        ("<code>-s</code> / <code>-t</code> / <code>--doc-lang</code>", "Idioma de origem, idioma de destino e idioma do livro no modo sem tradução."),
        ("<code>-b / --bilingual</code>", "Exibe o parágrafo original acima do traduzido mantendo o <code>lang</code> original."),
        ("<code>--start-page</code> / <code>--end-page</code>", "Restringe o processamento a um intervalo de páginas ou capítulos (base 1)."),
        ("<code>--footnotes</code> / <code>--back-to-toc</code>", "Controla notas (<code>move_end</code>, <code>remove</code>, <code>keep</code>) e link de retorno."),
        ("<code>--help-manual</code>, <code>--version</code>, <code>--check-update</code>, <code>--apply-update</code>", "Abre este manual HTML, exibe a versão, consulta ou aplica atualização no executável."),
    ]
    sec_cache = (
        '<section id="sec-cache-som"><h2>6. Cache SQLite WAL, Pausa Segura e Sinais Sonoros</h2>'
        "<p>Cada bloco traduzido é gravado imediatamente em banco SQLite WAL local (em <code>~/.tradutor_livros_cache</code>). "
        "Ao clicar em <strong>Pausar</strong> (ou sofrer limite temporário HTTP 429), o programa finaliza o lote atual, gera "
        "<code>&lt;nome&gt;_parcial.&lt;ext&gt;</code> e preserva tudo o que já foi traduzido. Na próxima execução com o mesmo arquivo e idioma, "
        "os trechos em cache são reaproveitados automaticamente sem custo de rede.</p>"
        + _table("Referência dos bipes sonoros discretos", ("Sinal sonoro", "Significado operacional"), beep_rows)
        + "</section>"
    )
    sec_cli = (
        '<section id="sec-cli"><h2>7. Linha de Comando (CLI)</h2>'
        + _code_block("cli-exemplos", "Exemplos práticos de comandos CLI para automação e leitura rápida", cli_sample)
        + _table("Principais opções de linha de comando", ("Parâmetro", "Efeito"), cli_rows)
        + "</section>"
    )
    sec_upd = (
        '<section id="sec-atualizacao"><h2>8. Atualizador Interno (F5) e Segurança</h2>'
        "<p>O aplicativo verifica silenciosamente na abertura (sem interromper leitores de tela caso você esteja offline) ou sob demanda "
        "pela tecla <kbd>F5</kbd> no menu <strong>Ajuda</strong> se existe nova versão no GitHub Releases. Todo pacote baixado é validado "
        "por hash criptográfico <code>SHA-256</code> e proteção contra extração fora da pasta antes de substituir o executável mantendo seus arquivos pessoais intactos.</p></section>"
    )
    sec_faq = (
        '<section id="sec-faq"><h2>9. Perguntas Frequentes e Solução de Problemas</h2>'
        "<details name=\"faq\"><summary>PDF escaneado sem camada de texto selecionável</summary>"
        "<p>Se o PDF for composto apenas por imagens digitalizadas, o botão <em>Testar Descoberta de Sumário</em> avisará que não há texto. Execute um processo de OCR antes de traduzi-lo.</p></details>"
        "<details name=\"faq\"><summary>Erro de arquivo aberto em outro programa ao salvar</summary>"
        "<p>Feche o arquivo PDF/EPUB de destino em leitores externos (como Adobe Reader ou Calibre) e clique em Iniciar novamente; o cache SQLite preservará seu progresso.</p></details>"
        "<details name=\"faq\"><summary>Pausa por limite temporário de requisições (HTTP 429)</summary>"
        "<p>Aguarde alguns minutos e clique novamente em Iniciar / Retomar Tradução. Todos os parágrafos já concluídos serão carregados do cache local em segundos.</p></details>"
        "</section>"
    )
    return sec_cache + sec_cli + sec_upd + sec_faq


def render_user_manual_html(
    app_name: str = APP_NAME,
    app_version: str = APP_VERSION,
    github_repo: str = GITHUB_REPO,
) -> str:
    """Renderiza o Manual Completo do Usuário em HTML5 semântico e acessível."""
    esc_name = html.escape(app_name)
    esc_ver = html.escape(app_version)
    esc_repo = html.escape(github_repo)
    toc = [
        ("sec-visao-geral", "1. Visão Geral e Fluxo Rápido em 5 Passos"),
        ("sec-abas", "2. Guia Completo das Duas Abas"),
        ("sec-atalhos", "3. Atalhos de Teclado e Navegação com NVDA"),
        ("sec-formatos", "4. Formatos de Entrada e Saída"),
        ("sec-aprimoramento", "5. Aprimoramento, Sumário e Notas de Rodapé"),
        ("sec-cache-som", "6. Cache SQLite WAL, Pausa Segura e Sinais Sonoros"),
        ("sec-cli", "7. Linha de Comando (CLI)"),
        ("sec-atualizacao", "8. Atualizador Interno (F5) e Segurança"),
        ("sec-faq", "9. Perguntas Frequentes e Solução de Problemas"),
    ]
    nav_items = "".join(f'<li><a href="#{sec_id}">{html.escape(label)}</a></li>' for sec_id, label in toc)
    sec1 = (
        '<section id="sec-visao-geral"><h2>1. Visão Geral e Fluxo Rápido em 5 Passos</h2>'
        f"<p>O <strong>{esc_name}</strong> transforma livros em PDF, EPUB, TXT e Markdown em edições acessíveis para leitura visual e leitores de tela.</p>"
        "<ol><li>Escolha a aba desejada: <strong>1. Traduzir Livro</strong> ou <strong>2. Apenas Aprimorar / Converter Livro</strong>.</li>"
        "<li>Use <strong>Procurar Livro</strong> (<kbd>Alt+L</kbd>) para selecionar o arquivo de origem.</li>"
        "<li>Defina o <strong>Formato de saída</strong> (<kbd>Alt+F</kbd>) e ajuste os idiomas ou o <strong>Idioma do Livro</strong>.</li>"
        "<li>Opcionalmente, clique em <strong>Testar Descoberta de Sumário</strong> (<kbd>Alt+W</kbd>) para conferir os capítulos antes de processar.</li>"
        "<li>Pressione <strong>Iniciar</strong> (<kbd>Alt+I</kbd>) e acompanhe o progresso por voz, histórico ou bipes sonoros.</li></ol></section>"
    )
    sec2 = (
        '<section id="sec-abas"><h2>2. Guia Completo das Duas Abas</h2>'
        "<h3>Aba 1: Traduzir Livro</h3>"
        "<p>Traduz o livro mantendo capítulos, títulos, listas e notas de rodapé. Permite escolher idioma de origem (incluindo detecção automática) "
        "e ativar o <strong>Modo Bilíngue</strong> (<kbd>Alt+B</kbd>), que exibe cada parágrafo original marcado com seu atributo <code>lang</code> real acima da tradução.</p>"
        "<h3>Aba 2: Apenas Aprimorar / Converter Livro</h3>"
        "<p>Corrige tipografia, reconstrói frases quebradas, limpa cabeçalhos repetitivos e converte formatos sem traduzir. "
        "O seletor <strong>Idioma do Livro</strong> (<kbd>Alt+M</kbd>) grava o idioma correto no EPUB e HTML para que o NVDA leia com a pronúncia exata.</p></section>"
    )
    sec3 = '<section id="sec-atalhos"><h2>3. Atalhos de Teclado e Navegação com NVDA</h2>' + _build_shortcuts_tables() + "</section>"
    body = sec1 + sec2 + sec3 + _build_formats_and_options() + _build_cache_cli_update_faq()
    return (
        f'<!DOCTYPE html>\n<html lang="pt-BR">\n<head>\n  <meta charset="utf-8" />\n'
        f'  <meta name="viewport" content="width=device-width, initial-scale=1.0" />\n'
        f'  <title>Manual do Usuário | {esc_name} v{esc_ver}</title>\n  <style>{_MANUAL_CSS}  </style>\n</head>\n'
        f'<body>\n  <a href="#conteudo-principal" class="skip-link visually-hidden">Pular para o conteúdo principal</a>\n'
        f'  <header>\n    <h1 id="conteudo-principal" tabindex="-1">Manual do Usuário — {esc_name} (v{esc_ver})</h1>\n'
        f'    <p class="meta">Documentação completa e acessível offline (pressione <kbd>F1</kbd> no programa para abrir a qualquer momento).</p>\n'
        f'  </header>\n  <nav id="sumario-manual" aria-label="Sumário do Manual">\n    <h2>Sumário do Manual</h2>\n'
        f'    <ol>{nav_items}</ol>\n  </nav>\n  <main>\n    {body}\n  </main>\n'
        f'  <footer>\n    <p>{esc_name} v{esc_ver} — Repositório oficial: <code>https://github.com/{esc_repo}</code></p>\n'
        f'    <p><a href="#sumario-manual">Voltar ao Sumário do Manual</a></p>\n  </footer>\n</body>\n</html>\n'
    )

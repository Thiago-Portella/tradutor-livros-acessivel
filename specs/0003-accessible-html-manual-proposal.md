# Proposal 0003: Manual Completo do Usuário em HTML5 Acessível (`F1`)

- **Status:** Accepted
- **Data:** 2026-11-14

## 1. Contexto e Problema (Por quê)
O menu `&Ajuda` do programa oferece atualmente apenas a checagem de atualizações (`F5`) e uma caixa de diálogo breve (`Sobre o Tradutor de Livros...`). Usuários finais — especialmente leitores cegos ou com baixa visão utilizando leitores de tela como o NVDA — não dispõem de documentação completa dentro do aplicativo explicando as duas abas, os 22 mnemônicos `Alt+Letra`, as opções granulares de aprimoramento, os algoritmos de descoberta de sumário, os sinais sonoros, a retomada via SQLite WAL, a linha de comando (CLI) e a solução de problemas comuns.

## 2. Condições de Sucesso
- **Decided:** Pressionar `F1` em qualquer controle da janela principal (`BookProcessorFrame`), selecionar `"&Manual do Usuário (HTML)...\tF1"` no menu `A&juda` ou executar `--help-manual` na CLI deve gerar/atualizar o manual completo em HTML5 e abri-lo imediatamente no navegador padrão do usuário via URI `file:///`.
- **Decided:** O manual em HTML5 deve ser 100% autônomo (offline, sem recursos externos, CSS embutido) e gerado programaticamente a partir das constantes canônicas do código (`APP_NAME`, `APP_VERSION`, `GITHUB_REPO`, `SUPPORTED_FORMATS`, `FOOTNOTE_MODES`), funcionando tanto no código-fonte quanto no executável empacotado `--onedir`.
- **Decided:** O HTML5 deve atender estritamente às boas práticas modernas de acessibilidade (`accessibility` e `html`): `lang="pt-BR"`, skip-link funcional, landmarks únicos (`<header>`, `<nav>`, `<main>`, `<footer>`), um único `<h1>` com hierarquia contínua `<h1>` -> `<h2>` -> `<h3>`, tabelas com `<caption>` e `<th scope>`, blocos de código CLI com `<figure>`/`<figcaption>` e `<pre role="region" tabindex="0"><code>`, e `<details>`/`<summary>` sem cabeçalhos internos no FAQ.
- **Decided:** Todos os módulos novos ou alterados devem manter o cabeçalho `# Role:` nas 5 primeiras linhas, o teto estrito de `<= 250` linhas físicas, zero colisões de mnemônicos `Alt` e aprovação integral em `tools/dev.py check`.

## 3. Não-Objetivos (Out of Scope)
- Hospedar site externo de documentação ou exigir conexão à internet para leitura do manual.
- Substituir o navegador padrão por um renderizador HTML interno limitado dentro do `wxPython`.
- Traduzir automaticamente o manual para múltiplos idiomas nesta entrega (idioma primário: `pt-BR`).

## 4. Alternativas Rejeitadas (`Rejected`)
- **Rejected:** Exibir o manual dentro de um `wx.html.HtmlWindow` do wxPython — não suporta CSS moderno, landmarks ARIA, skip-links nem o modo de navegação virtual completo do NVDA nos navegadores padrão.
- **Rejected:** Abrir página remota do GitHub ao pressionar `F1` — falha em ambientes offline e impede leitura local imediata.
- **Rejected:** Manter um arquivo `.html` estático solto sem gerador Python — corre risco de dessincronizar da versão `APP_VERSION` e falhar quando o executável é iniciado de outro diretório de trabalho.

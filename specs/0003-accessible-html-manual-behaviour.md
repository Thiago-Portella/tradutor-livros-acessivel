# Behaviour Spec 0003: Contratos Observáveis do Manual HTML5 (`F1`)

## Exemplo Concreto de Uso (Aprovado pelo Humano)

```python
from src.services.help_manual_service import generate_user_manual_html, open_user_manual

# 1. Geração determinística do manual HTML5 completo em disco
manual_path = generate_user_manual_html("saida/manual_usuario.html")

# 2. Abertura direta no navegador padrão do usuário (acionada por F1, menu Ajuda ou --help-manual)
opened_path = open_user_manual(output_path=manual_path, browser_opener=lambda url: True)
assert opened_path == manual_path
```

### Linha de Comando (CLI)
```powershell
python book_translator.py --help-manual
# Manual do usuário gerado e aberto no navegador: C:\Users\...\.tradutor_livros_cache\manual_usuario.html
```

## Cenários Observáveis (Casos Antes da Aceitação)

### Cenário 1: Geração Determinística e Estrutura HTML5 Semântica Acessível
- **Dado (Given):** Invocação de `generate_user_manual_html` para um caminho temporário.
- **Quando (When):** O arquivo HTML5 gerado é analisado estruturalmente por `HTMLParser`.
- **Então (Then):** Contém `<!DOCTYPE html>`, `<html lang="pt-BR">`, `<title>` não vazio com nome e versão do app, skip-link apontando para `<h1 id="conteudo-principal" tabindex="-1">`, exatamente um `<header>`, um `<nav aria-label="Sumário do Manual">`, um `<main>`, um `<footer>`, apenas um `<h1>`, sequência de cabeçalhos sem níveis pulados, todas as tabelas com `<caption>` e `<th scope>`, blocos `<pre role="region" tabindex="0"><code>` e zero tags `<h1..h6>` dentro de `<summary>`.

### Cenário 2: Cobertura Integral do Programa no Manual
- **Dado (Given):** O conteúdo HTML5 produzido por `render_user_manual_html()`.
- **Quando (When):** Inspecionam-se as 9 seções do documento.
- **Então (Then):** Estão documentados: fluxo rápido em 5 passos, Abas 1 e 2, mnemônicos `Alt+Letra` e atalhos (`F1`, `F5`, `Esc`, `Ctrl+Tab`), formatos de entrada/saída, opções de aprimoramento e notas de rodapé (`move_end`, `remove`, `keep`), cache SQLite WAL e `_parcial`, frequências de bipes sonoros (`520 Hz`, `660 Hz`, `880 Hz`, `300 Hz`, `220 Hz`), flags CLI (`--cli`, `--enhance-only`, `--help-manual`, `--check-update`, `--apply-update`), atualizador interno (`F5`) e solução de problemas comuns.

### Cenário 3: Abertura Direta no Navegador com URI `file:///`
- **Dado (Given):** Um caminho de saída válido e um callback `browser_opener` espião.
- **Quando (When):** Executa-se `open_user_manual(output_path=..., browser_opener=...)`.
- **Então (Then):** O arquivo HTML5 é gravado atomicamente no disco e `browser_opener` recebe exatamente uma URI iniciada por `file:///` apontando para o arquivo criado, retornando o caminho absoluto do arquivo.

### Cenário 4: Acionamento por `F1` e Menu `A&juda` na GUI Sem Colisão de Mnemônicos
- **Dado (Given):** Uma instância de `BookProcessorFrame` em uma `wx.App`.
- **Quando (When):** Inspeciona-se o menu `A&juda` e dispara-se `F1` via `_on_char_hook`.
- **Então (Then):** O menu `A&juda` contém `"&Manual do Usuário (HTML)...\tF1"` sem colidir com nenhum mnemônico `Alt` das duas abas, o diálogo Sobre referencia `F1` e pressionar `F1` invoca `open_help_manual_from_gui(frame)`.

### Cenário 5: Acionamento pela Flag CLI `--help-manual`
- **Dado (Given):** Execução do ponto de entrada `book_translator.main()` com argumento `--help-manual`.
- **Quando (When):** A CLI processa a flag.
- **Então (Then):** Chama `open_user_manual()`, imprime `"Manual do usuário gerado e aberto no navegador:"` em `stdout` e encerra com código de saída `0`.

### Cenário 6: Tratamento Resiliente de Erro na GUI
- **Dado (Given):** Falha simulada ao gerar ou abrir o manual quando o usuário aciona ajuda na interface gráfica.
- **Quando (When):** Chama-se `open_help_manual_from_gui(frame)`.
- **Então (Then):** Captura a exceção, exibe `wx.MessageBox` com ícone de erro e mensagem clara em português sem encerrar nem travar a aplicação, retornando `None`.

# Diretrizes de Engenharia — Tradutor e Aprimorador Acessível de Livros

Este projeto segue os invariantes do sistema de engenharia em loop fechado.

## 1. Regras Arquiteturais Obrigatórias (`tools/dev.py check`)
1. **Cabeçalho de Papel (`Role:`):** Todo arquivo Python (`.py`) na raiz, em `src/`, `tools/` e `tests/` deve declarar nas primeiras 5 linhas um único papel válido:
   `# Role: entity | value | policy | port | adapter | service | controller`
2. **Teto Estrito de 250 linhas:** Nenhum arquivo `.py` de produção (raiz, `src/`, `tools/`) pode exceder **250 linhas físicas**. Divida responsabilidades em módulos coesos antes de atingir o limite.
3. **Proibição de Gavetas Semânticas (`utils` / `helpers`):** É proibido criar módulos nomeados `utils.py`, `helpers.py`, `common.py`, `shared.py` ou `misc.py`.
4. **Pedágio `**Decided**`:** Decisões congeladas em `specs/` e `docs/ARCHITECTURE.md` são vinculantes e não podem ser contornadas silenciosamente.
5. **Higiene de Comentários:** Comentários devem explicar apenas o *porquê* atual de uma restrição ou invariante técnico. Comentários de histórico de diff/PR são proibidos.
6. **Arquitetura Viva (`docs/ARCHITECTURE.md`):** Deve conter diagrama Mermaid acompanhado de lista numerada textual acessível para leitores de tela (NVDA) e tabela `"Onde vive"` 100% sincronizada com os módulos em disco.

## 2. Instrumento de Voo Único
- Utilize sempre `C:\Python314\python.exe tools/dev.py check` como gate único antes de concluir qualquer entrega.
- O comando executa em sequência: `doctor`, validação de cabeçalhos `Role:`, limite de `250 linhas`, proibição de `utils`, sincronia de `docs/ARCHITECTURE.md`, recompilação `--if-stale` do executável `TradutorLivros.exe` e 100% da suíte `tests/` (incluindo `test_manual_sync`).

## 3. Higiene de Testes GUI (`wxPython`) e Manual Acessível (`F1`)
1. **Teardown Determinístico de `wx.App` (`gc.collect()`):** Todo teste que instanciar `wx.App` e `wx.Frame` deve executar obrigatoriamente no bloco `finally:` a sequência abaixo, evitando que o destrutor C++ tardio do `wxPyApp` restaure `sys.stdout` no meio de blocos `redirect_stdout()` de testes subsequentes:
   ```python
   frame.Destroy()
   wx.YieldIfNeeded()
   app.ExitMainLoop()
   del frame, app
   gc.collect()
   ```
2. **Padrão de Manual do Usuário em HTML5 (`F1`):** Manuais do usuário (`F1` / `--help-manual`) devem separar a geração HTML5/CSS pura sem I/O (`# Role: policy`) da gravação atômica e abertura via `Path(...).resolve().as_uri()` no navegador padrão (`# Role: service`), garantindo funcionamento offline idêntico em código-fonte e no executável `--onedir`, com validação estrutural via `HTMLParser` (landmarks únicos, skip-link funcional, tabelas com `<caption>`/`<th scope>`, blocos `<pre role="region" tabindex="0"><code>` ligados a `<figcaption id>` e zero cabeçalhos dentro de `<summary>`).

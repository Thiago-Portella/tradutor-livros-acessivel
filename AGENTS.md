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

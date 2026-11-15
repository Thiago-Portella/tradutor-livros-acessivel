# Tech Spec 0003: Desenho Interno do Manual HTML5 Acessível (`F1`)

## 1. Decisões Técnicas Congeladas
- **Decided:** Todo o conteúdo HTML5/CSS do manual é construído por função pura sem I/O em `src/policies/user_manual_content.py` (`# Role: policy`), permitindo testes determinísticos rápidos e zero risco de arquivo estático ausente no pacote PyInstaller.
- **Decided:** A geração atômica em disco e a abertura no navegador padrão residem em `src/services/help_manual_service.py` (`# Role: service`), reutilizando `write_atomically` e salvando em `~/.tradutor_livros_cache/manual_usuario.html` quando `output_path` for `None`.
- **Decided:** `src/controllers/gui_update_dialog.py` adiciona o item `&Manual do Usuário (HTML)...\tF1` ao menu `A&juda` (usando mnemônico `&M` livre no menu, pois `A&juda` já usa `J`, `&Verificar` usa `V` e `&Sobre` usa `S`) e `src/controllers/gui_frame.py` adiciona captura global de `wx.WXK_F1` em `_on_char_hook` para garantir resposta imediata de qualquer controle em foco.
- **Decided:** Todos os arquivos `.py` novos e modificados mantêm `# Role:` nas 5 primeiras linhas, `<= 250` linhas físicas e zero comentários arqueológicos de PR/diff.

## 2. Mapa de Módulos e Papéis (`<= 250` linhas por arquivo)

| Arquivo | Papel (`Role`) | Responsabilidade Única | Colaboradores Permitidos |
| :--- | :--- | :--- | :--- |
| `src/policies/user_manual_content.py` | `policy` | Renderiza HTML5/CSS semântico e acessível do manual completo | `src/domain/version.py`, `src/domain/models.py` |
| `src/services/help_manual_service.py` | `service` | Grava `manual_usuario.html` atomicamente e abre `file:///` no navegador | `user_manual_content.py`, `atomic_file_writer.py` |
| `src/controllers/gui_update_dialog.py` | `controller` | Menu `A&juda` com item `F1`, função `open_help_manual_from_gui` e diálogo Sobre | `help_manual_service.py`, `self_update_service.py` |
| `src/controllers/gui_frame.py` | `controller` | Atalho global `wx.WXK_F1` e `Esc` no `_on_char_hook` | `gui_update_dialog.py`, `gui_workflow_tab.py` |
| `book_translator.py` | `controller` | Flag CLI `--help-manual` e despacho principal | `help_manual_service.py`, `gui_frame.py`, `book_pipeline.py` |

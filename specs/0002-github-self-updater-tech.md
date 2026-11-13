# Tech Spec 0002: Arquitetura do Atualizador e Workflows GitHub

## 1. Decisões Técnicas Congeladas
- **Decided:** Todos os novos módulos de produção declaram `# Role:` nas 5 primeiras linhas e respeitam limite estrito de `<= 250` linhas físicas sem nomes `utils`/`helpers`.
- **Decided:** Cliente HTTP do atualizador (`github_release_client.py`) utiliza apenas `urllib` da biblioteca padrão com verificação TLS padrão ativa, `User-Agent` explícito, leitura em blocos de 64 KB e cálculo incremental de `hashlib.sha256`.
- **Decided:** Substituição no Windows (`windows_swap_installer.py`) extrai para pasta temporária após `validate_zip_member_paths` e dispara script `.cmd` destacado em `%TEMP%` usando `robocopy` sem `/PURGE` na raiz da instalação (preservando arquivos criados pelo usuário) e `/MIR` apenas na subpasta `_internal` quando presente.
- **Decided:** `TradutorLivros.spec` usa exclusivamente caminhos relativos (`book_translator.py` e `pathex=['.']`) para compilação idêntica na estação local e nos runners `windows-latest` do GitHub Actions.
- **Decided:** Workflows `.github/workflows/ci.yml` e `.github/workflows/release.yml` executam o instrumento de voo único `python tools/dev.py check` antes de aceitar PRs ou publicar assets.

## 2. Mapa de Módulos e Papéis (`<= 250` linhas por arquivo)

| Arquivo | Papel (`Role`) | Responsabilidade Única | Colaboradores Permitidos |
| :--- | :--- | :--- | :--- |
| `src/domain/version.py` | `value` | Versão única do app e URLs do repositório GitHub | stdlib |
| `src/domain/update_models.py` | `value` | Dataclasses imutáveis e exceções do atualizador | stdlib |
| `src/policies/semver_policy.py` | `policy` | Comparação SemVer, validação de manifesto e anti Zip Slip | `src/domain/update_models.py` |
| `src/adapters/github_release_client.py` | `adapter` | Download HTTPS de `latest.json` e `.zip` com `SHA-256` | `version.py`, `update_models.py`, `semver_policy.py` |
| `src/adapters/windows_swap_installer.py` | `adapter` | Extração em staging e script trampolim `.cmd` no Windows | `update_models.py`, `semver_policy.py` |
| `src/services/self_update_service.py` | `service` | Orquestração de checagem, staging e disparo de update | `version.py`, `update_models.py`, `semver_policy.py`, adapters |
| `src/controllers/gui_update_dialog.py` | `controller` | Menu Ajuda, checagem silenciosa e diálogo acessível NVDA | `version.py`, `update_models.py`, `self_update_service.py` |
| `tools/build_release_assets.py` | `controller` | Empacotador de `TradutorLivros-win64.zip` + `latest.json` | `version.py`, `semver_policy.py` |

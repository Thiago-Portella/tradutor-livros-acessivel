# Behaviour Spec 0002: Contratos Observáveis do Atualizador Interno

## Exemplo Concreto de Uso (Aprovado pelo Humano)

### Manifesto publicado nos assets (`latest.json`)
```json
{
  "version": "1.1.0",
  "tag": "v1.1.0",
  "published_at": "2026-11-13T18:00:00Z",
  "asset_name": "TradutorLivros-win64.zip",
  "download_url": "https://github.com/Thiago-Portella/tradutor-livros-acessivel/releases/download/v1.1.0/TradutorLivros-win64.zip",
  "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  "size_bytes": 48251904,
  "release_notes": "- Adicionado atualizador interno acessível via GitHub Releases\n- Melhorias de estabilidade"
}
```

### Linha de Comando (CLI)
```powershell
python book_translator.py --version
# Tradutor e Aprimorador Acessível de Livros v1.0.0

python book_translator.py --check-update
# Você já está na versão mais recente (v1.0.0).
# ou:
# Nova versão disponível: v1.1.0 (atual: v1.0.0). Use --apply-update ou o menu Ajuda (F5) para atualizar.

TradutorLivros.exe --apply-update
```

## Cenários Observáveis (Casos Antes da Aceitação)

### Cenário 1: Comparação SemVer Determinística
- **Dado (Given):** Strings de versão válidas (`"1.0.0"`, `"v1.0.2"`, `"1.0.10"`, `"1.1.0"`) e uma string malformada (`"1.2"`).
- **Quando (When):** Executa-se `parse_semver` e `is_newer_version`.
- **Então (Then):** `"1.1.0" > "1.0.0"` e `"1.0.10" > "1.0.2"` retornam `True`, versões iguais retornam `False` e `"1.2"` lança `ValueError`.

### Cenário 2: Parse e Validação Estrita do `latest.json`
- **Dado (Given):** Um JSON de manifesto completo válido e manifestos inválidos (URL HTTP sem TLS ou hash `sha256` fora de 64 caracteres hex).
- **Quando (When):** Chama-se `parse_and_validate_manifest`.
- **Então (Then):** O manifesto válido retorna `ReleaseManifest` íntegro; os inválidos lançam `UpdateError` claro.

### Cenário 3: Checagem em Versão Atualizada
- **Dado (Given):** Versão local `"1.1.0"` e manifesto remoto com `"1.1.0"` ou `"1.0.9"`.
- **Quando (When):** Executa-se `check_for_updates`.
- **Então (Then):** Retorna `UpdateCheckResult(update_available=False, error_message=None)`.

### Cenário 4: Checagem Silenciosa Offline / Erro de Rede
- **Dado (Given):** Falha de conexão ou erro HTTP simulado na busca do manifesto.
- **Quando (When):** Executa-se `check_for_updates`.
- **Então (Then):** Não propaga exceção; retorna `UpdateCheckResult(update_available=False, manifest=None, error_message=...)` permitindo silêncio na inicialização da GUI e feedback claro sob demanda.

### Cenário 5: Download em Streaming e Validação `SHA-256`
- **Dado (Given):** Servidor HTTP local servindo um `.zip` válido e um `.zip` com hash divergente do manifesto.
- **Quando (When):** Executa-se `download_release_archive`.
- **Então (Then):** O arquivo íntegro é salvo no destino com callbacks de progresso; o arquivo corrompido lança `IntegrityVerificationError` e o destino parcial é removido sem lixo no disco.

### Cenário 6: Bloqueio Anti Zip Slip Antes da Extração
- **Dado (Given):** Um arquivo `.zip` malicioso contendo entrada `../evil.dll` ou caminho absoluto.
- **Quando (When):** Executa-se `stage_update_zip`.
- **Então (Then):** Lança `UnsafeArchiveError` antes de extrair qualquer arquivo para o sistema de arquivos.

### Cenário 7: Proteção do Ambiente de Desenvolvimento
- **Dado (Given):** Execução não congelada (`is_frozen=False`).
- **Quando (When):** Chama-se `prepare_and_stage_update`.
- **Então (Then):** Lança `DevelopmentModeUpdateError` orientando uso de `git pull`, sem baixar nem modificar arquivos locais.

### Cenário 8: Empacotamento de Release Assets e Script Trampolim Windows
- **Dado (Given):** Diretório simulado contendo `TradutorLivros.exe` e invocação de `tools/build_release_assets.py` e `build_trampoline_batch_content`.
- **Quando (When):** Empacota-se `TradutorLivros-win64.zip` com `latest.json` e gera-se o script `.cmd`.
- **Então (Then):** `build_release_assets.py` rejeita tag divergente de `APP_VERSION`, produz `.zip` + `latest.json` válido quando a tag coincide, e o script `.cmd` contém espera pelo `PID`, cópia via `robocopy` preservando dados externos, relançamento opcional e auto-remoção.

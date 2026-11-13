# Tradutor e Aprimorador Acessível de Livros

Aplicativo desktop e ferramenta CLI em Python para **extrair, aprimorar tipograficamente e traduzir livros** (`.pdf`, `.epub`, `.txt`, `.md`) exportando para **EPUB 3, PDF A4, HTML5, Markdown e TXT**, projetado com foco total em acessibilidade para leitores de tela (**NVDA**).

---

## Principais Recursos

- **Interface Gráfica Acessível (`wxPython` + NVDA):** Duas abas dedicadas (`1. Traduzir Livro` e `2. Apenas Aprimorar / Converter Livro`), aceleradores `Alt` exclusivos sem colisões, preview assíncrono de sumário sem travar o leitor de tela, bipes discretos opcionais e fechamento seguro via `Esc` quando ocioso.
- **Extração Estrutural Inteligente:**
  - **PDF (`PyMuPDF`):** Remoção de cabeçalhos/rodapés repetitivos, reconstrução de frases quebradas entre páginas, detecção de sumário em 5 camadas e suporte a múltiplos capítulos na mesma página.
  - **EPUB:** Parser estrutural baseado em `HTMLParser` com decodificação de URLs e entidades HTML/Unicode.
  - **Markdown e TXT:** Preservação fiel de títulos e filtro opcional por intervalo de capítulos/seções.
- **Tradução Resiliente com Cache SQLite WAL:** Fatiamento por fronteiras de sentenças respeitando limite de payload, captura automática do idioma detectado e salvamento progressivo em cache SQLite WAL (com geração segura de edição `_parcial` caso o usuário pause).
- **Edições Bilíngues e Exportação Acessível:** EPUB 3 e HTML5 com marcação semântica de idioma original (`lang`) e destino, sumários clicáveis, opção `[Voltar ao Sumário]` e suporte Unicode completo na exportação PDF A4.
- **Atualizador Interno via GitHub Release Assets (Custo Zero):**
  - Consulta diretamente o arquivo estático `latest.json` hospedado nos Release Assets do GitHub (sem sofrer limite de 60 req/h da API REST anônima).
  - Checagem silenciosa em segundo plano ao abrir (não interrompe se estiver offline ou já atualizado), verificação sob demanda no menu **Ajuda -> Verificar Atualizações (`F5`)** e flags de CLI.
  - Validação criptográfica **SHA-256**, bloqueio contra **Zip Slip** e troca automática de arquivos no Windows sem privilégio de Administrador via script trampolim pós-encerramento do processo.

---

## Instalação e Uso (Usuário Final — Windows)

1. Baixe o arquivo **`TradutorLivros-win64.zip`** na aba [Releases](https://github.com/Thiago-Portella/tradutor-livros-acessivel/releases).
2. Extraia a pasta `TradutorLivros` para um diretório de sua preferência (ex.: `C:\Programas\TradutorLivros`).
3. Execute **`TradutorLivros.exe`**.
4. Para verificar atualizações manualmente a qualquer momento, pressione **`F5`** (ou acesse **Ajuda -> Verificar Atualizações**).

---

## Execução a Partir do Código-Fonte

### Pré-requisitos
- Python 3.12 ou superior (Windows x64)
- Dependências listadas em `requirements.txt`

```powershell
git clone https://github.com/Thiago-Portella/tradutor-livros-acessivel.git
cd tradutor-livros-acessivel
pip install -r requirements.txt
```

### Abrindo a Interface Gráfica (GUI)
```powershell
python book_translator.py
```

### Linha de Comando (CLI)
```powershell
# Ver versão instalada
python book_translator.py --version

# Checar se há atualização disponível nas Releases do GitHub
python book_translator.py --check-update

# Aplicar atualização automaticamente (disponível apenas no executável TradutorLivros.exe)
TradutorLivros.exe --apply-update

# Traduzir um livro em modo CLI
python book_translator.py livro.epub --cli -s auto -t pt -f epub --bilingual

# Apenas aprimorar e converter PDF para HTML acessível sem traduzir
python book_translator.py obra.pdf --cli --enhance-only --doc-lang en -f html
```

---

## Fluxo de Trabalho de Branches e Lançamento de Versões

Este repositório utiliza um fluxo **Trunk leve com Release por Tag**, equilibrando organização, segurança e simplicidade:

### 1. Branches e Pull Requests
- **`main`:** Branch principal sempre estável e protegida. Não faça commits diretos na `main`; toda alteração entra via Pull Request aprovado pelo CI.
- **Branches de Trabalho:** Crie a partir da `main` usando prefixos claros:
  - `feat/<nome>` para novas funcionalidades
  - `fix/<nome>` para correções de bugs
  - `docs/<nome>` para documentação e especificações
  - `chore/<nome>` para manutenção, dependências ou automações

```powershell
# Criar branch de trabalho
git switch main
git pull
git switch -c feat/minha-melhoria

# Validar localmente antes do push (doctor, linters, build --if-stale e 100% dos testes)
python tools/dev.py check

# Enviar e abrir Pull Request
git push -u origin feat/minha-melhoria
gh pr create --fill
```

### 2. Como Publicar uma Nova Versão (GitHub Action Automática)
A versão oficial exibida pelo programa e validada pela Action vive em **`src/domain/version.py`** (`APP_VERSION`).

1. Em uma branch (`chore/release-1.1.0`), atualize `APP_VERSION = "1.1.0"` em `src/domain/version.py` e faça o merge via PR na `main`.
2. Sincronize a `main` local, crie a tag anotada correspondente e envie ao GitHub:
   ```powershell
   git switch main
   git pull
   git tag -a v1.1.0 -m "Release v1.1.0"
   git push origin v1.1.0
   ```
3. A workflow `.github/workflows/release.yml` será disparada automaticamente e executará:
   - Validação integral (`python tools/dev.py check`);
   - Geração automática das notas da versão a partir dos commits desde a tag anterior;
   - Conferência de paridade entre a tag `v1.1.0` e `APP_VERSION`;
   - Empacotamento de `TradutorLivros-win64.zip` e geração do manifesto `latest.json` com hash `SHA-256`;
   - Publicação oficial da Release no GitHub para os usuários atualizarem pelo próprio aplicativo!

---

## Arquitetura e Verificação Local

O projeto segue arquitetura em camadas desacopladas (`controllers` -> `services` -> `domain/policies` e `adapters`) documentada em [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) e regida pelo instrumento de voo único:

```powershell
python tools/dev.py check
```

Esse comando executa em sequência: diagnóstico de ambiente (`doctor`), validação de papéis `# Role:`, limite máximo de **250 linhas** por módulo de produção, proibição de módulos genéricos (`utils`/`helpers`), sincronia de `docs/ARCHITECTURE.md`, recompilação `--if-stale` com PyInstaller e 100% da suíte de testes automatizados.

---

## Licença

Distribuído sob a licença **MIT**. Consulte o arquivo [LICENSE](LICENSE) para detalhes.

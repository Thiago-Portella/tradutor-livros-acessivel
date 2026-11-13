# Proposal 0002: Atualizador Interno via GitHub Release Assets e CI/CD

- **Status:** Accepted
- **Data:** 2026-11-13

## 1. Contexto e Problema (Por quê)
A distribuição do `TradutorLivros.exe` em pasta (`--onedir`) exige hoje substituição manual completa pelo usuário a cada correção ou melhoria, sem notificação dentro da interface acessível nem garantia de integridade criptográfica do pacote baixado. Além disso, o repositório local não possui controle de versão remoto publicado no GitHub, pipelines de verificação automática em Pull Requests nem empacotamento automatizado de lançamentos.

## 2. Condições de Sucesso
- **Decided:** Utilizar exclusivamente os assets públicos do GitHub Releases (`https://github.com/Thiago-Portella/tradutor-livros-acessivel/releases/latest/download/latest.json`) servidos via CDN sem depender da REST API anônima do GitHub (evitando limite de 60 requisições/hora por IP) e sem domínio próprio.
- **Decided:** Validar integralmente todo pacote `.zip` antes de extrair e aplicar: verificação de hash `SHA-256` contra o `latest.json` e bloqueio de travessia de diretórios (*Zip Slip*).
- **Decided:** Executar a substituição da pasta do aplicativo no Windows por meio de script trampolim `.cmd` em pasta temporária aguardando o encerramento do `PID` em execução, preservando arquivos externos do usuário e operando sem exigir privilégios de Administrador.
- **Decided:** Proibir aplicação automática de atualização quando o programa estiver rodando em código-fonte não empacotado (`getattr(sys, "frozen", False)` falso), evitando sobrescrita acidental do repositório Git.
- **Decided:** Oferecer checagem silenciosa em segundo plano na abertura da GUI (sem interromper leitores de tela caso offline ou atualizado), menu `&Ajuda` (`F5` Verificar Atualizações e Sobre) e flags CLI (`--version`, `--check-update`, `--apply-update`).
- **Decided:** Adotar fluxo *Trunk* leve (`feat/*`, `fix/*`, `docs/*`, `chore/*` -> Pull Request validado pelo CI na `main`) e geração automática da GitHub Release (`TradutorLivros-win64.zip` + `latest.json` + changelog dos commits) ao enviar tags `vX.Y.Z` sincronizadas com `APP_VERSION` em `src/domain/version.py`.

## 3. Não-Objetivos (Out of Scope)
- Aquisição de domínio próprio, servidor dedicado de atualizações ou certificado comercial pago de assinatura de código (EV/OV).
- Geração de instalador Inno Setup nesta fase (formato aprovado: pacote portátil `.zip` + `latest.json`).
- Canais múltiplos Beta/Nightly ou branches permanentes paralelas como `develop`.

## 4. Alternativas Rejeitadas (`Rejected`)
- **Rejected:** Consultar `https://api.github.com/repos/.../releases/latest` diretamente nos clientes — bloqueia clientes sob NAT/VPN após 60 consultas por hora.
- **Rejected:** Empacotar em modo `--onefile` no PyInstaller — degrada tempo de abertura a cada execução e eleva falsos positivos de antivírus.
- **Rejected:** GitFlow pesado com `develop` e `release/*` — adiciona merge commits redundantes para repositório desktop enxuto.
- **Rejected:** Injetar versão apenas em tempo de compilação no CI — faz execuções locais e testes perderem rastreabilidade SemVer contra o `latest.json`.

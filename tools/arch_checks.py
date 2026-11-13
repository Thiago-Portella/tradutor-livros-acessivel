# Role: policy
"""Regras estáticas de governança arquitetural para o gate tools/dev.py check."""

from __future__ import annotations

import re
from pathlib import Path
from typing import List

VALID_ROLES = {"entity", "value", "policy", "port", "adapter", "service", "controller"}
FORBIDDEN_STEMS = {"utils", "helpers", "common", "shared", "misc"}
MAX_LINES = 250
_FORBIDDEN_PHRASES = (
    "antes era",
    "mudou no milestone",
    "mudou no pr",
    "removido no pr",
    "removido por causa",
    "adicionado para corrigir",
    "changelog:",
    "histórico de pr",
)
_ARCHAEOLOGY_RE = re.compile(r"^\s*#.*\b(" + "|".join(_FORBIDDEN_PHRASES) + r")\b", re.I)


def iter_project_py_files(root: Path, include_tests: bool = True) -> List[Path]:
    files: List[Path] = []
    for p in sorted(root.glob("*.py")):
        files.append(p)
    dirs = ["src", "tools"] + (["tests"] if include_tests else [])
    for folder in dirs:
        base = root / folder
        if base.exists():
            files.extend(sorted(base.rglob("*.py")))
    return files


def check_roles(root: Path) -> List[str]:
    errors: List[str] = []
    for py_file in iter_project_py_files(root, include_tests=True):
        head = py_file.read_text(encoding="utf-8").splitlines()[:5]
        role_line = next((ln.strip() for ln in head if ln.strip().startswith("# Role:")), None)
        if not role_line:
            errors.append(f"Cabeçalho '# Role:' ausente nas 5 primeiras linhas: {py_file.relative_to(root)}")
            continue
        role_val = role_line.split(":", 1)[1].strip()
        if role_val not in VALID_ROLES:
            errors.append(f"Role inválido '{role_val}' em {py_file.relative_to(root)}")
    return errors


def check_line_limits(root: Path) -> List[str]:
    errors: List[str] = []
    for py_file in iter_project_py_files(root, include_tests=False):
        count = len(py_file.read_text(encoding="utf-8").splitlines())
        if count > MAX_LINES:
            errors.append(f"Arquivo excede {MAX_LINES} linhas ({count} linhas): {py_file.relative_to(root)}")
    return errors


def check_forbidden_filenames(root: Path) -> List[str]:
    errors: List[str] = []
    for py_file in iter_project_py_files(root, include_tests=True):
        if py_file.stem.lower() in FORBIDDEN_STEMS:
            errors.append(f"Nome de módulo proibido ({py_file.stem}): {py_file.relative_to(root)}")
    return errors


def check_comment_hygiene(root: Path) -> List[str]:
    errors: List[str] = []
    for py_file in iter_project_py_files(root, include_tests=True):
        for idx, ln in enumerate(py_file.read_text(encoding="utf-8").splitlines(), start=1):
            if _ARCHAEOLOGY_RE.search(ln):
                errors.append(f"Comentário arqueológico proibido em {py_file.relative_to(root)}:{idx}")
    return errors


def check_architecture_sync(root: Path) -> List[str]:
    arch_file = root / "docs" / "ARCHITECTURE.md"
    if not arch_file.exists():
        return ["Arquivo docs/ARCHITECTURE.md ausente."]
    text = arch_file.read_text(encoding="utf-8")
    if "mermaid" not in text or "Descrição Textual da Arquitetura" not in text:
        return ["docs/ARCHITECTURE.md deve conter diagrama Mermaid e lista numerada textual para NVDA."]

    table_paths = set()
    for ln in text.splitlines():
        if ln.startswith("|") and "`" in ln:
            parts = [p.strip() for p in ln.split("|")]
            if len(parts) >= 3 and parts[2].startswith("`") and parts[2].endswith("`"):
                table_paths.add(parts[2].strip("`"))

    disk_paths = {
        p.relative_to(root).as_posix()
        for p in iter_project_py_files(root, include_tests=False)
    }

    errors: List[str] = []
    for missing_in_doc in sorted(disk_paths - table_paths):
        errors.append(f"Módulo ausente da tabela 'Onde vive' em docs/ARCHITECTURE.md: {missing_in_doc}")
    for orphan_in_doc in sorted(table_paths - disk_paths):
        errors.append(f"Entrada órfã em docs/ARCHITECTURE.md não encontrada no disco: {orphan_in_doc}")
    return errors

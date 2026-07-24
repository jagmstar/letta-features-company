from __future__ import annotations

import argparse
import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from string import Template
from typing import Any, Iterable
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_PATH = Path(__file__).resolve().with_name("report-template.md")
DEFAULT_JSON_SUFFIX = ".json"
SKIP_DIRS = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".tox",
    ".venv",
    "venv",
    "dist",
    "build",
    "node_modules",
}
SOURCE_EXTENSIONS = {".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}
DOC_EXTENSIONS = {".md", ".rst", ".adoc", ".txt"}
DEPENDENCY_FILES = {
    "requirements.txt",
    "requirements-dev.txt",
    "requirements-test.txt",
    "pyproject.toml",
    "setup.py",
    "Pipfile",
    "Pipfile.lock",
    "package.json",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
    "uv.lock",
    "LICENSE",
    "LICENSE.txt",
    "LICENSE.md",
    "COPYING",
}
LICENSE_PATTERNS = {
    "MIT": re.compile(r"\bmit license\b|permission is hereby granted, free of charge", re.I),
    "Apache-2.0": re.compile(r"apache license|version 2\.0", re.I),
    "BSD-3-Clause": re.compile(r"redistribution and use in source and binary forms", re.I),
    "BSD-2-Clause": re.compile(r"neither the name of the .* nor the names of its contributors", re.I),
    "GPL-3.0": re.compile(r"gnu general public license", re.I),
    "LGPL-3.0": re.compile(r"lesser general public license", re.I),
    "MPL-2.0": re.compile(r"mozilla public license", re.I),
    "ISC": re.compile(r"permission to use, copy, modify, and/or distribute this software", re.I),
    "Unlicense": re.compile(r"this is free and unencumbered software released into the public domain", re.I),
}
SECRET_PATTERNS = [
    re.compile(r"(?i)\b(api[_-]?key|secret|token|password|passwd|private[_-]?key)\b\s*[:=]\s*['\"][^'\"]{8,}['\"]"),
    re.compile(r"-----BEGIN (RSA|EC|OPENSSH|DSA|PRIVATE) KEY-----"),
]
DANGEROUS_CALLS = {"eval", "exec", "compile"}
SHELL_TRUE_PATTERN = re.compile(r"shell\s*=\s*True")
UNSAFE_LOAD_PATTERN = re.compile(r"\byaml\.load\s*\(")
GITHUB_WORKFLOW_PATTERN = re.compile(r"\.github[\\/]+workflows[\\/].+\.(ya?ml)$", re.I)


@dataclass(slots=True)
class RepoSource:
    raw: str
    kind: str
    resolved: str


@dataclass(slots=True)
class CheckResult:
    name: str
    score: float
    metrics: dict[str, Any]
    findings: list[dict[str, str]]


class AuditError(RuntimeError):
    pass


class ComplexityVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.current = 1

    def generic_visit(self, node: ast.AST) -> None:
        if isinstance(node, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler, ast.With, ast.AsyncWith)):
            self.current += 1
        elif isinstance(node, ast.BoolOp):
            self.current += max(0, len(node.values) - 1)
        elif isinstance(node, ast.IfExp):
            self.current += 1
        elif hasattr(ast, "Match") and isinstance(node, ast.Match):  # pragma: no cover - Python 3.10+
            self.current += len(node.cases)
        elif isinstance(node, (ast.comprehension,)):
            self.current += len(node.ifs)
        super().generic_visit(node)


class FunctionSpanVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.spans: list[dict[str, Any]] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:  # noqa: N802 - ast visitor API
        self._record(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> Any:  # noqa: N802 - ast visitor API
        self._record(node)
        self.generic_visit(node)

    def _record(self, node: ast.AST) -> None:
        end_lineno = getattr(node, "end_lineno", None) or getattr(node, "lineno", 0)
        self.spans.append(
            {
                "name": getattr(node, "name", "<anonymous>"),
                "lineno": getattr(node, "lineno", 0),
                "end_lineno": end_lineno,
                "length": max(0, end_lineno - getattr(node, "lineno", 0) + 1),
            }
        )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _run(command: list[str], *, cwd: Path, env: dict[str, str] | None = None, timeout: int = 900) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _merge_env(repo_root: Path) -> dict[str, str]:
    env = os.environ.copy()
    pythonpath = env.get("PYTHONPATH")
    repo_root_text = str(repo_root)
    env["PYTHONPATH"] = repo_root_text if not pythonpath else os.pathsep.join([repo_root_text, pythonpath])
    return env


def _is_git_remote(raw: str) -> bool:
    return bool(
        re.match(r"^https://github\.com/[^/\s]+/[^/\s]+(?:\.git)?/?$", raw)
        or re.match(r"^git@github\.com:[^/\s]+/[^/\s]+(?:\.git)?$", raw)
    )


def resolve_repo_source(repo_input: str) -> RepoSource:
    candidate = repo_input.strip()
    if not candidate:
        raise ValueError("repo source cannot be empty")

    local_path = Path(candidate)
    if local_path.exists():
        return RepoSource(raw=candidate, kind="path", resolved=str(local_path.resolve()))

    if _is_git_remote(candidate):
        return RepoSource(raw=candidate, kind="url", resolved=candidate)

    parsed = urlparse(candidate)
    if parsed.scheme in {"http", "https", "ssh", "git"}:
        raise ValueError("Only GitHub repository URLs are supported for remote audits")

    raise ValueError("Repo source must be an existing local path or a GitHub repository URL")


def clone_repository(source: RepoSource, workdir: Path) -> Path:
    destination = workdir / "cloned-repo"
    if destination.exists():
        shutil.rmtree(destination)

    if source.kind == "path":
        command = ["git", "clone", "--depth", "1", source.resolved.replace("\\", "/"), str(destination)]
    else:
        command = ["git", "clone", "--depth", "1", source.resolved, str(destination)]

    result = _run(command, cwd=workdir)
    if result.returncode != 0:
        raise AuditError(
            "Failed to clone repository\n"
            f"command: {' '.join(command)}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )

    return destination


def _git_output(repo_root: Path, args: list[str]) -> str:
    result = _run(["git", *args], cwd=repo_root)
    return result.stdout.strip() if result.returncode == 0 else ""


def list_files(repo_root: Path) -> list[Path]:
    files: list[Path] = []
    for path in repo_root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        files.append(path)
    return files


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def rel(path: Path, repo_root: Path) -> str:
    try:
        return str(path.relative_to(repo_root)).replace("\\", "/")
    except ValueError:
        return str(path)


def count_nonblank_lines(text: str) -> int:
    return sum(1 for line in text.splitlines() if line.strip())


def detect_local_modules(repo_root: Path, python_files: list[Path]) -> set[str]:
    modules = {path.stem for path in python_files}
    for path in repo_root.iterdir():
        if not path.is_dir():
            continue
        if any(child.suffix.lower() == ".py" for child in path.rglob("*.py")):
            modules.add(path.name)
    return modules


def classify_files(repo_root: Path, files: list[Path]) -> dict[str, list[Path]]:
    buckets: dict[str, list[Path]] = defaultdict(list)
    for path in files:
        rel_path = rel(path, repo_root)
        suffix = path.suffix.lower()
        lower_name = path.name.lower()
        if suffix == ".py":
            buckets["python"].append(path)
            if "/tests/" in f"/{rel_path}/" or lower_name.startswith("test_") or lower_name.endswith("_test.py"):
                buckets["tests"].append(path)
            else:
                buckets["source"].append(path)
        elif suffix in DOC_EXTENSIONS or lower_name.startswith("readme"):
            buckets["docs"].append(path)
        elif suffix in {".yml", ".yaml"} and GITHUB_WORKFLOW_PATTERN.search(rel_path):
            buckets["workflows"].append(path)
        elif lower_name in {name.lower() for name in DEPENDENCY_FILES}:
            buckets["manifests"].append(path)
        elif suffix in SOURCE_EXTENSIONS:
            buckets["source"].append(path)
        if lower_name in {name.lower() for name in DEPENDENCY_FILES}:
            buckets["dependency_files"].append(path)
    return buckets


def analyze_python_code(repo_root: Path, python_files: list[Path]) -> CheckResult:
    module_docstrings = 0
    total_functions = 0
    total_loc = 0
    total_comment_lines = 0
    total_file_count = len(python_files)
    complexity_values: list[int] = []
    function_lengths: list[int] = []
    todo_hits = 0
    files_with_class_defs = 0
    max_file_loc = 0
    longest_function: dict[str, Any] | None = None

    for path in python_files:
        text = read_text(path)
        total_loc += count_nonblank_lines(text)
        max_file_loc = max(max_file_loc, len(text.splitlines()))
        total_comment_lines += sum(1 for line in text.splitlines() if line.lstrip().startswith("#"))
        todo_hits += len(re.findall(r"(?i)\b(?:todo|fixme|xxx)\b", text))
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue

        if ast.get_docstring(tree):
            module_docstrings += 1
        if any(isinstance(node, ast.ClassDef) for node in ast.walk(tree)):
            files_with_class_defs += 1

        func_visitor = FunctionSpanVisitor()
        func_visitor.visit(tree)
        for func in func_visitor.spans:
            total_functions += 1
            function_lengths.append(func["length"])
            if longest_function is None or func["length"] > longest_function["length"]:
                longest_function = {"file": rel(path, repo_root), **func}

            node = next(
                (
                    candidate
                    for candidate in ast.walk(tree)
                    if isinstance(candidate, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and getattr(candidate, "name", None) == func["name"]
                    and getattr(candidate, "lineno", None) == func["lineno"]
                ),
                None,
            )
            if node is not None:
                visitor = ComplexityVisitor()
                for stmt in node.body:
                    visitor.visit(stmt)
                complexity_values.append(visitor.current)

    avg_function_length = round(sum(function_lengths) / len(function_lengths), 2) if function_lengths else 0.0
    max_function_length = max(function_lengths) if function_lengths else 0
    max_complexity = max(complexity_values) if complexity_values else 0
    docstring_coverage = round((module_docstrings / total_file_count) * 100, 2) if total_file_count else 0.0
    comment_density = round((total_comment_lines / total_loc) * 100, 2) if total_loc else 0.0
    complexity_over_10 = sum(1 for value in complexity_values if value > 10)
    long_functions = sum(1 for value in function_lengths if value > 80)

    metrics = {
        "python_files": total_file_count,
        "source_lines": total_loc,
        "comment_lines": total_comment_lines,
        "comment_density_percent": comment_density,
        "module_docstring_coverage_percent": docstring_coverage,
        "function_count": total_functions,
        "avg_function_length": avg_function_length,
        "max_function_length": max_function_length,
        "max_cyclomatic_complexity": max_complexity,
        "functions_over_80_lines": long_functions,
        "functions_over_complexity_10": complexity_over_10,
        "todo_fixme_hits": todo_hits,
        "files_with_classes": files_with_class_defs,
        "largest_python_file_lines": max_file_loc,
        "longest_function": longest_function,
    }

    findings: list[dict[str, str]] = []
    if docstring_coverage < 60 and total_file_count:
        findings.append(
            {
                "severity": "medium",
                "title": "Module docstring coverage is light",
                "detail": f"Only {module_docstrings} of {total_file_count} Python files include module docstrings.",
            }
        )
    if max_complexity > 12:
        findings.append(
            {
                "severity": "medium",
                "title": "At least one function is relatively complex",
                "detail": f"Maximum observed cyclomatic complexity is {max_complexity}.",
            }
        )
    if long_functions:
        findings.append(
            {
                "severity": "medium",
                "title": "Some functions are long enough to review",
                "detail": f"{long_functions} functions exceed 80 lines.",
            }
        )
    if todo_hits:
        findings.append(
            {
                "severity": "low",
                "title": "TODO/FIXME markers remain in source",
                "detail": f"Found {todo_hits} TODO/FIXME-style markers across Python files.",
            }
        )

    score = 100.0
    score -= max(0.0, (60 - docstring_coverage) * 0.5) if total_file_count else 0.0
    score -= min(25.0, complexity_over_10 * 4.0)
    score -= min(20.0, long_functions * 5.0)
    score -= min(10.0, todo_hits * 2.0)
    score = max(0.0, round(score, 2))

    return CheckResult(name="Code quality", score=score, metrics=metrics, findings=findings)


def _count_test_cases_in_tree(tree: ast.AST) -> int:
    count = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
            count += 1
        elif isinstance(node, ast.AsyncFunctionDef) and node.name.startswith("test_"):
            count += 1
        elif isinstance(node, ast.ClassDef):
            if any(base for base in node.bases if getattr(base, "id", None) == "TestCase" or getattr(base, "attr", None) == "TestCase"):
                count += sum(1 for child in node.body if isinstance(child, ast.FunctionDef) and child.name.startswith("test_"))
    return count


def _coverage_from_json(coverage_json: dict[str, Any], source_files: list[Path], repo_root: Path) -> tuple[float | None, dict[str, Any]]:
    files_data = coverage_json.get("files", {})
    measurable = 0
    covered_lines = 0
    source_lines = 0
    missing_files = []
    for path in source_files:
        rel_path = rel(path, repo_root)
        file_data = files_data.get(rel_path) or files_data.get(str(path)) or files_data.get(path.as_posix())
        if file_data is None:
            missing_files.append(rel_path)
            source_lines += count_nonblank_lines(read_text(path))
            continue
        summary = file_data.get("summary", {})
        measurable += 1
        covered_lines += int(summary.get("covered_lines", 0))
        source_lines += int(summary.get("num_statements", count_nonblank_lines(read_text(path))))
    percent = round((covered_lines / source_lines) * 100, 2) if source_lines else None
    return percent, {
        "measured_source_files": measurable,
        "unmeasured_source_files": len(missing_files),
        "unmeasured_files": missing_files[:15],
        "covered_lines": covered_lines,
        "source_lines": source_lines,
    }


def analyze_test_coverage(repo_root: Path, python_files: list[Path], source_files: list[Path]) -> CheckResult:
    test_files = [path for path in python_files if path not in source_files]
    test_cases = 0
    for path in test_files:
        try:
            test_cases += _count_test_cases_in_tree(ast.parse(read_text(path)))
        except SyntaxError:
            continue

    env = _merge_env(repo_root)
    coverage_data_path = repo_root / ".audit-coverage.json"
    if coverage_data_path.exists():
        coverage_data_path.unlink()

    test_command = [sys.executable, "-m", "coverage", "run", "-m", "pytest", "-q"]
    result = _run(test_command, cwd=repo_root, env=env, timeout=1800)
    coverage_percent: float | None = None
    coverage_meta: dict[str, Any] = {}
    test_run_status = "passed" if result.returncode == 0 else "failed"
    test_runner = "pytest"
    if result.returncode == 0:
        coverage_json_cmd = [sys.executable, "-m", "coverage", "json", "-o", str(coverage_data_path)]
        json_result = _run(coverage_json_cmd, cwd=repo_root, env=env, timeout=300)
        if json_result.returncode == 0 and coverage_data_path.exists():
            coverage_json = json.loads(coverage_data_path.read_text(encoding="utf-8"))
            coverage_percent, coverage_meta = _coverage_from_json(coverage_json, source_files, repo_root)
            coverage_meta["coverage_json_totals"] = coverage_json.get("totals", {})
        else:
            coverage_meta = {
                "coverage_json_error": json_result.stderr.strip(),
                "coverage_json_stdout": json_result.stdout.strip(),
            }
    else:
        test_runner = "pytest"
        coverage_meta = {
            "stderr": result.stderr.strip(),
            "stdout": result.stdout.strip(),
        }

    if coverage_percent is None:
        covered_sources = sum(1 for path in source_files if any(path.name == test_file.name for test_file in test_files))
        coverage_percent = round((covered_sources / len(source_files)) * 100, 2) if source_files else 0.0
        coverage_meta["proxy_coverage_note"] = "Coverage tool unavailable or failed; fallback ratio uses source files with sibling tests."

    findings: list[dict[str, str]] = []
    if test_run_status != "passed":
        findings.append(
            {
                "severity": "high",
                "title": "Test suite did not pass cleanly",
                "detail": "The repository test command returned a non-zero exit code.",
            }
        )
    if coverage_percent < 60:
        findings.append(
            {
                "severity": "medium",
                "title": "Test coverage is below target",
                "detail": f"Measured coverage is {coverage_percent}%.",
            }
        )
    if not test_files:
        findings.append(
            {
                "severity": "medium",
                "title": "No Python test files detected",
                "detail": "The repository has no Python test files to measure.",
            }
        )

    score = max(0.0, round(coverage_percent - (0 if test_run_status == "passed" else 20), 2))

    metrics = {
        "test_files": len(test_files),
        "test_cases": test_cases,
        "source_files": len(source_files),
        "coverage_percent": coverage_percent,
        "test_run_status": test_run_status,
        "test_runner": test_runner,
        "test_command": " ".join(test_command),
        **coverage_meta,
    }
    return CheckResult(name="Test coverage", score=score, metrics=metrics, findings=findings)


def analyze_security(repo_root: Path, files: list[Path]) -> CheckResult:
    findings: list[dict[str, str]] = []
    secret_hits = 0
    shell_true = 0
    unsafe_loads = 0
    dangerous_calls = 0
    top_files = Counter()

    for path in files:
        if path.suffix.lower() not in {".py", ".js", ".ts", ".jsx", ".tsx", ".yml", ".yaml", ".json", ".md", ".txt"}:
            continue
        text = read_text(path)
        matched = False
        for pattern in SECRET_PATTERNS:
            hits = pattern.findall(text)
            if hits:
                secret_hits += len(hits)
                matched = True
        if SHELL_TRUE_PATTERN.search(text):
            shell_true += len(SHELL_TRUE_PATTERN.findall(text))
            matched = True
        if UNSAFE_LOAD_PATTERN.search(text):
            unsafe_loads += len(UNSAFE_LOAD_PATTERN.findall(text))
            matched = True
        if matched:
            top_files[rel(path, repo_root)] += 1
        if path.suffix.lower() == ".py":
            try:
                tree = ast.parse(text)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    func_name = None
                    if isinstance(node.func, ast.Name):
                        func_name = node.func.id
                    elif isinstance(node.func, ast.Attribute):
                        func_name = node.func.attr
                    if func_name in DANGEROUS_CALLS:
                        dangerous_calls += 1
                    if func_name == "load" and isinstance(node.func, ast.Attribute) and getattr(node.func.value, "id", None) == "yaml":
                        unsafe_loads += 1
                    if func_name == "run" and any(
                        kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True
                        for kw in node.keywords
                    ):
                        shell_true += 1

    if secret_hits:
        findings.append(
            {
                "severity": "high",
                "title": "Secret-like values found in repository text",
                "detail": f"Detected {secret_hits} potential secret patterns in tracked files.",
            }
        )
    if shell_true:
        findings.append(
            {
                "severity": "medium",
                "title": "Shell invocation detected in code",
                "detail": f"Found {shell_true} shell=True or shell-like invocation(s).",
            }
        )
    if dangerous_calls:
        findings.append(
            {
                "severity": "medium",
                "title": "Dynamic code execution primitives are present",
                "detail": f"Detected {dangerous_calls} eval/exec/compile call(s).",
            }
        )
    if unsafe_loads:
        findings.append(
            {
                "severity": "medium",
                "title": "Potentially unsafe deserialization detected",
                "detail": f"Found {unsafe_loads} yaml.load-style call(s).",
            }
        )

    score = 100.0
    score -= min(40.0, secret_hits * 20.0)
    score -= min(15.0, shell_true * 5.0)
    score -= min(15.0, dangerous_calls * 5.0)
    score -= min(15.0, unsafe_loads * 5.0)
    score = max(0.0, round(score, 2))

    metrics = {
        "secret_like_hits": secret_hits,
        "shell_true_hits": shell_true,
        "unsafe_load_hits": unsafe_loads,
        "dynamic_exec_hits": dangerous_calls,
        "top_files": top_files.most_common(10),
    }
    return CheckResult(name="Security", score=score, metrics=metrics, findings=findings)


def analyze_documentation(repo_root: Path, files: list[Path], python_files: list[Path]) -> CheckResult:
    docs_files = [path for path in files if path.suffix.lower() in DOC_EXTENSIONS or path.name.lower().startswith("readme")]
    module_docstrings = 0
    for path in python_files:
        try:
            if ast.get_docstring(ast.parse(read_text(path))):
                module_docstrings += 1
        except SyntaxError:
            continue

    readme_present = any(path.name.lower().startswith("readme") for path in docs_files)
    openapi_present = any("openapi" in path.name.lower() for path in docs_files) or any("openapi" in rel(path, repo_root).lower() for path in files)
    total_python = len(python_files)
    docstring_coverage = round((module_docstrings / total_python) * 100, 2) if total_python else 0.0
    docs_ratio = round((len(docs_files) / len(files)) * 100, 2) if files else 0.0

    findings: list[dict[str, str]] = []
    if not readme_present:
        findings.append(
            {
                "severity": "medium",
                "title": "README file is missing",
                "detail": "The repository does not include a top-level README.",
            }
        )
    if docstring_coverage < 50 and total_python:
        findings.append(
            {
                "severity": "low",
                "title": "Python module docstring coverage can improve",
                "detail": f"Only {module_docstrings} of {total_python} Python files have module docstrings.",
            }
        )

    score = 100.0
    score -= max(0.0, (70 - docstring_coverage) * 0.4)
    score -= 0 if readme_present else 20
    score -= 0 if openapi_present else 5
    score = max(0.0, round(score, 2))

    metrics = {
        "docs_files": len(docs_files),
        "markdown_files": sum(1 for path in files if path.suffix.lower() == ".md"),
        "module_docstring_coverage_percent": docstring_coverage,
        "docs_ratio_percent": docs_ratio,
        "readme_present": readme_present,
        "openapi_present": openapi_present,
        "total_python_files": total_python,
        "module_docstrings": module_docstrings,
    }
    return CheckResult(name="Documentation", score=score, metrics=metrics, findings=findings)


def analyze_cicd(repo_root: Path, files: list[Path]) -> CheckResult:
    workflow_files = [path for path in files if GITHUB_WORKFLOW_PATTERN.search(rel(path, repo_root))]
    job_count = 0
    test_job_count = 0
    deploy_workflows = 0
    artifact_uploads = 0
    build_commands = 0
    workflow_triggers = 0
    for path in workflow_files:
        text = read_text(path)
        job_count += len(re.findall(r"^\s{2}[A-Za-z0-9_-]+:\s*$", text, re.M))
        if re.search(r"(?i)pytest|unittest", text):
            test_job_count += 1
        if re.search(r"(?i)deploy-pages|github-pages|pages: write", text):
            deploy_workflows += 1
        if "upload-artifact" in text or "upload-pages-artifact" in text:
            artifact_uploads += 1
        build_commands += len(re.findall(r"(?mi)^\s*run:\s+.*(?:pytest|python|npm|make|tox)", text))
        workflow_triggers += len(re.findall(r"(?mi)^on:\s*$|^\s+-\s+(?:push|pull_request|workflow_run|workflow_dispatch)\b", text))

    findings: list[dict[str, str]] = []
    if not workflow_files:
        findings.append(
            {
                "severity": "high",
                "title": "No CI/CD workflows found",
                "detail": "The repository has no GitHub Actions workflow files.",
            }
        )
    elif not test_job_count:
        findings.append(
            {
                "severity": "medium",
                "title": "CI workflows do not appear to run tests",
                "detail": "No test command was detected in workflow steps.",
            }
        )
    if not deploy_workflows and workflow_files:
        findings.append(
            {
                "severity": "low",
                "title": "No deploy workflow detected",
                "detail": "CI exists, but a deployment workflow was not detected.",
            }
        )

    score = 100.0
    score -= 0 if workflow_files else 40
    score -= 0 if test_job_count else 25
    score -= 0 if deploy_workflows else 10
    score -= 0 if artifact_uploads else 5
    score = max(0.0, round(score, 2))

    metrics = {
        "workflow_files": len(workflow_files),
        "job_count": job_count,
        "test_job_count": test_job_count,
        "deploy_workflows": deploy_workflows,
        "artifact_uploads": artifact_uploads,
        "build_commands": build_commands,
        "workflow_triggers": workflow_triggers,
    }
    return CheckResult(name="CI/CD", score=score, metrics=metrics, findings=findings)


def _parse_requirements(path: Path) -> tuple[int, int, list[str]]:
    declared = 0
    pinned = 0
    names: list[str] = []
    for raw_line in read_text(path).splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        declared += 1
        name = re.split(r"[<>=~!; \[]", line, maxsplit=1)[0].strip()
        if name:
            names.append(name)
        if re.search(r"(==|===|@|/|git\+)", line):
            pinned += 1
    return declared, pinned, names


def _parse_package_json(path: Path) -> tuple[int, int, list[str]]:
    declared = 0
    pinned = 0
    names: list[str] = []
    payload = json.loads(read_text(path))
    for section in ("dependencies", "devDependencies", "peerDependencies"):
        deps = payload.get(section, {}) or {}
        for name, version in deps.items():
            declared += 1
            names.append(name)
            if re.fullmatch(r"\d+\.\d+\.\d+", str(version).lstrip("^~=")):
                pinned += 1
    return declared, pinned, names


def _parse_pyproject(path: Path) -> tuple[int, int, list[str]]:
    declared = 0
    pinned = 0
    names: list[str] = []
    text = read_text(path)
    for match in re.finditer(r'"([A-Za-z0-9_.-]+)(?:\s*\[[^\]]+\])?\s*([<>=!~].*?)?"', text):
        declared += 1
        names.append(match.group(1))
        if match.group(2) and "==" in match.group(2):
            pinned += 1
    return declared, pinned, names


def analyze_dependencies(repo_root: Path, files: list[Path], python_files: list[Path]) -> CheckResult:
    manifest_files = [path for path in files if path.name in DEPENDENCY_FILES or path.name.lower() in {name.lower() for name in DEPENDENCY_FILES}]
    lockfiles = [path for path in manifest_files if path.name.lower() in {"poetry.lock", "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "uv.lock", "pipfile.lock"}]
    declared = 0
    pinned = 0
    manifest_names: list[str] = []
    manifest_types: Counter[str] = Counter()

    for path in manifest_files:
        manifest_types[path.name.lower()] += 1
        lower = path.name.lower()
        try:
            if lower.startswith("requirements"):
                d, p, names = _parse_requirements(path)
            elif lower == "package.json":
                d, p, names = _parse_package_json(path)
            elif lower == "pyproject.toml":
                d, p, names = _parse_pyproject(path)
            else:
                d, p, names = (0, 0, [])
        except Exception:
            d, p, names = (0, 0, [])
        declared += d
        pinned += p
        manifest_names.extend(names)

    local_modules = detect_local_modules(repo_root, python_files)
    stdlib_modules = set(getattr(sys, "stdlib_module_names", set()))
    external_imports: set[str] = set()
    import_sources: Counter[str] = Counter()

    for path in python_files:
        try:
            tree = ast.parse(read_text(path))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            module_name = None
            if isinstance(node, ast.Import):
                for alias in node.names:
                    module_name = alias.name.split(".")[0]
                    if module_name not in stdlib_modules and module_name not in local_modules:
                        external_imports.add(module_name)
                        import_sources[module_name] += 1
            elif isinstance(node, ast.ImportFrom):
                if node.level and node.level > 0:
                    continue
                if node.module:
                    module_name = node.module.split(".")[0]
                    if module_name not in stdlib_modules and module_name not in local_modules:
                        external_imports.add(module_name)
                        import_sources[module_name] += 1

    findings: list[dict[str, str]] = []
    if not manifest_files:
        findings.append(
            {
                "severity": "medium",
                "title": "No dependency manifest detected",
                "detail": "The repository does not declare dependencies in a recognized manifest file.",
            }
        )
    if external_imports and not manifest_files:
        findings.append(
            {
                "severity": "medium",
                "title": "Third-party imports are present without a manifest",
                "detail": f"Detected {len(external_imports)} external import(s) such as {', '.join(sorted(external_imports)[:5])}.",
            }
        )
    if declared and pinned < declared:
        findings.append(
            {
                "severity": "low",
                "title": "Some dependencies are not pinned",
                "detail": f"{declared - pinned} of {declared} declared dependencies are not pinned to exact versions.",
            }
        )
    if lockfiles:
        findings.append(
            {
                "severity": "low",
                "title": "Lockfiles are present",
                "detail": f"Found {len(lockfiles)} lockfile(s) that can improve reproducibility.",
            }
        )

    score = 100.0
    score -= 0 if manifest_files else 20
    score -= min(20.0, max(0, declared - pinned) * 2.0)
    score += 5 if lockfiles else 0
    score = max(0.0, min(100.0, round(score, 2)))

    metrics = {
        "manifest_files": len(manifest_files),
        "manifest_types": dict(manifest_types),
        "declared_dependencies": declared,
        "pinned_dependencies": pinned,
        "external_imports": sorted(external_imports),
        "external_import_count": len(external_imports),
        "lockfiles": len(lockfiles),
        "lockfile_names": [path.name for path in lockfiles],
        "import_sources": dict(import_sources),
    }
    return CheckResult(name="Dependency health", score=score, metrics=metrics, findings=findings)


def _detect_license(text: str) -> str | None:
    for license_name, pattern in LICENSE_PATTERNS.items():
        if pattern.search(text):
            return license_name
    return None


def analyze_license(repo_root: Path, files: list[Path]) -> CheckResult:
    license_files = [path for path in files if path.name.upper().startswith("LICENSE") or path.name.upper() == "COPYING"]
    detected: str | None = None
    for path in license_files:
        detected = _detect_license(read_text(path))
        if detected:
            break

    findings: list[dict[str, str]] = []
    if not license_files:
        findings.append(
            {
                "severity": "high",
                "title": "No license file found",
                "detail": "The repository does not include a LICENSE or COPYING file.",
            }
        )
    elif not detected:
        findings.append(
            {
                "severity": "medium",
                "title": "License file could not be classified",
                "detail": f"Found {len(license_files)} license file(s), but none matched a known license pattern.",
            }
        )

    score = 100.0 if detected else 0.0
    if license_files and not detected:
        score = 50.0
    score = max(0.0, round(score, 2))

    metrics = {
        "license_files": len(license_files),
        "license_names": [path.name for path in license_files],
        "detected_license": detected,
        "license_present": bool(license_files),
    }
    return CheckResult(name="License compliance", score=score, metrics=metrics, findings=findings)


def _score_to_risk(score: float) -> str:
    if score >= 85:
        return "low"
    if score >= 70:
        return "moderate"
    if score >= 50:
        return "elevated"
    return "high"


def _build_section(result: CheckResult) -> str:
    metrics_lines = ["| Metric | Value |", "| --- | ---: |"]
    for key, value in result.metrics.items():
        metrics_lines.append(f"| {key.replace('_', ' ').title()} | `{json.dumps(value, ensure_ascii=False)}` |")

    findings = result.findings or [{"severity": "info", "title": "No major issues detected", "detail": "Nothing material stood out in this check."}]
    findings_lines = [f"- **{item['severity'].title()}** — {item['title']}: {item['detail']}" for item in findings]
    return "\n".join([
        "### Metrics",
        *metrics_lines,
        "",
        "### Findings",
        *findings_lines,
    ])


def _build_scorecard(results: list[CheckResult]) -> str:
    lines = ["| Check | Score | Key metric |", "| --- | ---: | --- |"]
    for result in results:
        if result.name == "Test coverage":
            key_metric = f"{result.metrics.get('coverage_percent', 0)}% coverage; {result.metrics.get('test_files', 0)} test files"
        elif result.name == "Code quality":
            key_metric = f"{result.metrics.get('function_count', 0)} functions; complexity max {result.metrics.get('max_cyclomatic_complexity', 0)}"
        elif result.name == "Security":
            key_metric = f"{result.metrics.get('secret_like_hits', 0)} secret-like hits"
        elif result.name == "Documentation":
            key_metric = f"{result.metrics.get('module_docstring_coverage_percent', 0)}% module docstrings"
        elif result.name == "CI/CD":
            key_metric = f"{result.metrics.get('workflow_files', 0)} workflow files; {result.metrics.get('test_job_count', 0)} test jobs"
        elif result.name == "Dependency health":
            key_metric = f"{result.metrics.get('manifest_files', 0)} manifest(s); {result.metrics.get('external_import_count', 0)} external imports"
        else:
            key_metric = f"{result.metrics.get('license_files', 0)} license file(s)"
        lines.append(f"| {result.name} | {result.score:.2f} | {key_metric} |")
    return "\n".join(lines)


def _summary_text(repo_info: dict[str, Any], results: list[CheckResult]) -> str:
    overall = repo_info["overall_score"]
    risk = _score_to_risk(overall)
    highlights = []
    for result in sorted(results, key=lambda item: item.score)[:3]:
        highlights.append(f"{result.name.lower()} scored {result.score:.1f}")
    highlight_text = "; ".join(highlights)
    return (
        f"Overall score: **{overall:.2f}/100** ({risk} risk). "
        f"The strongest signals are {highlight_text}."
    )


def build_report_and_metrics(repo_source: RepoSource, repo_root: Path, output_path: Path, json_output: Path) -> tuple[str, dict[str, Any]]:
    files = list_files(repo_root)
    python_files = [path for path in files if path.suffix.lower() == ".py"]
    source_files = [path for path in files if path.suffix.lower() in SOURCE_EXTENSIONS and path not in python_files or path.suffix.lower() == ".py" and path not in [p for p in python_files if p not in python_files]]
    source_files = [path for path in files if path.suffix.lower() in SOURCE_EXTENSIONS and not ("/tests/" in f"/{rel(path, repo_root)}/" or path.name.lower().startswith("test_") or path.name.lower().endswith("_test.py"))]
    git_commit = _git_output(repo_root, ["rev-parse", "HEAD"])
    git_branch = _git_output(repo_root, ["rev-parse", "--abbrev-ref", "HEAD"])
    git_remote = _git_output(repo_root, ["remote", "get-url", "origin"])

    checks = [
        analyze_python_code(repo_root, python_files),
        analyze_test_coverage(repo_root, python_files, source_files),
        analyze_security(repo_root, files),
        analyze_documentation(repo_root, files, python_files),
        analyze_cicd(repo_root, files),
        analyze_dependencies(repo_root, files, python_files),
        analyze_license(repo_root, files),
    ]

    overall_score = round(sum(check.score for check in checks) / len(checks), 2) if checks else 0.0
    metrics: dict[str, Any] = {
        "repo": {
            "source": repo_source.raw,
            "source_kind": repo_source.kind,
            "resolved_source": repo_source.resolved,
            "clone_path": str(repo_root),
            "commit": git_commit,
            "branch": git_branch,
            "remote": git_remote,
            "file_count": len(files),
            "python_file_count": len(python_files),
            "source_file_count": len(source_files),
            "generated_at": _now_iso(),
        },
        "summary": {
            "overall_score": overall_score,
            "risk_level": _score_to_risk(overall_score),
            "check_count": len(checks),
        },
        "checks": {check.name.lower().replace("/", "_").replace(" ", "_"): {
            "score": check.score,
            "metrics": check.metrics,
            "findings": check.findings,
        } for check in checks},
    }

    context = {
        "repo_url": repo_source.raw,
        "clone_source": repo_source.resolved,
        "commit": git_commit or "unknown",
        "branch": git_branch or "unknown",
        "generated_at": metrics["repo"]["generated_at"],
        "overall_score": f"{overall_score:.2f}",
        "risk_level": metrics["summary"]["risk_level"],
        "summary_text": _summary_text(metrics["summary"], checks),
        "scorecard_table": _build_scorecard(checks),
        "code_quality_section": _build_section(checks[0]),
        "test_coverage_section": _build_section(checks[1]),
        "security_section": _build_section(checks[2]),
        "documentation_section": _build_section(checks[3]),
        "cicd_section": _build_section(checks[4]),
        "dependency_section": _build_section(checks[5]),
        "license_section": _build_section(checks[6]),
        "next_steps": "\n".join(
            [
                "1. Review high-severity findings first.",
                "2. Decide whether to fix, document, or accept each risk.",
                "3. Re-run the audit after remediation to compare scores.",
            ]
        ),
    }

    template_text = TEMPLATE_PATH.read_text(encoding="utf-8")
    report = Template(template_text).safe_substitute(context)
    json_output.write_text(json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")
    output_path.write_text(report, encoding="utf-8")
    return report, metrics


def audit_repository(repo_input: str, output: Path, json_output: Path | None = None) -> tuple[str, dict[str, Any]]:
    repo_source = resolve_repo_source(repo_input)
    with tempfile.TemporaryDirectory(prefix="audit-pipeline-") as temp_dir:
        workdir = Path(temp_dir)
        cloned_repo = clone_repository(repo_source, workdir)
        metrics_json = json_output or output.with_suffix(DEFAULT_JSON_SUFFIX)
        return build_report_and_metrics(repo_source, cloned_repo, output, metrics_json)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit a GitHub repository and generate a markdown report plus JSON metrics.")
    parser.add_argument("--repo", required=True, help="GitHub repository URL or local path to audit")
    parser.add_argument("--output", required=True, help="Path to write the markdown report")
    parser.add_argument("--json-output", help="Optional path for the JSON metrics output")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        json_output = Path(args.json_output) if args.json_output else None
        if json_output is not None:
            json_output.parent.mkdir(parents=True, exist_ok=True)
        audit_repository(args.repo, output, json_output)
    except ValueError as exc:
        parser.error(str(exc))
    except (AuditError, OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        print(f"Audit failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

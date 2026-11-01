"""Guard architectural dependencies, including imports inside functions."""

import ast
from importlib.util import resolve_name
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "src" / "backlog_service"


def imported_modules(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:
                module = resolve_name("." * node.level + module, "backlog_service")
            yield module
            yield from (f"{module}.{alias.name}" for alias in node.names)


@pytest.mark.parametrize(
    "module,forbidden",
    [
        (
            "domain",
            {
                "fastapi",
                "starlette",
                "sqlalchemy",
                "httpx",
                "backlog_service.config",
                "backlog_service.database",
                "backlog_service.models",
                "backlog_service.repository",
                "backlog_service.project_access",
                "backlog_service.security",
                "backlog_service.service",
                "backlog_service.routes",
                "backlog_service.dependencies",
                "backlog_service.app",
                "backlog_service.cli",
            },
        ),
        ("service", {"fastapi", "starlette", "sqlalchemy", "backlog_service.models"}),
        (
            "routes",
            {
                "sqlalchemy",
                "backlog_service.models",
                "backlog_service.repository",
                "backlog_service.database",
                "backlog_service.project_access",
                "backlog_service.security",
                "backlog_service.config",
            },
        ),
    ],
)
def test_layer_does_not_import_forbidden_dependencies(module, forbidden):
    tree = ast.parse((SOURCE / f"{module}.py").read_text(encoding="utf-8"))
    violations = {
        dependency
        for dependency in imported_modules(tree)
        if any(dependency == item or dependency.startswith(item + ".") for item in forbidden)
    }
    assert violations == set(), f"{module} imports dependencies outside its layer: {violations}"


@pytest.mark.parametrize(
    "module", ["item_service", "service", "recommendation_service", "review_service"]
)
def test_application_services_do_not_access_orm_session(module):
    tree = ast.parse((SOURCE / f"{module}.py").read_text(encoding="utf-8"))
    imports = set(imported_modules(tree))
    assert not any(
        name.startswith(("fastapi", "sqlalchemy", "backlog_service.models")) for name in imports
    )
    assert not any(
        isinstance(node, ast.Attribute) and node.attr == "session" for node in ast.walk(tree)
    )


@pytest.mark.parametrize("module", ["item_routes", "recommendation_routes", "review_routes"])
def test_expanded_http_adapter_keeps_persistence_out(module):
    tree = ast.parse((SOURCE / f"{module}.py").read_text(encoding="utf-8"))
    assert not any(
        name.startswith(("sqlalchemy", "backlog_service.models", "backlog_service.item_repository"))
        for name in imported_modules(tree)
    )

"""安装包配置与运行/生产依赖边界。"""

from pathlib import Path
import tomllib


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"


def test_pyproject_discovers_packages_and_bundles_runtime_resources():
    config = tomllib.loads((BACKEND / "pyproject.toml").read_text(encoding="utf-8"))
    setuptools = config["tool"]["setuptools"]

    assert "application*" in setuptools["packages"]["find"]["include"]
    assert "common*" in setuptools["packages"]["find"]["include"]
    assert setuptools["package-data"]["prompts"] == ["*.md"]
    assert setuptools["package-data"]["thesis_docx"] == ["templates/*.docx"]
    assert config["tool"]["setuptools"]["dynamic"]["dependencies"]["file"] == [
        "requirements-runtime.txt"
    ]
    assert (BACKEND / "prompts" / "__init__.py").is_file()
    assert (BACKEND / "thesis_docx" / "templates" / "builtin_thesis_template.docx").is_file()


def test_optional_infrastructure_is_not_a_core_runtime_dependency():
    runtime = (BACKEND / "requirements-runtime.txt").read_text(encoding="utf-8")
    production = (BACKEND / "requirements-production.txt").read_text(encoding="utf-8")

    for dependency in ("psycopg2-binary", "asyncpg", "alembic", "redis", "APScheduler"):
        assert dependency not in runtime
        assert dependency in production

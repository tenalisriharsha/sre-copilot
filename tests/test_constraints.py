"""constraints.txt must pin every declared dependency within pyproject's bounds."""

import tomllib
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).parents[1]


def _declared() -> list[Requirement]:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    deps = list(project["dependencies"])
    for extra in project["optional-dependencies"].values():
        deps.extend(extra)
    return [Requirement(dep) for dep in deps]


def _pins() -> dict[str, list[str]]:
    pins: dict[str, list[str]] = {}
    for line in (ROOT / "constraints.txt").read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        req = Requirement(line)
        (version,) = [spec.version for spec in req.specifier if spec.operator == "=="]
        pins.setdefault(canonicalize_name(req.name), []).append(version)
    return pins


def test_every_constraint_is_an_exact_pin():
    assert _pins()


def test_every_declared_dependency_is_pinned_within_its_bounds():
    pins = _pins()
    for req in _declared():
        versions = pins.get(canonicalize_name(req.name))
        assert versions, f"{req.name} is missing from constraints.txt; regenerate it"
        for version in versions:
            assert req.specifier.contains(version, prereleases=True), (
                f"constraints.txt pins {req.name}=={version}, outside pyproject's {req.specifier}"
            )

import pytest
from pathlib import Path
import importlib.metadata
import tomllib
import re

def get_root_path():
    return Path(__file__).parent.parent

def _clean_string(req):
    """Normalizes a requirement string (lowercase and removes spaces)."""
    return req.strip().lower().replace(" ", "")

def parse_txt_requirements(file_path):
    """Extracts full requirement strings (name + version) from a .txt file."""
    if not file_path.exists():
        return set()
    packages = set()
    with open(file_path, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith(("#", "-e", "git+", "-r")):
                continue
            packages.add(_clean_string(line))
    return packages

def parse_toml_section(data, section_type="main"):
    """Extracts full requirement strings from pyproject.toml including optional sections."""
    packages = set()
    project = data.get("project", {})
    
    if section_type == "main":
        deps = project.get("dependencies", [])
    elif section_type == "optional":
        deps = project.get("optional-dependencies", {}).get("optionals", [])
    elif section_type == "dev":
        deps = project.get("optional-dependencies", {}).get("dev", [])
        if not deps:
            deps = data.get("dependency-groups", {}).get("dev", [])
            
    for req in deps:
        packages.add(_clean_string(req))
    return packages

def test_dependency_files_integrity():
    """1. Verifies that .txt files and pyproject.toml have identical names AND versions."""
    root = get_root_path()
    toml_path = root / "pyproject.toml"
    assert toml_path.exists(), "Missing pyproject.toml"

    with open(toml_path, "rb") as f:
        toml_data = tomllib.load(f)

    # Validate Production Sync (Main + Optionals)
    txt_main = parse_txt_requirements(root / "requirements.txt")
    toml_main = parse_toml_section(toml_data, "main") | parse_toml_section(toml_data, "optional")
    
    assert txt_main == toml_main, (
        f"Production version mismatch!\n"
        f"Only in TXT: {txt_main - toml_main}\n"
        f"Only in TOML: {toml_main - txt_main}"
    )

    # Validate Development Sync
    txt_dev = parse_txt_requirements(root / "requirements-dev.txt")
    toml_dev = parse_toml_section(toml_data, "dev")
    assert txt_dev == toml_dev, (
        f"Development version mismatch!\n"
        f"Only in TXT: {txt_dev - toml_dev}\n"
        f"Only in TOML: {toml_dev - txt_dev}"
    )

def test_environment_vs_toml():
    """2. Verifies that installed packages satisfy TOML requirements."""
    root = get_root_path()
    with open(root / "pyproject.toml", "rb") as f:
        data = tomllib.load(f)
    
    all_declared = (
        parse_toml_section(data, "main") | 
        parse_toml_section(data, "optional") | 
        parse_toml_section(data, "dev")
    )
    _verify_installation(all_declared, "TOML")

def test_environment_vs_requirements():
    """3. Verifies that installed packages satisfy .txt requirements."""
    root = get_root_path()
    all_txt_deps = (
        parse_txt_requirements(root / "requirements.txt") | 
        parse_txt_requirements(root / "requirements-dev.txt")
    )
    _verify_installation(all_txt_deps, "requirements.txt")

def _verify_installation(package_set, source_name):
    """Helper to check if declared versions match installed versions."""
    missing_or_wrong = []
    
    for req in package_set:
        # Split name from version
        parts = re.split(r'==|>=|~=|<=|>|<', req)
        raw_name = parts[0].strip()
        
        # CLEAN EXTRAS: "qrcode[pil]" -> "qrcode"
        clean_name = re.sub(r'\[.*\]', '', raw_name)
        
        try:
            installed_ver = importlib.metadata.version(clean_name)
            if "==" in req:
                expected_ver = req.split("==")[1].strip()
                if installed_ver != expected_ver:
                    missing_or_wrong.append(f"{clean_name} (Installed: {installed_ver}, Expected: {expected_ver})")
        except importlib.metadata.PackageNotFoundError:
            missing_or_wrong.append(f"{clean_name} (Not installed)")

    if missing_or_wrong:
        pytest.fail(f"Environment out of sync with {source_name}:\n" + "\n".join(missing_or_wrong))

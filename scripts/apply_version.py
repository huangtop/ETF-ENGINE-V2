from pathlib import Path

path = Path("pyproject.toml")
text = path.read_text(encoding="utf-8")
if 'version = "2.5.0"' in text:
    print("pyproject.toml is already version 2.5.0")
elif 'version = "2.1.0"' in text:
    path.write_text(
        text.replace('version = "2.1.0"', 'version = "2.5.0"', 1),
        encoding="utf-8",
    )
    print("Updated pyproject.toml to version 2.5.0")
else:
    raise SystemExit(
        "Expected current-main version 2.1.0 was not found. "
        "Review pyproject.toml manually."
    )

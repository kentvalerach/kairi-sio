# kairi_tree.py — ejecutar en C:\KAIRI-SIO\
import os
from pathlib import Path

root = Path("C:/KAIRI-SIO")
exclude = {'.git', '__pycache__', '.pytest_cache', 'node_modules', '.venv', 'venv'}

for path in sorted(root.rglob("*")):
    # Saltar solo directorios de sistema
    if any(part in exclude for part in path.parts):
        continue
    rel = path.relative_to(root)
    depth = len(rel.parts) - 1
    prefix = "  " * depth + ("📁 " if path.is_dir() else "📄 ")
    print(f"{prefix}{path.name}")
"""Cross-layer import boundary check for fault_mapper application layer."""
import ast
import pathlib

# ── Collect every public name exported from the domain layer ──
domain_dir = pathlib.Path("fault_mapper/domain")
domain_exports = set()
for f in domain_dir.glob("*.py"):
    if f.name == "__init__.py":
        continue
    tree = ast.parse(f.read_text())
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.ClassDef, ast.FunctionDef)):
            domain_exports.add(node.name)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    domain_exports.add(t.id)

print(f"Domain exports: {len(domain_exports)} names")

# ── Collect every name imported FROM domain by app files ──
app_dir = pathlib.Path("fault_mapper/application")
missing = []
found = set()
for f in sorted(app_dir.glob("*.py")):
    tree = ast.parse(f.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and "domain" in node.module:
            for alias in node.names:
                name = alias.name
                if name in domain_exports:
                    found.add(name)
                else:
                    missing.append((f.name, name))

print(f"App files import {len(found)} unique domain names")
if missing:
    print("MISSING from domain:")
    for fname, name in missing:
        print(f"   {fname} imports {name}")
else:
    print("All domain imports resolve.")

# ── Cross-check application-layer internal imports ──
app_exports = set()
for f in app_dir.glob("*.py"):
    tree = ast.parse(f.read_text())
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.ClassDef, ast.FunctionDef)):
            app_exports.add(node.name)

missing_app = []
for f in sorted(app_dir.glob("*.py")):
    tree = ast.parse(f.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and "application" in node.module:
            for alias in node.names:
                name = alias.name
                if name not in app_exports:
                    missing_app.append((f.name, name))

if missing_app:
    print("MISSING intra-app imports:")
    for fname, name in missing_app:
        print(f"   {fname} imports {name}")
else:
    print("All intra-application imports resolve.")

# ── Line counts ──
print("\nLine counts:")
total = 0
for f in sorted(app_dir.glob("*.py")):
    if f.name == "__init__.py":
        continue
    lines = len(f.read_text().splitlines())
    total += lines
    print(f"  {f.name:40s} {lines:4d}")
print(f"  {'TOTAL':40s} {total:4d}")

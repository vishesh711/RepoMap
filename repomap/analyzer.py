"""
Static analyzer: turns a Python codebase into a graph of facts.

Nodes  : functions, classes, methods, data structures, entry points
Edges  : calls, creates (instantiation), raises, uses (type reference),
         has (composition / fields), extends (inheritance),
         maybe_calls (name-based guess when the receiver type is unknown)

Everything here is deterministic. No AI is involved, so the map is only
ever as "creative" as the code itself.
"""

from __future__ import annotations

import ast
import os
from dataclasses import dataclass, field
from pathlib import Path

SKIP_DIRS = {
    ".git", ".hg", ".svn", "__pycache__", "node_modules", ".venv", "venv", "env",
    ".env", ".tox", ".nox", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    "build", "dist", "site-packages", ".eggs", ".idea", ".vscode",
}

DATA_DECORATORS = {"dataclass", "dataclasses.dataclass", "attr.s", "attrs", "define",
                   "frozen", "attr.define", "attrs.define", "attr.frozen"}
DATA_BASES = {"Enum", "IntEnum", "StrEnum", "Flag", "IntFlag", "NamedTuple", "TypedDict",
              "BaseModel", "Struct", "SQLModel", "Schema"}
CONTAINER_TYPES = {"list", "List", "set", "Set", "frozenset", "FrozenSet", "tuple", "Tuple",
                   "Sequence", "MutableSequence", "Iterable", "Iterator", "Collection",
                   "deque", "Deque", "Generator", "AsyncIterator", "AsyncIterable"}
MAPPING_TYPES = {"dict", "Dict", "Mapping", "MutableMapping", "DefaultDict", "defaultdict",
                 "OrderedDict"}

ROUTE_DECORATORS = {"get", "post", "put", "patch", "delete", "route", "websocket",
                    "api_route", "head", "options"}
CLI_DECORATORS = {"command", "group", "callback"}
TASK_DECORATORS = {"task", "shared_task", "periodic_task", "job", "scheduled_job"}
EVENT_DECORATORS = {"on_event", "listener", "subscriber", "event", "on_message", "handler"}

# Method names too generic to guess a target from the name alone.
GENERIC_NAMES = {
    "get", "set", "add", "append", "extend", "update", "pop", "remove", "clear", "copy",
    "items", "keys", "values", "join", "split", "strip", "format", "read", "write",
    "open", "close", "run", "start", "stop", "send", "load", "dump", "dumps", "loads",
    "save", "delete", "create", "find", "filter", "map", "sort", "index", "count",
    "insert", "replace", "lower", "upper", "encode", "decode", "render", "parse",
    "process", "execute", "call", "apply", "next", "reset", "init", "setup", "build",
    "validate", "check", "handle", "emit", "log", "info", "debug", "warning", "error",
    "exception", "flush", "connect", "commit", "fetch", "query", "match", "search",
    "__init__", "__call__", "__enter__", "__exit__", "__str__", "__repr__", "__eq__",
    "__hash__", "__len__", "__iter__", "__getitem__", "__setitem__", "__contains__",
}


@dataclass
class TypeRef:
    """A reference to a project class, optionally as the element of a container."""
    cls: str
    container: bool = False


@dataclass
class Symbol:
    id: str
    kind: str              # function | method | class | entry
    name: str
    qualname: str
    module: str
    file: str
    line: int
    end_line: int
    parent: str | None = None
    is_data: bool = False
    is_async: bool = False
    signature: str = ""
    doc: str = ""
    decorators: list[str] = field(default_factory=list)
    entry_reason: str | None = None
    bases: list[str] = field(default_factory=list)          # resolved class ids
    fields: dict[str, TypeRef] = field(default_factory=dict)  # attr -> type (classes)
    returns: list[TypeRef] = field(default_factory=list)    # functions
    params: dict[str, TypeRef] = field(default_factory=dict)  # functions
    ast_node: ast.AST | None = None


@dataclass
class Module:
    name: str
    path: Path
    rel: str
    tree: ast.Module
    lines: list[str]
    is_package: bool
    symbols: dict[str, str] = field(default_factory=dict)  # top-level name -> symbol id
    imports: dict[str, tuple] = field(default_factory=dict)
    # imports values: ("module", modname) or ("from", modname, name)


def _dotted(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else None
    if isinstance(node, ast.Call):
        return _dotted(node.func)
    return None


def _first_doc_line(node: ast.AST) -> str:
    try:
        doc = ast.get_docstring(node)  # type: ignore[arg-type]
    except TypeError:
        return ""
    if not doc:
        return ""
    return doc.strip().splitlines()[0][:200]


class Analyzer:
    def __init__(self, root: str | os.PathLike, include_tests: bool = False):
        self.root = Path(root).resolve()
        self.include_tests = include_tests
        self.modules: dict[str, Module] = {}
        self.symbols: dict[str, Symbol] = {}
        self.edges: dict[tuple[str, str, str], dict] = {}
        self.warnings: list[str] = []
        self._methods_by_name: dict[str, list[str]] = {}

    # ------------------------------------------------------------------ files
    def _iter_files(self):
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = sorted(d for d in dirnames
                                 if d not in SKIP_DIRS and not d.startswith(".")
                                 and not d.endswith(".egg-info"))
            if not self.include_tests and Path(dirpath).name in {"tests", "test", "testing"}:
                dirnames[:] = []
                continue
            for fn in sorted(filenames):
                if not fn.endswith(".py"):
                    continue
                if not self.include_tests and (fn.startswith("test_") or fn.endswith("_test.py")
                                               or fn == "conftest.py"):
                    continue
                yield Path(dirpath) / fn

    def _module_name(self, path: Path) -> tuple[str, bool]:
        rel = path.relative_to(self.root).with_suffix("")
        parts = list(rel.parts)
        # If the folder itself is a package, its files live under the package name
        if (self.root / "__init__.py").exists():
            parts = [self.root.name] + parts
        is_pkg = parts[-1] == "__init__"
        if is_pkg:
            parts = parts[:-1]
        if not parts:
            parts = [self.root.name]
        return ".".join(parts), is_pkg

    # --------------------------------------------------------------- pass 1
    def analyze(self) -> dict:
        for path in self._iter_files():
            try:
                src = path.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(src, filename=str(path))
            except SyntaxError as e:
                self.warnings.append(f"Skipped {path.relative_to(self.root)}: syntax error line {e.lineno}")
                continue
            name, is_pkg = self._module_name(path)
            self.modules[name] = Module(name, path, str(path.relative_to(self.root)), tree,
                                        src.splitlines(), is_pkg)

        for mod in self.modules.values():
            self._collect_imports(mod)
            self._collect_symbols(mod)

        for mod in self.modules.values():
            self._resolve_class_info(mod)

        # Names a top-level package re-exports from its __init__ are its public API.
        tops = [m for m in self.modules.values() if m.is_package and "." not in m.name]
        for mod in tops:
            for alias, imp in mod.imports.items():
                if imp[0] != "from" or alias.startswith("_"):
                    continue
                r = self.resolve_name(mod.name, alias)
                if r and r[0] == "sym":
                    s = self.symbols[r[1]]
                    if s.kind in ("function", "class") and not s.entry_reason:
                        s.entry_reason = f"public API (exported as {mod.name}.{alias})"

        for sym in list(self.symbols.values()):
            if sym.kind in ("function", "method", "entry"):
                self._analyze_body(sym)

        return self.to_graph()

    def _collect_imports(self, mod: Module):
        for node in ast.walk(mod.tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    if a.asname:
                        mod.imports[a.asname] = ("module", a.name)
                    else:
                        top = a.name.split(".")[0]
                        mod.imports[top] = ("module", top)
                        mod.imports[a.name] = ("module", a.name)
            elif isinstance(node, ast.ImportFrom):
                base = self._resolve_relative(mod, node.module, node.level)
                for a in node.names:
                    if a.name == "*":
                        continue
                    mod.imports[a.asname or a.name] = ("from", base, a.name)

    def _resolve_relative(self, mod: Module, name: str | None, level: int) -> str:
        if level == 0:
            return name or ""
        parts = mod.name.split(".")
        if not mod.is_package:
            parts = parts[:-1]
        if level > 1:
            parts = parts[: len(parts) - (level - 1)]
        if name:
            parts.append(name)
        return ".".join(parts)

    def _collect_symbols(self, mod: Module):
        for node in mod.tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                sid = self._add_function(mod, node, parent=None)
                mod.symbols[node.name] = sid
            elif isinstance(node, ast.ClassDef):
                sid = self._add_class(mod, node)
                mod.symbols[node.name] = sid
            elif isinstance(node, ast.If) and self._is_main_guard(node.test):
                sid = f"{mod.name}:__main__"
                end = getattr(node, "end_lineno", node.lineno)
                self.symbols[sid] = Symbol(
                    id=sid, kind="entry", name=f"run {Path(mod.rel).name}",
                    qualname="__main__", module=mod.name, file=mod.rel, line=node.lineno,
                    end_line=end, entry_reason="script entry (__main__ block)",
                    doc="Runs when this file is executed directly", ast_node=node)

    @staticmethod
    def _is_main_guard(test: ast.AST) -> bool:
        return (isinstance(test, ast.Compare) and isinstance(test.left, ast.Name)
                and test.left.id == "__name__" and len(test.comparators) == 1
                and isinstance(test.comparators[0], ast.Constant)
                and test.comparators[0].value == "__main__")

    def _signature(self, node) -> str:
        a = node.args
        parts = []
        for arg in a.posonlyargs + a.args:
            parts.append(arg.arg + (": " + ast.unparse(arg.annotation) if arg.annotation else ""))
        if a.vararg:
            parts.append("*" + a.vararg.arg)
        for arg in a.kwonlyargs:
            parts.append(arg.arg + (": " + ast.unparse(arg.annotation) if arg.annotation else ""))
        if a.kwarg:
            parts.append("**" + a.kwarg.arg)
        ret = f" -> {ast.unparse(node.returns)}" if node.returns else ""
        sig = f"{node.name}({', '.join(parts)}){ret}"
        return sig if len(sig) < 240 else sig[:237] + "..."

    def _add_function(self, mod: Module, node, parent: Symbol | None) -> str:
        qual = f"{parent.qualname}.{node.name}" if parent else node.name
        sid = f"{mod.name}:{qual}"
        decos = [_dotted(d) or ast.unparse(d)[:60] for d in node.decorator_list]
        start = min([node.lineno] + [d.lineno for d in node.decorator_list])
        sym = Symbol(
            id=sid, kind="method" if parent else "function", name=node.name, qualname=qual,
            module=mod.name, file=mod.rel, line=start,
            end_line=getattr(node, "end_lineno", node.lineno),
            parent=parent.id if parent else None, is_async=isinstance(node, ast.AsyncFunctionDef),
            signature=self._signature(node), doc=_first_doc_line(node), decorators=decos,
            ast_node=node)
        sym.entry_reason = self._entry_reason(sym, decos)
        self.symbols[sid] = sym
        if parent:
            self._methods_by_name.setdefault(node.name, []).append(sid)
        return sid

    @staticmethod
    def _entry_reason(sym: Symbol, decos: list[str]) -> str | None:
        for d in decos:
            last = d.split(".")[-1]
            if last in ROUTE_DECORATORS and "." in d:
                return f"HTTP route (@{d})"
            if last in CLI_DECORATORS and "." in d:
                return f"CLI command (@{d})"
            if last in TASK_DECORATORS:
                return f"background task (@{d})"
            if last in EVENT_DECORATORS:
                return f"event handler (@{d})"
        if sym.kind == "function" and sym.name == "main":
            return "main() function"
        return None

    def _add_class(self, mod: Module, node: ast.ClassDef) -> str:
        sid = f"{mod.name}:{node.name}"
        decos = [_dotted(d) or "" for d in node.decorator_list]
        start = min([node.lineno] + [d.lineno for d in node.decorator_list])
        sym = Symbol(id=sid, kind="class", name=node.name, qualname=node.name, module=mod.name,
                     file=mod.rel, line=start, end_line=getattr(node, "end_lineno", node.lineno),
                     doc=_first_doc_line(node), decorators=decos, ast_node=node)
        base_names = [(_dotted(b) or "").split(".")[-1] for b in node.bases]
        methods = [n for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        sym.is_data = (any(d in DATA_DECORATORS or d.split(".")[-1] == "dataclass" for d in decos)
                       or any(b in DATA_BASES for b in base_names))
        self.symbols[sid] = sym
        for m in methods:
            self._add_function(mod, m, parent=sym)
        return sid

    # ------------------------------------------------------------ resolution
    def find_module(self, name: str) -> str | None:
        if not name:
            return None
        if name in self.modules:
            return name
        cands = [m for m in self.modules if m.endswith("." + name)]
        return cands[0] if len(cands) == 1 else None

    def resolve_name(self, modname: str, name: str, depth: int = 0) -> tuple | None:
        """Resolve a bare name inside a module -> ("sym", id) | ("mod", modname)."""
        if depth > 6:
            return None
        mod = self.modules.get(modname)
        if not mod:
            return None
        if name in mod.symbols:
            return ("sym", mod.symbols[name])
        imp = mod.imports.get(name)
        if not imp:
            return None
        if imp[0] == "module":
            target = self.find_module(imp[1])
            return ("mod", target) if target else None
        _, src_mod, src_name = imp
        target = self.find_module(src_mod)
        if target:
            r = self.resolve_name(target, src_name, depth + 1)
            if r:
                return r
        sub = self.find_module(f"{src_mod}.{src_name}" if src_mod else src_name)
        if sub:
            return ("mod", sub)
        return None

    def resolve_dotted(self, modname: str, node: ast.AST) -> tuple | None:
        if isinstance(node, ast.Name):
            return self.resolve_name(modname, node.id)
        if isinstance(node, ast.Attribute):
            base = self.resolve_dotted(modname, node.value)
            if base and base[0] == "mod":
                return self.resolve_name(base[1], node.attr) or (
                    ("mod", self.find_module(f"{base[1]}.{node.attr}"))
                    if self.find_module(f"{base[1]}.{node.attr}") else None)
            if base and base[0] == "sym":
                sym = self.symbols[base[1]]
                if sym.kind == "class":
                    m = self.find_method(sym.id, node.attr)
                    if m:
                        return ("sym", m)
        return None

    def resolve_class(self, modname: str, node: ast.AST) -> str | None:
        r = self.resolve_dotted(modname, node)
        if r and r[0] == "sym" and self.symbols[r[1]].kind == "class":
            return r[1]
        return None

    def annotation_types(self, modname: str, ann: ast.AST | None) -> list[TypeRef]:
        """Project classes mentioned in a type annotation."""
        if ann is None:
            return []
        if isinstance(ann, ast.Constant) and isinstance(ann.value, str):
            try:
                ann = ast.parse(ann.value, mode="eval").body
            except SyntaxError:
                return []
        out: list[TypeRef] = []
        if isinstance(ann, (ast.Name, ast.Attribute)):
            c = self.resolve_class(modname, ann)
            if c:
                out.append(TypeRef(c))
        elif isinstance(ann, ast.Subscript):
            outer = (_dotted(ann.value) or "").split(".")[-1]
            inner = ann.slice
            args = list(inner.elts) if isinstance(inner, ast.Tuple) else [inner]
            if outer in MAPPING_TYPES and len(args) == 2:
                args = [args[1]]
            for a in args:
                for t in self.annotation_types(modname, a):
                    out.append(TypeRef(t.cls, t.container or outer in CONTAINER_TYPES
                                       or outer in MAPPING_TYPES))
            c = self.resolve_class(modname, ann.value)
            if c:
                out.append(TypeRef(c))
        elif isinstance(ann, ast.BinOp) and isinstance(ann.op, ast.BitOr):
            out += self.annotation_types(modname, ann.left)
            out += self.annotation_types(modname, ann.right)
        return out

    def find_method(self, class_id: str, name: str, seen=None) -> str | None:
        seen = seen or set()
        if class_id in seen:
            return None
        seen.add(class_id)
        cand = f"{class_id}.{name}"
        if cand in self.symbols:
            return cand
        for b in self.symbols[class_id].bases:
            r = self.find_method(b, name, seen)
            if r:
                return r
        return None

    def find_field(self, class_id: str, name: str, seen=None) -> TypeRef | None:
        seen = seen or set()
        if class_id in seen or class_id not in self.symbols:
            return None
        seen.add(class_id)
        cls = self.symbols[class_id]
        if name in cls.fields:
            return cls.fields[name]
        for b in cls.bases:
            r = self.find_field(b, name, seen)
            if r:
                return r
        return None

    def _resolve_class_info(self, mod: Module):
        for sym in [s for s in self.symbols.values() if s.module == mod.name]:
            node = sym.ast_node
            if sym.kind == "class":
                for b in node.bases:
                    c = self.resolve_class(mod.name, b)
                    if c and c != sym.id:
                        sym.bases.append(c)
                for stmt in node.body:
                    if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                        ts = self.annotation_types(mod.name, stmt.annotation)
                        if ts:
                            sym.fields[stmt.target.id] = ts[0]
            elif sym.kind in ("function", "method"):
                a = node.args
                for arg in a.posonlyargs + a.args + a.kwonlyargs:
                    ts = self.annotation_types(mod.name, arg.annotation)
                    if ts:
                        sym.params[arg.arg] = ts[0]
                sym.returns = self.annotation_types(mod.name, node.returns)

        # self.x = ... / self.x: T = ... inside methods become fields
        for sym in [s for s in self.symbols.values() if s.module == mod.name and s.kind == "method"]:
            cls = self.symbols[sym.parent]
            for stmt in ast.walk(sym.ast_node):
                target, ann, value = None, None, None
                if isinstance(stmt, ast.AnnAssign):
                    target, ann, value = stmt.target, stmt.annotation, stmt.value
                elif isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
                    target, value = stmt.targets[0], stmt.value
                if not (isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name)
                        and target.value.id == "self"):
                    continue
                if target.attr in cls.fields:
                    continue
                t = None
                if ann is not None:
                    ts = self.annotation_types(mod.name, ann)
                    t = ts[0] if ts else None
                if t is None and isinstance(value, ast.Call):
                    c = self.resolve_class(mod.name, value.func)
                    t = TypeRef(c) if c else None
                if t is None and isinstance(value, ast.Name) and value.id in sym.params:
                    t = sym.params[value.id]
                if t is None and isinstance(value, (ast.List, ast.ListComp)):
                    elt = value.elts[0] if isinstance(value, ast.List) and value.elts else (
                        value.elt if isinstance(value, ast.ListComp) else None)
                    if isinstance(elt, ast.Call):
                        c = self.resolve_class(mod.name, elt.func)
                        t = TypeRef(c, True) if c else None
                if t:
                    cls.fields[target.attr] = t

    # ------------------------------------------------------------ pass 2
    def _edge(self, src: str, dst: str, kind: str, line: int):
        if src == dst and kind != "calls":
            return
        key = (src, dst, kind)
        if key in self.edges:
            e = self.edges[key]
            e["count"] += 1
            e["line"] = min(e["line"], line)
        else:
            self.edges[key] = {"source": src, "target": dst, "type": kind, "line": line, "count": 1}

    def _analyze_body(self, sym: Symbol):
        node = sym.ast_node
        modname = sym.module
        owner_cls = sym.parent
        local: dict[str, TypeRef] = dict(sym.params)
        if owner_cls:
            local["self"] = TypeRef(owner_cls)
            local["cls"] = TypeRef(owner_cls)

        for t in sym.params.values():
            self._edge(sym.id, t.cls, "uses", sym.line)
        for t in sym.returns:
            self._edge(sym.id, t.cls, "uses", sym.line)

        def type_of(expr) -> TypeRef | None:
            if isinstance(expr, ast.Name):
                return local.get(expr.id)
            if isinstance(expr, ast.Call):
                if isinstance(expr.func, ast.Name) and expr.func.id == "super" and owner_cls:
                    b = self.symbols[owner_cls].bases
                    return TypeRef(b[0]) if b else None
                c = self.resolve_class(modname, expr.func)
                if c:
                    return TypeRef(c)
                target = resolve_callee(expr.func)
                if target and target[1] in self.symbols:
                    rets = self.symbols[target[1]].returns
                    return rets[0] if rets else None
                return None
            if isinstance(expr, ast.Attribute):
                base = type_of(expr.value)
                if base and not base.container:
                    return self.find_field(base.cls, expr.attr)
                return None
            if isinstance(expr, ast.Subscript):
                base = type_of(expr.value)
                if base and base.container:
                    return TypeRef(base.cls)
                return None
            if isinstance(expr, ast.Await):
                return type_of(expr.value)
            return None

        def resolve_callee(func) -> tuple[str, str] | None:
            """-> (edge_kind, target_id)"""
            if isinstance(func, ast.Name):
                if func.id in local:
                    return None
                r = self.resolve_name(modname, func.id)
                if r and r[0] == "sym":
                    k = "creates" if self.symbols[r[1]].kind == "class" else "calls"
                    return (k, r[1])
                return None
            if isinstance(func, ast.Attribute):
                if (isinstance(func.value, ast.Call) and isinstance(func.value.func, ast.Name)
                        and func.value.func.id == "super" and owner_cls):
                    for b in self.symbols[owner_cls].bases:
                        m = self.find_method(b, func.attr)
                        if m:
                            return ("calls", m)
                    return None
                base_t = type_of(func.value)
                if base_t and not base_t.container:
                    m = self.find_method(base_t.cls, func.attr)
                    return ("calls", m) if m else None
                r = self.resolve_dotted(modname, func)
                if r and r[0] == "sym":
                    k = "creates" if self.symbols[r[1]].kind == "class" else "calls"
                    return (k, r[1])
                # Last resort: a method name that exists exactly once in the project.
                if func.attr not in GENERIC_NAMES and not func.attr.startswith("__"):
                    cands = self._methods_by_name.get(func.attr, [])
                    if len(cands) == 1:
                        return ("maybe_calls", cands[0])
            return None

        body = node.body if isinstance(node, ast.If) else [node]
        # Walk statements in source order so local types are known before use.
        raised = set()
        for b in body:
            for r in ast.walk(b):
                if isinstance(r, ast.Raise) and r.exc is not None:
                    raised.add(id(r.exc))

        def pos(n):
            ref = n.target if isinstance(n, ast.comprehension) else n
            return (getattr(ref, "lineno", 0), getattr(ref, "col_offset", 0))
        ordered = sorted((n for b in body for n in ast.walk(b)
                          if hasattr(n, "lineno") or isinstance(n, ast.comprehension)), key=pos)
        for n in ordered:
            if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
                t = type_of(n.value)
                if t:
                    local[n.targets[0].id] = t
            elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
                ts = self.annotation_types(modname, n.annotation)
                if ts:
                    local[n.target.id] = ts[0]
            elif isinstance(n, (ast.For, ast.AsyncFor, ast.comprehension)) and isinstance(n.target, ast.Name):
                it = type_of(n.iter)
                if it and it.container:
                    local[n.target.id] = TypeRef(it.cls)
            elif isinstance(n, (ast.With, ast.AsyncWith)):
                for item in n.items:
                    if isinstance(item.optional_vars, ast.Name):
                        t = type_of(item.context_expr)
                        if t:
                            local[item.optional_vars.id] = t
            elif (isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)
                  and n.id not in local and n.id != "self"):
                r = self.resolve_name(modname, n.id)
                if r and r[0] == "sym" and self.symbols[r[1]].kind == "class" and r[1] != owner_cls:
                    self._edge(sym.id, r[1], "raises" if id(n) in raised else "uses", n.lineno)
            if isinstance(n, ast.Call):
                r = resolve_callee(n.func)
                if r:
                    kind, target = r
                    if kind == "creates" and id(n) in raised:
                        kind = "raises"
                    if target != sym.id or kind == "calls":
                        self._edge(sym.id, target, kind, n.lineno)

    # ------------------------------------------------------------ output
    def to_graph(self) -> dict:
        # Class-level structural edges
        for sym in self.symbols.values():
            if sym.kind == "class":
                for b in sym.bases:
                    self._edge(sym.id, b, "extends", sym.line)
                for fname, t in sym.fields.items():
                    if t.cls != sym.id:
                        self._edge(sym.id, t.cls, "has", sym.line)

        # Drop "uses" when a stronger relationship already exists between the pair
        strong = {(e["source"], e["target"]) for e in self.edges.values()
                  if e["type"] in ("creates", "calls", "raises")}
        edges = [e for e in self.edges.values()
                 if not (e["type"] == "uses" and (e["source"], e["target"]) in strong)]
        # A maybe_calls edge is redundant if a definite call exists
        edges = [e for e in edges
                 if not (e["type"] == "maybe_calls" and (e["source"], e["target"]) in strong)]

        # Field annotations as readable labels for classes
        nodes = []
        for sym in self.symbols.values():
            mod = self.modules[sym.module]
            lo, hi = sym.line, min(sym.end_line, sym.line + 150)
            src = "\n".join(mod.lines[lo - 1: hi])
            if sym.end_line > hi:
                src += f"\n# ... {sym.end_line - hi} more lines"
            data_kind = None
            if sym.kind == "class" and sym.is_data:
                kind = "data"
                bn = {(_dotted(b) or "").split(".")[-1] for b in sym.ast_node.bases}
                if bn & {"Enum", "IntEnum", "StrEnum", "Flag", "IntFlag"}:
                    data_kind = "enum"
                elif bn & {"BaseModel", "SQLModel", "Schema", "Struct"}:
                    data_kind = "model"
                elif "NamedTuple" in bn:
                    data_kind = "namedtuple"
                elif "TypedDict" in bn:
                    data_kind = "typeddict"
                else:
                    data_kind = "dataclass"
            else:
                kind = sym.kind
            fields = []
            if sym.kind == "class":
                for stmt in sym.ast_node.body:
                    if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                        fields.append(f"{stmt.target.id}: {ast.unparse(stmt.annotation)}"[:80])
                    elif (isinstance(stmt, ast.Assign) and len(stmt.targets) == 1
                          and isinstance(stmt.targets[0], ast.Name) and sym.is_data):
                        fields.append(stmt.targets[0].id)
            nodes.append({
                "id": sym.id, "kind": kind, "name": sym.name, "qualname": sym.qualname,
                "module": sym.module, "file": sym.file, "line": sym.line, "end_line": sym.end_line,
                "parent": sym.parent, "signature": sym.signature, "doc": sym.doc,
                "decorators": sym.decorators, "entry": sym.entry_reason, "is_async": sym.is_async,
                "fields": fields[:30], "source": src, "data_kind": data_kind,
            })

        edges.sort(key=lambda e: (e["source"], e["line"]))
        stats = {
            "files": len(self.modules),
            "functions": sum(1 for n in nodes if n["kind"] == "function"),
            "classes": sum(1 for n in nodes if n["kind"] == "class"),
            "data": sum(1 for n in nodes if n["kind"] == "data"),
            "methods": sum(1 for n in nodes if n["kind"] == "method"),
            "entries": sum(1 for n in nodes if n["entry"]),
            "edges": len(edges),
            "lines": sum(len(m.lines) for m in self.modules.values()),
        }
        return {"root": self.root.name, "nodes": nodes, "edges": edges, "stats": stats,
                "warnings": self.warnings}

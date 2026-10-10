"""
Multi-language extractor built on tree-sitter.

One generic engine walks every syntax tree and records facts:
  * definitions  - functions, classes, methods, structs, interfaces, enums, traits
  * calls        - with the receiver chain (`this.repo.find`, `pkg.Func`, `Foo::new`)
  * creations    - `new Foo()`, `Foo{}`, `Foo { .. }`, `Foo.new`
  * type refs    - parameter / return / field types
  * bindings     - local variable and field types, used to resolve `x.method()`
  * imports      - which files a file depends on, and import aliases
  * entry points - main(), HTTP routes, framework conventions, top-level script code

A resolver then turns names into links, preferring the closest scope
(same class, same file, imported files, same package folder, unique name).
Per-language differences live in the LANGS table, not in separate analyzers.
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from .analyzer import GENERIC_NAMES, SKIP_DIRS

try:
    from tree_sitter_language_pack import get_parser
except ImportError:  # pragma: no cover
    get_parser = None

sys.setrecursionlimit(max(sys.getrecursionlimit(), 20000))

EXTRA_SKIP_DIRS = {"vendor", "third_party", "third-party", "out", "target", ".next", ".nuxt",
                   ".svelte-kit", "coverage", "bower_components", "Pods", ".gradle", "obj",
                   "bin", "__snapshots__", "generated", ".turbo", ".cache", "storybook-static",
                   ".output", "tmp", "public"}
TEST_DIRS = {"test", "tests", "__tests__", "spec", "specs", "testing", "e2e", "testdata", "fixtures"}
MAX_FILE_BYTES = 600_000


# --------------------------------------------------------------------------- languages
@dataclass
class Lang:
    name: str                      # tree-sitter grammar name
    label: str                     # what people call it
    exts: tuple
    defs: dict                     # node type -> (kind, data_kind)
    calls: dict                    # node type -> how to read the callee
    implicit_this: bool = False    # bare `foo()` may mean this.foo()
    test_file: str = r"$^"         # regex on the file name


FUNC_VALUES = {"arrow_function", "function_expression", "function", "generator_function"}
ANON_FUNCS = FUNC_VALUES | {"func_literal", "closure_expression", "lambda_expression",
                            "anonymous_function", "anonymous_function_creation_expression",
                            "do_block", "block", "lambda", "anonymous_method_expression"}

JS_DEFS = {
    "function_declaration": ("function", None), "generator_function_declaration": ("function", None),
    "class_declaration": ("class", None), "abstract_class_declaration": ("class", None),
    "interface_declaration": ("data", "interface"), "type_alias_declaration": ("data", "type"),
    "enum_declaration": ("data", "enum"), "method_definition": ("method", None),
    "variable_declarator": ("function?", None), "public_field_definition": ("method?", None),
    "field_definition": ("method?", None), "assignment_expression": ("function=", None),
    "pair": ("function:", None),
}
JS_CALLS = {"call_expression": "function", "new_expression": "new:constructor",
            "jsx_opening_element": "render:name", "jsx_self_closing_element": "render:name"}

LANGS = [
    Lang("javascript", "JavaScript", (".js", ".jsx", ".mjs", ".cjs"), JS_DEFS, JS_CALLS,
         test_file=r"\.(test|spec)\.[cm]?jsx?$"),
    Lang("typescript", "TypeScript", (".ts", ".mts", ".cts"), JS_DEFS, JS_CALLS,
         test_file=r"(\.(test|spec)\.[cm]?ts$|\.d\.ts$)"),
    Lang("tsx", "TypeScript", (".tsx",), JS_DEFS, JS_CALLS, test_file=r"\.(test|spec)\.tsx$"),
    Lang("go", "Go", (".go",), {
        "function_declaration": ("function", None), "method_declaration": ("method", None),
        "type_spec": ("type?", None),
    }, {"call_expression": "function", "composite_literal": "new:type"}, test_file=r"_test\.go$"),
    Lang("java", "Java", (".java",), {
        "class_declaration": ("class", None), "interface_declaration": ("data", "interface"),
        "enum_declaration": ("data", "enum"), "record_declaration": ("data", "record"),
        "method_declaration": ("method", None), "constructor_declaration": ("method", None),
    }, {"method_invocation": "object+name", "object_creation_expression": "new:type"},
        implicit_this=True, test_file=r"(Test|Tests|IT)\.java$"),
    Lang("csharp", "C#", (".cs",), {
        "class_declaration": ("class", None), "struct_declaration": ("struct", None),
        "interface_declaration": ("data", "interface"), "record_declaration": ("data", "record"),
        "enum_declaration": ("data", "enum"), "method_declaration": ("method", None),
        "constructor_declaration": ("method", None),
    }, {"invocation_expression": "function", "object_creation_expression": "new:type"},
        implicit_this=True, test_file=r"Tests?\.cs$"),
    Lang("rust", "Rust", (".rs",), {
        "function_item": ("function", None), "struct_item": ("struct", None),
        "enum_item": ("data", "enum"), "trait_item": ("data", "trait"), "impl_item": ("impl", None),
    }, {"call_expression": "function", "struct_expression": "new:name"}),
    Lang("c", "C", (".c", ".h"), {
        "function_definition": ("function", None), "struct_specifier": ("struct", None),
        "enum_specifier": ("data", "enum"), "union_specifier": ("struct", None),
    }, {"call_expression": "function"}),
    Lang("cpp", "C++", (".cpp", ".cc", ".cxx", ".hpp", ".hh", ".hxx"), {
        "function_definition": ("function", None), "struct_specifier": ("struct", None),
        "class_specifier": ("class", None), "enum_specifier": ("data", "enum"),
        "union_specifier": ("struct", None),
    }, {"call_expression": "function", "new_expression": "new:type"}, implicit_this=True,
        test_file=r"_test\.(cc|cpp)$"),
    Lang("ruby", "Ruby", (".rb",), {
        "method": ("function", None), "singleton_method": ("method", None),
        "class": ("class", None), "module": ("class", "module"),
    }, {"call": "receiver+method"}, implicit_this=True, test_file=r"_(spec|test)\.rb$"),
    Lang("php", "PHP", (".php",), {
        "function_definition": ("function", None), "class_declaration": ("class", None),
        "interface_declaration": ("data", "interface"), "trait_declaration": ("class", "trait"),
        "enum_declaration": ("data", "enum"), "method_declaration": ("method", None),
    }, {"function_call_expression": "function", "member_call_expression": "object+name",
        "nullsafe_member_call_expression": "object+name", "scoped_call_expression": "scope+name",
        "object_creation_expression": "new:child"}, test_file=r"Test\.php$"),
]
EXT_LANG = {e: l for l in LANGS for e in l.exts}

# Leaves that name something
NAME_LEAVES = {"identifier", "property_identifier", "field_identifier", "type_identifier",
               "constant", "name", "namespace_identifier", "package_identifier",
               "shorthand_property_identifier", "private_property_identifier",
               "statement_identifier", "primitive_type", "predefined_type"}
SELF_WORDS = {"this", "self", "base", "super", "$this", "Self"}
# member-access node -> (object field, property field)
MEMBER_NODES = {
    "member_expression": ("object", "property"), "selector_expression": ("operand", "field"),
    "field_expression": ("value|argument", "field"), "field_access": ("object", "field"),
    "member_access_expression": ("expression|object", "name"), "scoped_identifier": ("path", "name"),
    "qualified_identifier": ("scope", "name"), "scope_resolution": ("scope", "name"),
    "nullsafe_member_access_expression": ("object", "name"), "optional_chain": ("", ""),
    "qualified_type": ("package", "name"), "generic_type": ("type", ""),
}
TYPE_FIELDS = {"type", "returns", "result", "return_type"}
DECL_NODES = {
    "required_parameter", "optional_parameter", "variable_declarator", "parameter_declaration",
    "short_var_declaration", "var_spec", "formal_parameter", "local_variable_declaration",
    "field_declaration", "public_field_definition", "parameter", "variable_declaration",
    "let_declaration", "simple_parameter", "property_declaration", "assignment_expression",
    "assignment", "declaration", "property_signature", "property_promotion_parameter",
    "self_parameter", "const_spec",
}
FIELD_NODES = {"public_field_definition", "field_definition", "property_signature", "field_declaration",
               "property_declaration", "enum_assignment", "enumerator", "enum_variant", "enum_constant",
               "enum_member_declaration", "enum_case", "record_component", "const_declaration"}
ENUM_BODIES = {"enum_body", "enumerator_list", "enum_variant_list", "enum_member_declaration_list"}
CREATE_NODES = {"new_expression", "object_creation_expression", "composite_literal", "struct_expression"}
EXTENDS_NODES = {"class_heritage", "extends_clause", "implements_clause", "superclass", "super_interfaces",
                 "base_class_clause", "base_list", "base_clause", "class_interface_clause",
                 "extends_interfaces", "trait_bounds"}
COMMENT_NODES = {"comment", "line_comment", "block_comment"}
ROUTE_VERBS = {"get", "post", "put", "delete", "patch", "all", "route", "handle", "handlefunc",
               "options", "head", "any", "match", "del"}
ANNOTATION_ROUTE = re.compile(
    r"@?\b((Get|Post|Put|Delete|Patch|Request|All|Head|Options)(Mapping)?|Http(Get|Post|Put|Delete|Patch)|"
    r"Route|Scheduled|KafkaListener|RabbitListener|EventListener|EventPattern|MessagePattern|Cron|"
    r"SqsListener|JmsListener|tokio::main|actix_web::main|launch|get|post|put|delete|patch)\b\s*(\(|$|\])")
MAIN_NAMES = {"main", "Main"}


@dataclass
class Sym:
    id: str
    kind: str
    name: str
    qualname: str
    file: str
    lang: str
    line: int
    end_line: int
    parent: str | None = None
    parent_name: str | None = None
    data_kind: str | None = None
    label: str | None = None
    entry: str | None = None
    doc: str = ""
    signature: str = ""
    decorators: list = field(default_factory=list)
    fields: list = field(default_factory=list)
    field_types: dict = field(default_factory=dict)
    locals: dict = field(default_factory=dict)
    is_async: bool = False
    explicit_methods: int = 0
    scope_cls: str | None = None   # class whose `this` a route handler closes over


@dataclass
class FileFacts:
    rel: str
    lang: Lang
    lines: list
    imports: set = field(default_factory=set)    # resolved repo-relative files
    raw_imports: list = field(default_factory=list)  # (spec, alias, orig_name)
    aliases: dict = field(default_factory=dict)  # alias -> (spec, orig name or None)
    pkg_aliases: set = field(default_factory=set)
    top_level: dict = field(default_factory=dict)  # name -> sym id


def _text(node, src: bytes) -> str:
    return src[node.start_byte:node.end_byte].decode("utf-8", "replace")


class Polyglot:
    def __init__(self, root: str | os.PathLike, include_tests: bool = False):
        self.root = Path(root).resolve()
        self.include_tests = include_tests
        self.files: dict[str, FileFacts] = {}
        self.syms: dict[str, Sym] = {}
        self.raw_calls: list = []      # (owner, form, chain, line, file)
        self.raw_types: list = []      # (owner, name, rel, line, file)
        self.raw_extends: list = []    # (cls, name, file)
        self.edges: dict = {}
        self.warnings: list = []
        self.lang_stats: dict = {}
        self._route_n = 0

    # ------------------------------------------------------------------- files
    def iter_files(self):
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = sorted(
                d for d in dirnames
                if d not in SKIP_DIRS and d not in EXTRA_SKIP_DIRS and not d.startswith(".")
                and not d.endswith(".egg-info")
                and (self.include_tests or d not in TEST_DIRS))
            for fn in sorted(filenames):
                lang = EXT_LANG.get(Path(fn).suffix)
                if not lang:
                    continue
                if fn.endswith((".min.js", ".bundle.js", ".map")) or ".generated." in fn:
                    continue
                if not self.include_tests and re.search(lang.test_file, fn):
                    continue
                p = Path(dirpath) / fn
                try:
                    if p.stat().st_size > MAX_FILE_BYTES:
                        self.warnings.append(f"Skipped {p.relative_to(self.root)}: file too large")
                        continue
                except OSError:
                    continue
                yield p, lang

    def analyze(self) -> dict:
        if get_parser is None:
            return self._empty("tree-sitter-language-pack is not installed")
        parsers = {}
        for path, lang in self.iter_files():
            rel = path.relative_to(self.root).as_posix()
            try:
                src = path.read_bytes()
            except OSError:
                continue
            lines = src.decode("utf-8", "replace").splitlines()
            if lines and sum(len(l) for l in lines) / len(lines) > 400:
                self.warnings.append(f"Skipped {rel}: looks minified")
                continue
            if lang.name not in parsers:
                try:
                    parsers[lang.name] = get_parser(lang.name)
                except Exception as e:  # grammar download can fail offline
                    self.warnings.append(f"No {lang.label} parser available: {e}")
                    parsers[lang.name] = None
            parser = parsers[lang.name]
            if parser is None:
                continue
            tree = parser.parse(src)
            ff = FileFacts(rel, lang, lines)
            self.files[rel] = ff
            st = self.lang_stats.setdefault(lang.label, {"files": 0, "lines": 0})
            st["files"] += 1
            st["lines"] += len(lines)
            self._walk(tree.root_node, src, ff, {"cls": None, "fn": None, "impl": None})
        self._resolve_imports()
        self._attach_methods()
        self._classify()
        self._resolve()
        return self.to_graph()

    def _empty(self, why):
        self.warnings.append(why)
        return self.to_graph()

    # ------------------------------------------------------------------- walking
    def _walk(self, node, src, ff: FileFacts, ctx):
        t = node.type
        lang = ff.lang
        if t in COMMENT_NODES:
            return
        spec = lang.defs.get(t)
        if spec and not ctx["fn"]:
            sym, newctx = self._definition(node, src, ff, ctx, spec)
            if newctx is not None:
                for c in node.children:
                    self._walk(c, src, ff, newctx)
                return
        if self._facts(node, src, ff, ctx) == "skip":
            return
        for c in node.children:
            self._walk(c, src, ff, ctx)

    def _name_of(self, node, src, lang):
        n = node.child_by_field_name("name")
        if n is None and node.type == "function_definition":
            d = node.child_by_field_name("declarator")
            while d is not None and d.type not in ("function_declarator",):
                d = d.child_by_field_name("declarator")
            if d is not None:
                n = d.child_by_field_name("declarator")
        if n is None and node.type in ("struct_specifier", "enum_specifier", "union_specifier"):
            p = node.parent
            if p is not None and p.type == "type_definition":
                n = p.child_by_field_name("declarator")
        if n is None:
            return None, None
        if n.type in ("qualified_identifier", "scope_resolution"):
            scope = n.child_by_field_name("scope")
            nm = n.child_by_field_name("name")
            return (_text(nm, src) if nm else _text(n, src)), (_text(scope, src).split("::")[-1] if scope else None)
        txt = _text(n, src)
        return txt.split("::")[-1].lstrip("$"), None

    def _definition(self, node, src, ff, ctx, spec):
        kind, data_kind = spec
        t = node.type
        lang = ff.lang

        if kind == "impl":  # Rust impl block: methods belong to the implemented type
            ty = node.child_by_field_name("type")
            tr = node.child_by_field_name("trait")
            tname = self._type_names(ty, src)[:1]
            if tname and tr is not None:
                for tn in self._type_names(tr, src)[:1]:
                    self.raw_extends.append((("impl", tname[0], ff.rel), tn, ff.rel))
            return None, {**ctx, "impl": tname[0] if tname else None}

        qual_override = None
        if kind in ("function=", "function:") or (kind == "method" and t == "method_definition" and not ctx["cls"]):
            # JS: app.handle = function () {}, module.exports = {...}, Foo.prototype.bar = ..., { key() {} }
            if kind == "function=":
                val, left = node.child_by_field_name("right"), node.child_by_field_name("left")
                segs = self._chain(left, src) if left is not None else None
            else:
                val = node.child_by_field_name("value") if kind == "function:" else node
                key = node.child_by_field_name("key") if kind == "function:" else node.child_by_field_name("name")
                if key is None or key.type not in ("property_identifier", "string", "identifier"):
                    return None, None
                owner = self._object_owner(node, src)
                segs = (owner or []) + [_text(key, src).strip("'\"")]
            if val is None or val.type not in FUNC_VALUES or not segs or "?" in segs:
                return None, None
            segs = [x for x in segs if x not in ("module", "exports", "prototype")]
            if not segs:
                fnm = val.child_by_field_name("name")
                segs = [_text(fnm, src) if fnm is not None else PurePosixPath(ff.rel).stem]
            if segs[0] in SELF_WORDS:
                return None, None
            kind, qual_override = "function", ".".join(segs)
        if kind in ("function?", "method?"):
            val = node.child_by_field_name("value")
            if val is None or val.type not in FUNC_VALUES:
                return None, None
            nm = node.child_by_field_name("name")
            if nm is None or nm.type not in ("identifier", "property_identifier", "private_property_identifier"):
                return None, None
            if kind == "method?" and not ctx["cls"]:
                return None, None
            if kind == "function?" and ctx["cls"]:
                return None, None
            kind = "method" if kind == "method?" else "function"
        if kind == "method" and t == "method_definition" and not ctx["cls"]:
            return None, None  # object-literal method

        if kind == "type?":  # Go type_spec
            ty = node.child_by_field_name("type")
            if ty is None:
                return None, None
            kind, data_kind = {"struct_type": ("struct", "struct"), "interface_type": ("data", "interface")}.get(
                ty.type, ("data", "type"))

        if qual_override:
            name, scope = qual_override.rsplit(".", 1)[-1], None
        else:
            name, scope = self._name_of(node, src, lang)
        if not name:
            return None, None
        if kind in ("struct",) and node.child_by_field_name("body") is None and t not in ("struct_item", "type_spec"):
            return None, None  # forward declaration / usage, not a definition
        if kind == "data" and t in ("enum_specifier",) and node.child_by_field_name("body") is None:
            return None, None

        parent_name = None
        if kind == "function":
            if ctx["cls"]:
                kind = "method"
            elif ctx["impl"]:
                kind, parent_name = "method", ctx["impl"]
            elif scope:
                kind, parent_name = "method", scope
            elif t == "function_definition":
                d = node.child_by_field_name("declarator")
                inner = d.child_by_field_name("declarator") if d is not None else None
                if inner is not None and inner.type == "field_identifier":
                    kind = "method"
        if t == "method_declaration" and lang.name == "go":
            recv = node.child_by_field_name("receiver")
            names = self._type_names(recv, src) if recv is not None else []
            parent_name = names[0] if names else None
        if kind == "method" and t == "singleton_method" and not ctx["cls"]:
            kind = "function"

        parent = ctx["cls"].id if (kind == "method" and ctx["cls"] and not parent_name) else None
        if kind == "method" and not parent and not parent_name:
            kind = "function"
        qual_parent = ctx["cls"].qualname if parent else parent_name
        qual = f"{qual_parent}.{name}" if (kind == "method" and qual_parent) else (
            f"{ctx['cls'].qualname}.{name}" if ctx["cls"] and kind != "method" else name)
        if qual_override:
            qual = qual_override
        sid = f"{ff.rel}:{qual}"
        if sid in self.syms:
            sid = f"{sid}#L{node.start_point[0] + 1}"
        sym = Sym(id=sid, kind=kind, name=name, qualname=qual, file=ff.rel, lang=lang.label,
                  line=node.start_point[0] + 1, end_line=node.end_point[0] + 1, parent=parent,
                  parent_name=parent_name, data_kind=data_kind)
        if lang.name == "ruby" and t == "module":
            sym.label = "module"
        if t in ("trait_declaration",):
            sym.label = "trait"
        sym.doc = self._doc(node, src)
        sym.signature = self._signature(node, src)
        sym.decorators = self._annotations(node, src)
        sym.is_async = bool(re.match(r"\s*(export\s+)?(default\s+)?(public\s+|private\s+|static\s+|protected\s+)*async\b",
                                     sym.signature))
        self._detect_entry(sym, node, src, ff)
        self.syms[sid] = sym
        if not ctx["cls"] and not ctx["impl"] and kind in ("function", "class", "struct", "data"):
            ff.top_level.setdefault(name, sid)
        if ctx["cls"] and kind == "method":
            ctx["cls"].explicit_methods += 1

        # inheritance
        for c in node.children:
            if c.type in EXTENDS_NODES or node.field_name_for_child(node.children.index(c)) == "superclass":
                for tn in self._type_names(c, src, all_leaves=True):
                    if tn not in SELF_WORDS:
                        self.raw_extends.append((sid, tn, ff.rel))
        # signature types
        if kind in ("function", "method"):
            for fld in ("parameters", "receiver", "return_type", "result", "returns", "type"):
                ch = node.child_by_field_name(fld)
                if ch is not None and fld != "receiver":
                    for tn in self._type_names(ch, src, all_leaves=fld == "parameters", typed_only=fld == "parameters"):
                        self.raw_types.append((sid, tn, "uses", sym.line, ff.rel))
            newctx = {**ctx, "fn": sym}
        else:
            newctx = {"cls": sym, "fn": None, "impl": None}
        return sym, newctx

    def _object_owner(self, node, src):
        """Name of the variable / export an object literal is assigned to."""
        obj = node.parent
        if obj is None or obj.type != "object":
            return None
        p = obj.parent
        if p is None:
            return None
        if p.type == "variable_declarator":
            n = p.child_by_field_name("name")
            return [_text(n, src)] if n is not None and n.type == "identifier" else None
        if p.type == "assignment_expression":
            return self._chain(p.child_by_field_name("left"), src)
        if p.type == "export_statement" or (p.type == "parenthesized_expression"):
            return []
        return None

    def _doc(self, node, src):
        prev = node.prev_named_sibling
        if prev is None and node.parent is not None and node.parent.type in ("export_statement", "decorated_definition"):
            prev = node.parent.prev_named_sibling
        if prev is not None and prev.type in COMMENT_NODES and prev.end_point[0] >= node.start_point[0] - 1:
            raw = _text(prev, src)
            lines = [re.sub(r"^\s*(/\*\*?|\*/|\*|//+|#+|///)\s?", "", l).strip() for l in raw.splitlines()]
            lines = [l for l in lines if l and not l.startswith("@") and l not in ("*/",)]
            return lines[0][:200] if lines else ""
        return ""

    def _signature(self, node, src):
        body = node.child_by_field_name("body")
        end = body.start_byte if body is not None else min(node.end_byte, node.start_byte + 240)
        sig = re.sub(r"\s+", " ", src[node.start_byte:end].decode("utf-8", "replace")).strip().rstrip("{:= ").strip()
        return sig if len(sig) < 240 else sig[:237] + "..."

    def _annotations(self, node, src):
        out = []
        cands = list(node.children)
        p = node.prev_named_sibling
        while p is not None and p.type in ("attribute_item", "decorator", "attribute_list", "annotation", "comment"):
            cands.append(p)
            p = p.prev_named_sibling
        if node.parent is not None and node.parent.type == "export_statement":
            cands += [c for c in node.parent.children if c.type == "decorator"]
        for c in cands:
            if c.type in ("modifiers",):
                for m in c.children:
                    if m.type in ("annotation", "marker_annotation"):
                        out.append(_text(m, src))
            elif c.type in ("decorator", "attribute_item", "attribute_list", "annotation", "marker_annotation"):
                out.append(_text(c, src))
        return [re.sub(r"\s+", " ", a)[:80] for a in out]

    def _detect_entry(self, sym, node, src, ff):
        for a in sym.decorators:
            m = ANNOTATION_ROUTE.search(a)
            if m and not re.search(r"\b(Test|test|derive|cfg)\b", a):
                arg = re.search(r"\(\s*[\"']([^\"']*)", a)
                sym.entry = f"handler {a.split('(')[0].strip('#[]@ ')}" + (f" {arg.group(1)}" if arg else "")
                if re.search(r"(Get|Post|Put|Delete|Patch|Request|Http|Route|get|post|put|delete|patch)", a):
                    sym.entry = "HTTP route " + sym.entry[len("handler "):]
                return
        if sym.name in MAIN_NAMES and sym.kind in ("function", "method"):
            sym.entry = "main() function"
            return
        if ff.lang.name == "go" and sym.name == "init" and sym.kind == "function":
            sym.entry = "init() runs at program start"
            return
        rel = ff.rel
        if ff.lang.name in ("javascript", "typescript", "tsx") and sym.kind == "function":
            exported_default = node.parent is not None and node.parent.type == "export_statement" and \
                _text(node.parent, src).lstrip().startswith("export default")
            if node.type == "variable_declarator":
                p = node.parent.parent if node.parent is not None else None
                exported_default = exported_default or False
                is_export = p is not None and p.type == "export_statement"
            else:
                is_export = node.parent is not None and node.parent.type == "export_statement"
            def url(p):
                return "/" + re.sub(r"\([^/]*\)/?", "", p).strip("/")
            if re.search(r"(^|/)app/(.+/)?route\.[cm]?[jt]sx?$", rel) and sym.name in (
                    "GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS") and is_export:
                sym.entry = f"HTTP route {sym.name} " + url(re.sub(r"(^|.*/)app/|/?route\.[cm]?[jt]sx?$", "", rel))
            elif exported_default and re.search(r"(^|/)app/(.+/)?(page|layout)\.[jt]sx?$", rel):
                kind_ = "layout" if re.search(r"layout\.[jt]sx?$", rel) else "page"
                sym.entry = f"{kind_} " + url(re.sub(r"(^|.*/)app/|/?(page|layout)\.[jt]sx?$", "", rel))
            elif exported_default and re.search(r"(^|/)pages/", rel):
                path = re.sub(r"(^|.*/)pages/|\.[jt]sx?$", "", rel).removesuffix("index")
                sym.entry = ("API route /" if path.startswith("api/") else "page /") + path

    # ----------------------------------------------------------------- facts
    def _owner(self, ctx, ff):
        if ctx["fn"]:
            return ctx["fn"].id
        if ctx["cls"]:
            return None
        sid = f"{ff.rel}:<run>"
        if sid not in self.syms:
            setup = ff.lang.name in ("go", "java", "csharp", "rust", "c", "cpp")
            self.syms[sid] = Sym(id=sid, kind="entry",
                                 name=f"{'setup in' if setup else 'run'} {PurePosixPath(ff.rel).name}",
                                 qualname="<run>", file=ff.rel, lang=ff.lang.label, line=1,
                                 end_line=len(ff.lines),
                                 entry="package-level setup" if setup else "top-level code in this file",
                                 doc="Code that runs when this file is loaded or executed")
        return sid

    def _facts(self, node, src, ff, ctx):
        t = node.type
        lang = ff.lang
        line = node.start_point[0] + 1

        # imports -------------------------------------------------------
        if t in ("import_statement", "export_statement") and lang.name in ("javascript", "typescript", "tsx"):
            source = node.child_by_field_name("source")
            if source is not None:
                spec = _text(source, src).strip("'\"`")
                ff.raw_imports.append(spec)
                for c in node.children:
                    if c.type == "import_clause":
                        for x in c.children:
                            if x.type == "identifier":
                                ff.aliases[_text(x, src)] = (spec, "default")
                            elif x.type == "namespace_import":
                                ids = [y for y in x.children if y.type == "identifier"]
                                if ids:
                                    ff.aliases[_text(ids[0], src)] = (spec, None)
                                    ff.pkg_aliases.add(_text(ids[0], src))
                            elif x.type == "named_imports":
                                for s in x.children:
                                    if s.type == "import_specifier":
                                        n = s.child_by_field_name("name")
                                        a = s.child_by_field_name("alias") or n
                                        if n is not None:
                                            ff.aliases[_text(a, src)] = (spec, _text(n, src))
            return
        if t == "import_spec" and lang.name == "go":
            path = node.child_by_field_name("path")
            if path is not None:
                spec = _text(path, src).strip('"`')
                nm = node.child_by_field_name("name")
                alias = _text(nm, src) if nm is not None else spec.rsplit("/", 1)[-1]
                ff.raw_imports.append(spec)
                ff.aliases[alias] = (spec, None)
                ff.pkg_aliases.add(alias)
            return
        if t == "import_declaration" and lang.name == "java":
            spec = re.sub(r"^import\s+(static\s+)?|;$", "", _text(node, src).strip()).strip()
            ff.raw_imports.append(spec)
            last = spec.rsplit(".", 1)[-1]
            if last != "*":
                ff.aliases[last] = (spec, last)
            return
        if t == "preproc_include":
            p = node.child_by_field_name("path")
            if p is not None and p.type == "string_literal":
                ff.raw_imports.append(_text(p, src).strip('"'))
            return
        if t == "call" and lang.name == "ruby":
            m = node.child_by_field_name("method")
            if m is not None and _text(m, src) in ("require_relative", "require"):
                args = node.child_by_field_name("arguments")
                if args is not None:
                    s = _text(args, src).strip("()'\" ")
                    ff.raw_imports.append(("./" if _text(m, src) == "require_relative" else "") + s)

        # bindings (variable / field types) ------------------------------
        if t in DECL_NODES:
            self._binding(node, src, ff, ctx)

        # fields shown on class / data boxes ---------------------------------
        if ctx["cls"] and not ctx["fn"] and (t in FIELD_NODES or (
                node.parent is not None and node.parent.type in ENUM_BODIES and node.is_named
                and t in ("property_identifier", "identifier", "enum_assignment"))):
            if len(ctx["cls"].fields) < 30:
                txt = re.sub(r"\s+", " ", _text(node, src).splitlines()[0]).strip().rstrip(";,")
                if txt and txt not in ctx["cls"].fields:
                    ctx["cls"].fields.append(txt[:80])
            for fld in ("type",):
                ch = node.child_by_field_name(fld)
                if ch is not None:
                    for tn in self._type_names(ch, src, all_leaves=True):
                        self.raw_types.append((ctx["cls"].id, tn, "has", line, ff.rel))
            if t == "property_declaration" or (t == "variable_declaration" and lang.name == "csharp"):
                pass

        # calls & creations ------------------------------------------------
        how = lang.calls.get(t)
        if how is None and lang.name == "ruby" and t == "identifier" and node.parent is not None \
                and node.parent.type in ("body_statement", "then", "else", "block_body", "do_block",
                                         "begin_block", "program") and ctx["fn"] is not None:
            how = "bare"
        if how is not None:
            if self._call(node, src, ff, ctx, how, line) == "skip":
                return "skip"

        # type references in bodies (Foo.CONSTANT, casts, generics) ------------
        if ctx["fn"] and t in ("type_identifier",) and node.parent is not None and node.parent.type not in (
                "composite_literal", "struct_expression", "new_expression", "object_creation_expression"):
            self.raw_types.append((ctx["fn"].id, _text(node, src), "uses", line, ff.rel))
        if ctx["fn"] and t in ("identifier", "constant", "name") and node.parent is not None:
            pt = node.parent.type
            if pt in MEMBER_NODES and node.parent.child_by_field_name(MEMBER_NODES[pt][0].split("|")[0]) == node:
                txt = _text(node, src)
                if txt[:1].isupper():
                    self.raw_types.append((ctx["fn"].id, txt, "uses", line, ff.rel))

    def _call(self, node, src, ff, ctx, how, line):
        lang = ff.lang
        chain, form = None, "call"
        if how == "bare":
            chain = [_text(node, src)]
        elif how.startswith("new:"):
            form = "new"
            fld = how.split(":")[1]
            target = node.child_by_field_name(fld) if fld != "child" else next(
                (c for c in node.named_children if c.type in ("name", "qualified_name")), None)
            if target is None:
                return
            names = self._type_names(target, src, all_leaves=True)
            chain = names[-1:] if names else None
        elif how.startswith("render:"):
            form = "render"
            target = node.child_by_field_name("name")
            if target is None:
                return
            txt = _text(target, src)
            if not txt[:1].isupper():
                return
            chain = txt.split(".")
        elif how == "function":
            fn = node.child_by_field_name("function")
            chain = self._chain(fn, src) if fn is not None else None
        elif how == "object+name":
            obj, nm = node.child_by_field_name("object"), node.child_by_field_name("name")
            if nm is None:
                return
            if obj is None:
                chain = [_text(nm, src)]
            else:
                base = self._chain(obj, src)
                chain = (base if base is not None else ["?"]) + [_text(nm, src)]
        elif how == "scope+name":
            sc, nm = node.child_by_field_name("scope"), node.child_by_field_name("name")
            if nm is None:
                return
            chain = [(_text(sc, src).split("\\")[-1] if sc is not None else "?"), _text(nm, src)]
        elif how == "receiver+method":
            rc, m = node.child_by_field_name("receiver"), node.child_by_field_name("method")
            if m is None:
                return
            mname = _text(m, src)
            if mname in ("require", "require_relative", "attr_accessor", "attr_reader", "include", "extend",
                         "private", "public", "protected", "puts", "raise"):
                return
            chain = (self._chain(rc, src) or ["?"]) + [mname] if rc is not None else [mname]
            if mname == "new" and rc is not None and len(chain) == 2:
                form, chain = "new", [chain[0]]
        if not chain or chain[-1] in ("", "?"):
            return

        # route registration: app.get("/x", handler) / r.GET("/x", h) / get "/x" do ... end
        verb = chain[-1].lower()
        if verb in ROUTE_VERBS and form == "call":
            args = node.child_by_field_name("arguments")
            if args is None:
                args = next((c for c in node.named_children if "argument" in c.type), None)
            argv = [a for a in (args.named_children if args is not None else [])]
            argv = [a.named_children[0] if a.type == "argument" and a.named_children else a for a in argv]
            if argv and "string" in argv[0].type:
                path = _text(argv[0], src).strip("'\"`")
                if path.startswith("/") or path == "" or path.startswith(":"):
                    block = node.child_by_field_name("block")
                    handlers = argv[1:] + ([block] if block is not None else [])
                    self._route(node, src, ff, ctx, chain[-1].upper(), path, handlers, line)
                    return "skip"

        owner = self._owner(ctx, ff)
        if owner is None:
            return
        self.raw_calls.append((owner, form, chain, line, ff.rel))

    def _route(self, node, src, ff, ctx, verb, path, handlers, line):
        self._route_n += 1
        name = f"{verb if verb not in ('HANDLEFUNC', 'HANDLE', 'ROUTE', 'MATCH', 'ANY', 'ALL') else 'ANY'} {path or '/'}"
        sid = f"{ff.rel}:route:{name}#L{line}"
        sym = Sym(id=sid, kind="entry", name=name, qualname=name, file=ff.rel, lang=ff.lang.label, line=line,
                  end_line=node.end_point[0] + 1, entry=f"HTTP route {name}",
                  doc="Route registered here", signature=re.sub(r"\s+", " ", _text(node, src))[:200])
        outer = ctx["fn"]
        if outer is not None:
            sym.locals = outer.locals          # handlers close over the enclosing scope
            sym.scope_cls = outer.parent or outer.scope_cls
        self.syms[sid] = sym
        rctx = {"cls": None, "fn": sym, "impl": None}
        for h in handlers:
            if h.type in ANON_FUNCS:
                for c in h.children:
                    self._walk(c, src, ff, rctx)
            else:
                ch = self._chain(h, src)
                if ch:
                    self.raw_calls.append((sid, "call", ch, line, ff.rel))
                else:
                    self._walk(h, src, ff, rctx)

    # ----------------------------------------------------------------- helpers
    def _chain(self, node, src):
        """`this.repo.find` -> ['this', 'repo', 'find'];  None if too dynamic."""
        if node is None:
            return None
        t = node.type
        if t in NAME_LEAVES or t in ("this", "self", "super", "base"):
            return [_text(node, src)]
        if t == "variable_name":
            return [_text(node, src).lstrip("$")]
        if t == "instance_variable":
            return ["self", _text(node, src).lstrip("@")]
        if t in ("generic_name", "generic_function"):
            return self._chain(node.named_children[0], src) if node.named_children else None
        if t in ("parenthesized_expression", "non_null_expression", "await_expression"):
            return self._chain(node.named_children[0], src) if node.named_children else None
        if t in MEMBER_NODES:
            of, pf = MEMBER_NODES[t]
            obj = None
            for f in of.split("|"):
                if f:
                    obj = node.child_by_field_name(f) or obj
            prop = node.child_by_field_name(pf) if pf else None
            if prop is None:
                return None
            pt = _text(prop, src)
            if obj is None:
                return [pt]
            base = self._chain(obj, src)
            return (base + [pt]) if base is not None else ["?", pt]
        return None

    def _type_names(self, node, src, all_leaves=False, typed_only=False):
        """Type names mentioned under a node (last segment of qualified names)."""
        if node is None:
            return []
        out = []

        def visit(n, in_type):
            t = n.type
            if t in ("type_identifier",) or (t in ("identifier", "constant", "name", "scoped_type_identifier")
                                            and in_type):
                txt = _text(n, src).split("::")[-1].split(".")[-1].split("\\")[-1]
                if txt and txt not in out:
                    out.append(txt)
                return
            for i, c in enumerate(n.children):
                fname = n.field_name_for_child(i)
                if typed_only:
                    visit(c, in_type or fname in TYPE_FIELDS)
                else:
                    visit(c, in_type or all_leaves or fname in TYPE_FIELDS or n.type in (
                        "superclass", "base_list", "base_clause", "class_interface_clause", "named_type",
                        "generic_type", "type_list", "qualified_type", "scoped_type_identifier",
                        "type_arguments", "type_argument_list"))

        visit(node, all_leaves and not typed_only)
        return [x for x in out if x not in ("var", "void", "int", "string", "bool", "any")]

    def _binding(self, node, src, ff, ctx):
        """Record `x -> TypeName` for locals/params (function) or fields (class)."""
        t = node.type
        lang = ff.lang
        names, tname = [], None
        if t == "self_parameter":
            return
        ty = node.child_by_field_name("type")
        if ty is not None and ty.type not in ("implicit_type",):
            tn = self._type_names(ty, src, all_leaves=True)
            tname = tn[0] if tn else None
        for f in ("name", "pattern", "left", "declarator"):
            ch = node.child_by_field_name(f)
            if ch is not None:
                names += self._decl_names(ch, src)
        for c in node.named_children:
            if c.type in ("variable_declarator", "property_element", "init_declarator") and not names:
                names += self._decl_names(c, src)
        if tname is None:
            val = None
            for f in ("value", "right"):
                val = node.child_by_field_name(f) or val
            if val is None:
                for c in node.named_children:
                    if c.type in ("variable_declarator", "init_declarator"):
                        val = c.child_by_field_name("value")
                        if val is None:
                            val = next((x for x in c.named_children if x.type in CREATE_NODES), None)
            if val is not None:
                if val.type == "expression_list" and val.named_children:
                    val = val.named_children[0]
                if val.type == "unary_expression" and val.named_children:
                    val = val.named_children[-1]
                if val.type in ("await_expression",) and val.named_children:
                    val = val.named_children[0]
                if val.type in CREATE_NODES:
                    fld = {"new_expression": "constructor" if lang.name in ("javascript", "typescript", "tsx") else "type",
                           "object_creation_expression": "type", "composite_literal": "type",
                           "struct_expression": "name"}[val.type]
                    tgt = val.child_by_field_name(fld) or next(
                        (c for c in val.named_children if c.type in ("name", "qualified_name")), None)
                    tn = self._type_names(tgt, src, all_leaves=True) if tgt is not None else []
                    tname = tn[0] if tn else None
                elif val.type in ("call_expression", "call"):
                    ch = self._chain(val.child_by_field_name("function") or val, src)
                    if val.type == "call":
                        rc, m = val.child_by_field_name("receiver"), val.child_by_field_name("method")
                        if rc is not None and m is not None and _text(m, src) == "new":
                            tname = _text(rc, src).split("::")[-1]
                    elif ch and len(ch) == 2 and ch[0][:1].isupper() and ch[1] in ("new", "default", "create", "from", "builder", "open", "connect"):
                        tname = ch[0]
                    elif ch:
                        tname = ("()", ch)  # resolve later through the callee's return type
        if not names or tname is None:
            return
        has_access = any(c.type in ("accessibility_modifier", "visibility_modifier") for c in node.children)
        for nm in names:
            if isinstance(nm, tuple):  # this.x / self.x / @x
                if ctx["cls"] is not None or (ctx["fn"] is not None and ctx["fn"].parent):
                    cls = ctx["cls"] or self.syms.get(ctx["fn"].parent)
                    if cls is not None and isinstance(tname, str):
                        cls.field_types.setdefault(nm[1], tname)
                continue
            if ctx["fn"] is not None:
                ctx["fn"].locals.setdefault(nm, tname)
                if has_access and t in ("required_parameter", "optional_parameter", "property_promotion_parameter") \
                        and ctx["fn"].parent and isinstance(tname, str):
                    cls = self.syms.get(ctx["fn"].parent)
                    if cls is not None:
                        cls.field_types.setdefault(nm, tname)
            elif ctx["cls"] is not None and isinstance(tname, str):
                ctx["cls"].field_types.setdefault(nm, tname)

    def _decl_names(self, node, src):
        t = node.type
        if t in ("identifier", "field_identifier", "property_identifier", "shorthand_property_identifier_pattern"):
            return [_text(node, src)]
        if t == "variable_name":
            return [_text(node, src).lstrip("$")]
        if t == "instance_variable":
            return [("self", _text(node, src).lstrip("@"))]
        if t in MEMBER_NODES:
            ch = self._chain(node, src)
            if ch and len(ch) == 2 and ch[0] in SELF_WORDS:
                return [("self", ch[1])]
            return []
        if t in ("expression_list", "variable_declarator", "pointer_declarator", "reference_declarator",
                 "init_declarator", "property_element", "mut_pattern", "array_declarator"):
            out = []
            for f in ("name", "declarator"):
                ch = node.child_by_field_name(f)
                if ch is not None:
                    return self._decl_names(ch, src)
            for c in node.named_children:
                out += self._decl_names(c, src)
                if t != "expression_list":
                    break
            return out
        return []

    # ----------------------------------------------------------------- resolution
    def _resolve_imports(self):
        files = set(self.files)
        by_base = {}
        by_dir = {}
        for f in files:
            p = PurePosixPath(f)
            by_base.setdefault(p.name, []).append(f)
            by_base.setdefault(p.stem, []).append(f)
            by_dir.setdefault(str(p.parent), []).append(f)
        self._by_dir = by_dir
        js_ext = ["", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", "/index.ts", "/index.tsx",
                  "/index.js", "/index.jsx"]

        def js_resolve(base_dir, spec):
            cands = []
            if spec.startswith("."):
                cands.append(os.path.normpath(os.path.join(base_dir, spec)))
            elif spec.startswith(("@/", "~/")):
                cands += ["src/" + spec[2:], spec[2:], "app/" + spec[2:]]
            elif spec.startswith("@") and spec.count("/") >= 1:
                return None
            else:
                cands += [spec, "src/" + spec]
            for c in cands:
                c = c.replace("\\", "/").lstrip("./") if not c.startswith("..") else c
                for e in js_ext:
                    if c.endswith(".js") and e == "":
                        for alt in (c[:-3] + ".ts", c[:-3] + ".tsx"):
                            if alt in files:
                                return alt
                    if (c + e) in files:
                        return c + e
            return None

        self._alias_files = {}
        for rel, ff in self.files.items():
            base_dir = str(PurePosixPath(rel).parent)
            lname = ff.lang.name
            resolved = {}
            for spec in ff.raw_imports:
                targets = []
                if lname in ("javascript", "typescript", "tsx"):
                    r = js_resolve(base_dir, spec)
                    targets = [r] if r else []
                elif lname == "go":
                    dirs = [d for d in by_dir if d != "." and (spec.endswith("/" + d) or spec == d
                                                              or spec.endswith("/" + d.rsplit("/", 1)[-1]) and d.count("/") == 0)]
                    best = max(dirs, key=len) if dirs else None
                    targets = by_dir.get(best, []) if best else []
                    if not targets:
                        tail = spec.rsplit("/", 1)[-1]
                        cand = [d for d in by_dir if d.endswith("/" + tail) or d == tail]
                        if len(cand) == 1:
                            targets = by_dir[cand[0]]
                elif lname == "java":
                    last = spec.rsplit(".", 1)[-1]
                    if last == "*":
                        pkg = spec[:-2].replace(".", "/")
                        targets = [f for d, fs in by_dir.items() if d.endswith(pkg) for f in fs]
                    else:
                        path_tail = spec.replace(".", "/") + ".java"
                        targets = [f for f in by_base.get(last + ".java", []) if f.endswith(path_tail)] or \
                            by_base.get(last + ".java", [])[:1]
                elif lname in ("c", "cpp"):
                    name = PurePosixPath(spec).name
                    near = os.path.normpath(os.path.join(base_dir, spec))
                    hdrs = [near] if near in files else by_base.get(name, [])
                    targets = list(hdrs)
                    for h in hdrs:
                        stem = PurePosixPath(h).stem
                        targets += [f for f in by_base.get(stem, []) if f.endswith((".c", ".cc", ".cpp", ".cxx"))]
                elif lname == "ruby":
                    s = spec if spec.endswith(".rb") else spec + ".rb"
                    near = os.path.normpath(os.path.join(base_dir, s)) if spec.startswith("./") else None
                    targets = [near] if near and near in files else [
                        f for f in files if f.endswith("/" + s.lstrip("./")) or f == s.lstrip("./")][:1]
                for tg in targets:
                    if tg and tg != rel:
                        ff.imports.add(tg)
                resolved[spec] = [tg for tg in targets if tg]
            # alias -> files
            amap = {}
            for alias, (spec, orig) in ff.aliases.items():
                amap[alias] = (resolved.get(spec, []), orig)
            self._alias_files[rel] = amap

        # name indexes
        self.by_name: dict[str, list[str]] = {}
        for s in self.syms.values():
            self.by_name.setdefault(s.name, []).append(s.id)

    def _attach_methods(self):
        """Go/Rust/C++ methods declared outside their type: find the type."""
        for s in list(self.syms.values()):
            if s.kind != "method" or s.parent or not s.parent_name:
                continue
            cands = [i for i in self.by_name.get(s.parent_name, [])
                     if self.syms[i].kind in ("class", "struct", "data")]
            d = str(PurePosixPath(s.file).parent)
            pick = self._closest(cands, s.file, d)
            if pick:
                s.parent = pick
                self.syms[pick].explicit_methods += 1
            else:
                s.kind = "function" if not s.parent_name else "method"
                if not s.parent:
                    s.kind = "function"
                    s.name = s.name
        # rust: impl Trait for Type
        fixed = []
        for owner, tn, f in self.raw_extends:
            if isinstance(owner, tuple):
                cands = [i for i in self.by_name.get(owner[1], []) if self.syms[i].kind in ("class", "struct", "data")]
                pick = self._closest(cands, f, str(PurePosixPath(f).parent))
                if pick:
                    fixed.append((pick, tn, f))
            else:
                fixed.append((owner, tn, f))
        self.raw_extends = fixed

    def _classify(self):
        for s in self.syms.values():
            if s.kind == "struct":
                has_methods = s.explicit_methods > 0
                s.kind = "class" if has_methods else "data"
                if s.kind == "data":
                    s.data_kind = s.data_kind or "struct"
                else:
                    s.label = "struct"

    def _closest(self, cands, file, d):
        """Pick a candidate by scope: same file, imported files, same folder, unique."""
        cands = list(dict.fromkeys(cands))
        if not cands:
            return None
        if len(cands) == 1:
            return cands[0]
        same = [c for c in cands if self.syms[c].file == file]
        if len(same) == 1:
            return same[0]
        imp = self.files[file].imports if file in self.files else set()
        inimp = [c for c in cands if self.syms[c].file in imp]
        if len(inimp) == 1:
            return inimp[0]
        samedir = [c for c in cands if str(PurePosixPath(self.syms[c].file).parent) == d]
        if len(samedir) == 1:
            return samedir[0]
        return None

    def _type_id(self, name, file):
        if not name:
            return None
        cands = [i for i in self.by_name.get(name, []) if self.syms[i].kind in ("class", "data")]
        if not cands:
            return None
        amap = self._alias_files.get(file, {})
        if name in amap and amap[name][0]:
            orig = amap[name][1] or name
            via = [i for i in self.by_name.get(orig, []) if self.syms[i].kind in ("class", "data")
                   and self.syms[i].file in amap[name][0]]
            if len(via) == 1:
                return via[0]
        return self._closest(cands, file, str(PurePosixPath(file).parent))

    def _method(self, cls_id, name, seen=None):
        seen = seen or set()
        if cls_id in seen or cls_id not in self.syms:
            return None
        seen.add(cls_id)
        for i in self.by_name.get(name, []):
            s = self.syms[i]
            if s.parent == cls_id and s.kind == "method":
                return i
        for base in self._bases.get(cls_id, []):
            r = self._method(base, name, seen)
            if r:
                return r
        return None

    def _field_type(self, cls_id, fname, file, seen=None):
        seen = seen or set()
        if cls_id in seen or cls_id not in self.syms:
            return None
        seen.add(cls_id)
        tn = self.syms[cls_id].field_types.get(fname)
        if tn:
            return self._type_id(tn, self.syms[cls_id].file)
        for base in self._bases.get(cls_id, []):
            r = self._field_type(base, fname, file, seen)
            if r:
                return r
        return None

    def _return_type(self, fn_id):
        s = self.syms.get(fn_id)
        if not s:
            return None
        m = re.search(r"(\)\s*(:|->)\s*|\)\s+)(\*?&?\(?\s*)([A-Z][\w]*)", s.signature)
        if m:
            return self._type_id(m.group(4), s.file)
        return None

    def _edge(self, src, dst, kind, line):
        if not src or not dst or (src == dst and kind != "calls"):
            return
        key = (src, dst, kind)
        e = self.edges.get(key)
        if e:
            e["count"] += 1
            e["line"] = min(e["line"], line)
        else:
            self.edges[key] = {"source": src, "target": dst, "type": kind, "line": line, "count": 1}

    def _resolve(self):
        self._bases = {}
        for owner, tn, f in self.raw_extends:
            tid = self._type_id(tn, f)
            if tid and tid != owner and owner in self.syms:
                self._bases.setdefault(owner, []).append(tid)
                self._edge(owner, tid, "extends", self.syms[owner].line)

        methods_by_name = {}
        for s in self.syms.values():
            if s.kind == "method":
                methods_by_name.setdefault(s.name, []).append(s.id)
        funcs_by_name = {}
        for s in self.syms.values():
            if s.kind == "function":
                funcs_by_name.setdefault(s.name, []).append(s.id)

        def enclosing_class(owner):
            s = self.syms.get(owner)
            return (s.parent or s.scope_cls) if s else None

        def local_type(owner, name, file, depth=0):
            s = self.syms.get(owner)
            if not s:
                return None
            tn = s.locals.get(name)
            if tn is None:
                return None
            if isinstance(tn, tuple):  # x := makeThing()  -> callee return type
                if depth > 2 or (tn[1] and tn[1][0] == name):
                    return None
                fid = resolve_fn(owner, tn[1], file, depth + 1)
                return self._return_type(fid) if fid else None
            return self._type_id(tn, file)

        def receiver_type(owner, recv, file, depth=0):
            """-> ('class', id) | ('pkg', files) | None"""
            if not recv:
                return None
            head = recv[0]
            cur = None
            if head in SELF_WORDS:
                cls = enclosing_class(owner)
                if head in ("super", "base") and cls:
                    b = self._bases.get(cls, [])
                    cls = b[0] if b else None
                cur = cls
            else:
                cur = local_type(owner, head, file, depth)
                if cur is None:
                    amap = self._alias_files.get(file, {})
                    ff = self.files.get(file)
                    if head in amap and ff is not None and head in ff.pkg_aliases:
                        if len(recv) == 1:
                            return ("pkg", amap[head][0])
                        return None
                    cls = enclosing_class(owner)
                    if cls and head in self.syms[cls].field_types:  # implicit this.field (Java/C#/C++)
                        cur = self._field_type(cls, head, file)
                    elif head[:1].isupper():
                        tid = self._type_id(head, file)
                        if tid:
                            if len(recv) == 1:
                                return ("static", tid)
                            cur = tid
            for seg in recv[1:]:
                if cur is None:
                    return None
                cur = self._field_type(cur, seg, file)
            return ("class", cur) if cur else None

        implementors = {}
        for c, bs in self._bases.items():
            for b in bs:
                implementors.setdefault(b, []).append(c)

        def implementation(type_id, name):
            """Interface/abstract type with a single concrete implementation of `name`."""
            hits = []
            stack, seen = list(implementors.get(type_id, [])), set()
            while stack:
                c = stack.pop()
                if c in seen:
                    continue
                seen.add(c)
                m = next((i for i in self.by_name.get(name, []) if self.syms[i].parent == c), None)
                if m:
                    hits.append(m)
                stack += implementors.get(c, [])
            return hits[0] if len(hits) == 1 else None

        guessed = set()
        funcs_by_qual = {}
        for s_ in self.syms.values():
            if s_.kind == "function" and "." in s_.qualname:
                funcs_by_qual.setdefault(s_.qualname, []).append(s_.id)

        def qualified(owner, chain, file):
            """JS objects of functions: app.handle(), this.send() inside res.json."""
            names = []
            if chain[0] in SELF_WORDS:
                oq = self.syms[owner].qualname if owner in self.syms else ""
                if "." in oq:
                    names.append(oq.rsplit(".", 1)[0] + "." + ".".join(chain[1:]))
            else:
                names.append(".".join(chain))
                names.append(".".join(chain[-2:]))
            for q in names:
                c = funcs_by_qual.get(q, [])
                pick = self._closest(c, file, str(PurePosixPath(file).parent)) if c else None
                if pick:
                    return pick
            return None

        def resolve_fn(owner, chain, file, depth=0):
            name = chain[-1]
            recv = chain[:-1]
            s = self.syms.get(owner)
            lang = self.files[file].lang if file in self.files else None
            if not recv:
                cls = enclosing_class(owner)
                if cls and lang and lang.implicit_this:
                    m = self._method(cls, name)
                    if m:
                        return m
                ff = self.files.get(file)
                if ff and name in ff.top_level and self.syms[ff.top_level[name]].kind == "function":
                    return ff.top_level[name]
                amap = self._alias_files.get(file, {})
                if name in amap and amap[name][0]:
                    orig = amap[name][1]
                    tfiles = amap[name][0]
                    if orig == "default":
                        cands = [i for f in tfiles for i in self._defaults(f)]
                    else:
                        cands = [i for i in funcs_by_name.get(orig or name, []) if self.syms[i].file in tfiles]
                    if len(cands) == 1:
                        return cands[0]
                cands = funcs_by_name.get(name, [])
                return self._closest(cands, file, str(PurePosixPath(file).parent)) if cands else None
            rt = receiver_type(owner, recv, file, depth)
            if rt is None and depth == 0:
                q = qualified(owner, chain, file)
                if q:
                    return q
            if rt and rt[0] in ("class", "static"):
                m = self._method(rt[1], name)
                if m is None and depth == 0:
                    impl = implementation(rt[1], name)
                    if impl:
                        guessed.add((owner, impl))
                        return impl
                return m
            if rt and rt[0] == "pkg":
                cands = [i for i in funcs_by_name.get(name, []) + self.by_name.get(name, [])
                         if self.syms[i].file in rt[1] and self.syms[i].kind in ("function", "class", "data")]
                cands = list(dict.fromkeys(cands))
                return cands[0] if len(cands) == 1 else None
            return None

        for owner, form, chain, line, file in self.raw_calls:
            if owner not in self.syms:
                continue
            if form == "new":
                tid = self._type_id(chain[0], file)
                if tid:
                    self._edge(owner, tid, "creates", line)
                continue
            if form == "render":
                tgt = resolve_fn(owner, chain, file)
                if not tgt:
                    tid = self._type_id(chain[-1], file)
                    tgt = tid
                if tgt:
                    self._edge(owner, tgt, "calls", line)
                continue
            tgt = resolve_fn(owner, chain, file)
            if tgt:
                self._edge(owner, tgt, "maybe_calls" if (owner, tgt) in guessed else "calls", line)
                continue
            # Foo.new (Ruby), Foo::new (Rust): creation through a static call
            if len(chain) == 2 and chain[1] in ("new", "create", "default", "builder", "from") and chain[0][:1].isupper():
                tid = self._type_id(chain[0], file)
                if tid:
                    self._edge(owner, tid, "creates", line)
                    continue
            # Last resort: method name that exists once in the project
            name = chain[-1]
            if len(chain) > 1 and name not in GENERIC_NAMES and not name.startswith("_") and len(name) > 3:
                cands = methods_by_name.get(name, [])
                if len(cands) == 1:
                    self._edge(owner, cands[0], "maybe_calls", line)

        for owner, tn, rel, line, file in self.raw_types:
            if owner not in self.syms:
                continue
            tid = self._type_id(tn, file)
            if tid and tid != owner and tid != self.syms[owner].parent:
                self._edge(owner, tid, rel, line)

    def _defaults(self, file):
        out = []
        for s in self.syms.values():
            if s.file == file and s.kind in ("function", "class"):
                ff = self.files[file]
                line = ff.lines[s.line - 1] if s.line - 1 < len(ff.lines) else ""
                if "export default" in line:
                    out.append(s.id)
        return out

    # ----------------------------------------------------------------- output
    def to_graph(self) -> dict:
        strong = {(e["source"], e["target"]) for e in self.edges.values() if e["type"] in ("creates", "calls")}
        edges = [e for e in self.edges.values()
                 if not (e["type"] in ("uses", "maybe_calls") and (e["source"], e["target"]) in strong)]
        has_out = {e["source"] for e in edges}
        nodes = []
        keep = set()
        for s in self.syms.values():
            if s.kind == "entry" and s.qualname == "<run>" and s.id not in has_out:
                continue  # file with no top-level calls into the project
            keep.add(s.id)
        edges = [e for e in edges if e["source"] in keep and e["target"] in keep]
        for s in self.syms.values():
            if s.id not in keep:
                continue
            ff = self.files[s.file]
            lo = s.line
            hi = min(s.end_line, s.line + 100) if s.qualname != "<run>" else min(len(ff.lines), 60)
            src = "\n".join(ff.lines[lo - 1:hi])
            if s.end_line > hi and s.qualname != "<run>":
                src += f"\n… {s.end_line - hi} more lines"
            nodes.append({
                "id": s.id, "kind": s.kind, "name": s.name, "qualname": s.qualname, "module": s.file,
                "file": s.file, "line": s.line, "end_line": s.end_line, "parent": s.parent,
                "signature": s.signature, "doc": s.doc, "decorators": s.decorators, "entry": s.entry,
                "is_async": s.is_async, "fields": s.fields[:30] if s.kind in ("class", "data") else [],
                "source": src, "data_kind": s.data_kind if s.kind == "data" else None,
                "label": s.label, "lang": s.lang,
            })
        edges.sort(key=lambda e: (e["source"], e["line"]))
        return {"nodes": nodes, "edges": edges, "warnings": self.warnings, "languages": self.lang_stats}

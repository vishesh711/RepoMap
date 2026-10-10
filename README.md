# codemap

Turn any codebase into an interactive **storyline map**: where execution starts, what each function calls, which classes hold which methods, and which data structures everything touches.

Built for reading code you didn't write line by line, especially code an AI generated for you.

```bash
codemap https://github.com/owner/repo     # any public GitHub repo
codemap path/to/project                    # a folder on your machine
```

It writes one self-contained `codemap.html`. Open it in a browser; it works offline.

**Languages:** Python · TypeScript · JavaScript (incl. React/JSX) · Go · Java · C# · Rust · C · C++ · Ruby · PHP. Mixed-language repos are mapped together.

## Install

```bash
pip install git+https://github.com/OWNER/codemap
```

Python 3.10+. Language grammars come from `tree-sitter-language-pack` and are fetched on first use.

## What you get

- **Starting points**, detected automatically:
  - `main()`, `__main__` blocks and top-level script code
  - HTTP routes: Express, Fastify, Gin, net/http, Sinatra, Slim, Spring `@GetMapping`, ASP.NET `[HttpGet]`, NestJS `@Get`, FastAPI and Flask decorators
  - Next.js pages, layouts and `route.ts` handlers
  - CLI commands, background tasks
  - a package's public API, and anything nothing else calls
- **Flows**: pick a starting point and see only the code reachable from it, top to bottom in call order. Big flows open at a readable depth, about 60 symbols, which you can raise.
- **Classes as containers**: methods sit inside their class or struct. Data types (dataclasses, structs, interfaces, enums, records) show their fields.
- **Storyline**: a plain-language walkthrough generated from the graph, e.g. "`main()` creates `Inventory`, `Order` and `OrderItem`, then calls `validate_order()` and `process_order()`." Every name links back to the map.
- **Inspector**: click any box for its signature, location, source, and everything it calls, creates, uses or is used by. For GitHub repos there's a **view on GitHub** link pinned to the exact commit.
- **Search**, neighbors view, group by file, pan and zoom, light and dark themes.

## How it works

Everything is deterministic static analysis. No AI is involved, so the map can't invent connections that aren't in the code.

1. **Parse.** Python uses its own `ast` module. Every other language goes through tree-sitter.
2. **Extract symbols**: functions, classes, methods, structs, interfaces, enums, traits, entry points.
3. **Resolve links** by the closest scope: same class, same file, imported files, same package folder, then a unique name in the project. Receiver types come from:
   - parameter and return types
   - local variables (`const inv = new Inventory()`, `inv := NewInventory()`, `let inv = Inventory::new()`)
   - class and struct fields (`this.repo.find()`, `s.inv.Reserve()`)
   - inheritance
   - interfaces with a single implementation
4. **Lay out** with ELK's layered algorithm (bundled), with classes as compound nodes.

| Link | Meaning | Drawn as |
|---|---|---|
| calls | a function or method call (or a JSX component render) | solid blue |
| creates | instantiates a class or struct | solid teal |
| is made of | a field holds another type | dashed, diamond head |
| references type | appears in a signature or body | dotted gray |
| extends | inheritance / implements | hollow arrow |
| raises | `raise SomeError(...)` (Python) | dotted red, off by default |
| guessed call | receiver type unknown; method name unique in the project, or single interface implementation | dashed gray |

## Options

```
codemap TARGET [-o OUT.html] [--json graph.json] [--branch NAME] [--subdir PATH]
               [--include-tests] [--title TITLE] [--keep-clone]
```

- `TARGET` is a folder, a GitHub URL, or `owner/repo`. Private repos: clone them yourself and pass the folder.
- `--json` writes the raw graph (nodes, edges, source spans). Use it for CI checks, diffing two commits, or giving an LLM a grounded view of the code.
- Skipped by default: dependencies and build output (`node_modules`, `vendor`, `dist`, `target`, virtualenvs…), minified and very large files, and tests (`--include-tests` keeps them).

## Publish a map for any repo with GitHub Actions

This repo is also a GitHub Action. Copy [`docs/publish-to-pages.yml`](docs/publish-to-pages.yml) into another repo's `.github/workflows/`. Every push to `main` then regenerates its map and publishes it to GitHub Pages. Set **Settings → Pages → Source** to **GitHub Actions** first.

```yaml
- uses: actions/checkout@v4
- uses: OWNER/codemap@main
  with:
    output: codemap-site/index.html
```

## Known limits

Static analysis can't see everything a program does at runtime:

- Calls through untyped variables, reflection, dependency-injection containers, callbacks stored in data structures, or `getattr`-style dynamic access may be missing. Type annotations make the map more complete.
- Generic method names (`get`, `run`, `send`…) are never guessed, to avoid false links.
- Nested functions and closures are folded into the function that contains them.
- Python gets the deepest analysis. The other languages share one engine and are slightly less precise.

## Roadmap

- **Diff mode**: map two commits and show only what changed structurally ("this change added a call from `checkout()` into `PaymentService`").
- **Security overlay**: draw findings (secrets, unauthenticated routes, user input reaching SQL) on the same map.
- **Rules**: fail CI when a change breaks a project rule, such as a route without auth middleware.
- **AI narration**: an LLM explains a flow, citing only graph facts.
- Kotlin, Swift, Scala.

## Development

```bash
pip install -e ".[dev]"
pytest
codemap examples/shop -o shop.html
```

| File | Role |
|---|---|
| `codemap/analyzer.py` | Python analyzer (`ast`) |
| `codemap/polyglot.py` | multi-language engine (tree-sitter) |
| `codemap/scan.py` | runs both and merges the results |
| `codemap/template.html` | the viewer |
| `codemap/render.py` | bundles the viewer and graph into one page |
| `codemap/cli.py` | command line, cloning, GitHub links |

`tests/fixtures/` holds the same inventory example in TypeScript, Go, Java and Rust. Each test pins the links it must produce.

## License

The viewer bundles [elkjs](https://github.com/kieler/elkjs) 0.9.3 under the Eclipse Public License 2.0; see `codemap/vendor/`.

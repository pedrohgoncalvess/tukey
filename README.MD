# Tukey

[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue)](pyproject.toml)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-green)](LICENSE)

Understand a codebase through structured metrics and an interactive, offline code map.

Tukey is a static analysis CLI for **Python, Rust, Scala, Java, TypeScript,
JavaScript, and PHP**. It parses source files with Tree-sitter and produces a
versioned JSON report, with an optional self-contained HTML visualization.
The analyzed code is never executed.

The name honors **John Tukey** and his contributions to exploratory data analysis.

## Features

- Measure physical lines, nonblank lines, and bytes by file, declaration, and module.
- Discover classes, interfaces, traits, implementations, functions, and methods.
- Inspect signature type annotations and identify potentially unused imports.
- Explore local dependencies, module coupling, call graphs, and cyclomatic complexity.
- Find potentially unused files and declarations using references and entry points.
- Import existing Coverage.py JSON or LCOV reports without running tests.
- Navigate an offline HTML map with search, filters, zoom, and declaration details.
- Consume a documented JSON contract for integrations and custom reporting.

## Requirements

- An internet connection for installation. The installers set up
  [uv](https://docs.astral.sh/uv/getting-started/installation/) and Python **3.12**
  automatically when needed.
- Linux/macOS: a POSIX shell and `curl` or `wget`. Windows: PowerShell **5.1+**.
- GNU Make is optional; direct commands are provided throughout.

No compiler or runtime for the analyzed languages is required. The parser pack
is pinned to a version with bundled parsers; analysis works offline once its
dependencies have been installed.

## Installation

Install for your user account without administrator privileges or `sudo`.
The installers download the source from the repository's `main` branch, install
the CLI in an isolated environment, and configure your user's PATH. You do not
need Git, Make, or a preinstalled Python. The distribution is named `tukey-code`;
the command and Python package are `tukey`.

### Linux and macOS

Copy and run this command in your terminal:

```sh
curl -fsSL https://raw.githubusercontent.com/pedrohgoncalvess/tukey/main/install.sh -o install-tukey.sh && sh install-tukey.sh
```

Or use `wget`:

```sh
wget -q https://raw.githubusercontent.com/pedrohgoncalvess/tukey/main/install.sh -O install-tukey.sh && sh install-tukey.sh
```

Open a new terminal after installation, then run `tukey --help`. If your shell
configuration cannot be updated, the installer prints the directory to add to
your PATH. You can inspect the downloaded `install-tukey.sh` before running it.

### Windows

Paste the following into **PowerShell**:

```powershell
$installer = Join-Path $env:TEMP ("tukey-install-{0}.ps1" -f [guid]::NewGuid())
Invoke-WebRequest -Uri https://raw.githubusercontent.com/pedrohgoncalvess/tukey/main/install.ps1 -OutFile $installer -UseBasicParsing -ErrorAction Stop
powershell.exe -NoProfile -ExecutionPolicy Bypass -File $installer
```

The execution-policy override applies only to that installer process. You can
inspect the downloaded script before running the last line. Open a new terminal
after installation, then run `tukey --help`. Restart your terminal application
if it still has the old PATH.

### Install from a local checkout

If you have already cloned or downloaded this project, run from its root:

```sh
# Linux/macOS: install this checkout, including local changes.
sh install.sh .
```

```powershell
# Windows: install this checkout, including local changes.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -Source .
```

Both scripts accept a local source directory or source archive URL. For example,
you can replace `.` with an archive URL for a specific Git tag or commit.
Running an installer again reinstalls Tukey from the selected source. Without
an argument, it always downloads `main`, even when run from a local checkout.

### Manual installation with uv

If uv is already installed, clone the repository and run:

```sh
git clone https://github.com/pedrohgoncalvess/tukey.git
cd tukey
uv tool install --reinstall --python 3.12 .
uv tool update-shell
```

Open a new terminal to make `tukey` available on your PATH. Run the installation
command again after updating the checkout. Alternatively, use `make install`.

To run directly from the checkout:

```sh
uv sync --group dev
uv run tukey --help
```

### Uninstall

```sh
uv tool uninstall tukey-code
```

This removes Tukey's isolated environment and command. uv and any managed Python
installation remain available for other tools.

## Quick start

```sh
# Print a JSON report to standard output.
tukey /path/to/project

# Write JSON and an interactive HTML map.
tukey /path/to/project --output report.json --html report.html

# Analyze a single file or a path containing spaces.
tukey src/app.py
tukey "C:\my projects\app" -o report.json

# Exclude paths relative to the analysis root.
tukey . --exclude "tests/*" --exclude "generated/*" --html
```

Open the generated HTML file in a browser. It contains its own data and styles
and needs no server, CDN, or network connection. With `--html` and no filename,
Tukey writes `report.html` in the current directory. JSON still goes to stdout
unless `--output` is specified. Output directories must already exist, and JSON
and HTML must use different paths.

Progress logs are printed immediately to stderr while directories are scanned
and files are analyzed, including file counts, percentages, and final analysis
stages. JSON on stdout remains suitable for piping to other tools. Use `--quiet`
(or `-q`) to suppress progress logs; CLI errors are still printed.

See the checked-in [JSON example](docs/example-report.json) and
[HTML example](docs/example-report.html) (download and open locally).

### CLI options

| Option | Purpose |
| --- | --- |
| `path` | Required source file or project directory |
| `-o`, `--output FILE` | Write UTF-8 JSON instead of printing it |
| `--html [FILE]` | Also generate an offline HTML report |
| `--exclude GLOB` | Exclude a relative path pattern; repeatable |
| `--coverage FILE` | Import Coverage.py JSON or LCOV; detected by content |
| `--coverage-root DIR` | Base for coverage paths; defaults to the analyzed root |
| `--entry-point GLOB[#NAME]` | Set explicit usage entry points; repeatable |
| `--public-api GLOB[#NAME]` | Preserve API files or declarations; repeatable |
| `-q`, `--quiet` | Suppress progress logs on stderr |
| `--config FILE` | Load a YAML configuration preset |
| `--format json\|html\|both` | Select the report formats |
| `--output-dir DIR` | Create/use a report directory |
| `--ignore-dirs NAMES` | Ignore directory names at every depth; comma-separated, repeatable |
| `--ignore-extensions TYPES` | Ignore extensions, e.g. `.js,.ts`; comma-separated, repeatable |
| `--no-exclusion [PATTERN]` | Disable all built-in exclusions, or only matching default names |
| `--version` | Print the tool version |
| `--help` | Show command help |

Exit codes are `0` for success, `1` for a partial report with analysis diagnostics,
and `2` for invalid arguments, invalid coverage input, or output errors. An error
in one source file does not prevent analysis of the remaining files.

## YAML configuration presets

Copy [tukey.example.yaml](tukey.example.yaml) and run:

```sh
tukey --config tukey.example.yaml
tukey . --ignore-dirs "database, log, generated" --ignore-extensions ".js, .d.ts"
tukey --config tukey.example.yaml --output-dir custom-reports --format html
```

Presets support `path`, `format`, `output_dir`, `output` (JSON filename),
`html` (HTML filename or boolean), `exclude`, `ignore_dirs`, `ignore_extensions`,
`coverage`, `coverage_root`, `entry_point`, `public_api`, and `quiet`.
`no_exclusion` accepts `false` (keep defaults), `true` (disable all), or a string/list
of default names or glob patterns to disable selectively.
Unknown keys and invalid value types produce an error. A preset is loaded only
when `--config` is provided; without a source path, the default is the preset's
directory (or the current directory without a preset).

Paths in YAML are relative to the YAML file's directory. CLI paths are relative
to the current directory. When `output_dir` is set, relative `output` and `html`
filenames go inside it, and default to `report.json` and `report.html`.
The output directory is created automatically; other output parents must exist.
Without `output_dir` or `output`, JSON still goes to stdout. `format: html`
generates only HTML; `format: both` generates both reports. Without `format`,
Tukey generates JSON, plus HTML when `html` is enabled.

Explicit CLI options replace preset values, including entire lists. Repeating
a list option collects multiple values. `--format json` disables a preset's HTML
output; `--format html` disables its JSON output. Use `--no-quiet` to enable logs
when a preset sets `quiet: true`.

`ignore_dirs` matches directory names at any depth and prunes them before scanning.
Comma-separated names are trimmed, so `"database, log"` ignores both `database`
and `log`; empty entries are discarded. Existing built-in exclusions still apply.
`ignore_extensions` accepts a YAML list or comma-separated string, with `.ts`,
`ts`, and `*.ts` treated alike, case-insensitively; `.d.ts` ignores declaration
files without excluding other TypeScript files. To ignore specific pages/files,
use relative path globs in `exclude`, e.g. `src/pages/legacy/*` or `**/*.generated.ts`.
These filters also apply when analyzing a single file.

### Default exclusions

Tukey skips version-control metadata, virtual environments, dependency directories
(`node_modules`, `npm_modules`, `vendor`, `bower_components`, `site-packages`),
build outputs (`target`, including Scala/sbt targets, `build`, `dist`), caches
(`__pycache__`, `.pytest_cache`, `.mypy_cache`, `.ruff_cache`, `.uv-cache`, `.cache`),
tool directories (`.gradle`, `.sbt`, `.bloop`, `.metals`, `.bsp`, `.scala-build`),
framework caches, editor metadata, and coverage reports before descending into them.
Names apply at every depth. Built-in file exclusions cover ignore files such as
`.gitignore` and `.dockerignore`, lockfiles, compiled artifacts, source maps,
minified JavaScript, Docker metadata, environment files, and OS metadata.

```sh
# Disable every built-in exclusion.
tukey . --no-exclusion

# Re-include only __pycache__, keeping every other default exclusion.
tukey . --no-exclusion "**pycache**"

# Re-include several defaults by name or pattern.
tukey . --no-exclusion "target, node_modules" --no-exclusion "**pycache**"
```

Put the source path before `--no-exclusion`: an immediately following value is
treated as its optional pattern. Quote glob patterns so the shell passes them
unchanged. These options remove only built-in exclusions; explicit `exclude`,
`ignore_dirs`, and `ignore_extensions` still apply. The supported source languages
and the policy of not following symlinks remain the same. Reports list the
effective default exclusions after these overrides.

## What the metrics mean

Each directory containing analyzed files is a **module**. Its size includes only
its direct files. `.` identifies the root module. Package and namespace metadata
are recorded separately and help resolve imports.

Physical lines include comments and blank lines; nonblank lines exclude only
blank lines. Declaration sizes include their signatures and bodies. Class,
function, file, and module sizes overlap and should not be added together.

Type coverage measures the presence of parameter and return annotations, rather
than type correctness or inference. Python and PHP use a `best_practice` policy;
Java, Rust, Scala, and TypeScript use `static`. JavaScript has no applicable
annotation coverage and reports `null`. Variable annotations are recorded
separately. Docstrings, JSDoc, and other docblocks are not evaluated.

Module coupling counts distinct local modules: **Ce** counts outgoing dependencies,
**Ca** counts incoming dependencies, and **instability** is `Ce / (Ce + Ca)`.
Instability is `null` when both counts are zero. Unresolved imports stay visible
without creating guessed dependency edges.

Call graphs resolve syntactic references such as lexical names, aliases, and
explicit receivers. Ambiguous calls and calls requiring type inference remain
unresolved. Complexity is syntax based; it is an aid to review, not compiler output.

## Potentially unused code

```sh
tukey . --entry-point "src/app.py#main" --html -o report.json
tukey . --entry-point "src/main.ts" --public-api "src/api.ts" --html
tukey . --entry-point "tests/test_*.py" --public-api "src/lib.py#public_*"
```

File patterns are relative to the analyzed root. Append `#NAME` to select a
symbol name or symbol glob. Explicit entry points replace automatic entry-point
detection. Without explicit entries, Tukey recognizes conventional main files,
Python main guards and test entries, and Rust/Java/Scala `main` declarations.
An entry-point file starts at its file-level references; it does not mark every
function as called. A public API file preserves all of its declarations.
Unmatched patterns are rejected to avoid silently empty configurations.

Files and declarations report `referenced`, `unused_candidate`, or `unknown`,
with reasons and evidence. With entry points, analysis follows references and
imports for reachability. Without detected entries, it uses references only and
reports `reachable: null`. Review candidates before deleting code: reflection,
framework conventions, exports, and incomplete source discovery limit certainty.
Test coverage is never treated as proof that code is unused.

## Importing test coverage

Generate coverage against the same source revision you analyze. Tukey reads an
existing report; it does not run tests or instrument the target project.

For a Python checkout with tests and dependencies already configured:

```sh
uv run --with coverage coverage run --source=src -m pytest
uv run --with coverage coverage json -o coverage.json
uv run tukey . --coverage coverage.json -o report.json
```

For JavaScript, TypeScript, or Rust, generate LCOV using your configured coverage
runner, then import it:

```sh
tukey . --coverage coverage/lcov.info -o report.json

# When analyzing a subdirectory, resolve coverage paths from the project root.
tukey src --coverage coverage/lcov.info --coverage-root . -o report.json
```

Coverage.py JSON supports Python files and inferred function/method body coverage.
LCOV supports JavaScript, TypeScript, and Rust line coverage at file, module, and
project levels; declaration coverage remains unmeasured. TypeScript reports must
point to original `.ts`/`.tsx` files: Tukey does not apply source maps.

Ratios range from 0 to 1. Unmeasured coverage and zero executable lines use `null`;
measured zero coverage remains zero. Aggregates sum line counts rather than average
percentages. Partial coverage explicitly reports measured and unmeasured files.
Execution counts and branch coverage are not provided. Coverage metrics currently
appear in JSON only, independently of signature type coverage.

## JSON report

The tool version is **0.2.0**; the report schema version is **1.4.0**. See the
[JSON Schema](docs/report.schema.json) for the complete contract.

| Field | Contents |
| --- | --- |
| `schema_version`, `tool`, `root` | Contract version, tool version, absolute source root |
| `analysis` | Conventions, exclusions, and usage configuration |
| `summary` | Counts, sizes, languages, coverage, and errors |
| `modules` | Direct member files, coupling, sizes, and coverage |
| `files` | Declarations, annotations, imports, calls, usage, and diagnostics |
| `dependency_graph` | Local module dependencies with import evidence |
| `call_graph` | Resolved edges, call sites, and unresolved calls |
| `diagnostics` | Discovery, reading, and coverage diagnostics |

Internal paths use `/` and are relative to `root`. For a single-file analysis,
`root` is its parent directory. Declaration IDs include paths and byte offsets
and can change between revisions; use them as identifiers within one report.

## Scope and limitations

- Source files must be UTF-8. Unsupported encodings produce diagnostics.
- Common dependency, build, and virtual-environment directories are skipped.
  The report lists these in `analysis.ignored_directories`; symlinks are skipped.
- `.gitignore` is not interpreted. Use explicit `--exclude` patterns as needed.
- Import resolution uses source layout and common conventions such as `src/`,
  `lib/`, `index`, `__init__`, and `mod`. It does not interpret tsconfig aliases,
  Cargo workspaces, Composer settings, JVM builds, or custom source roots.
- Dynamic imports, macros, PHP include/require, reflection, and runtime dispatch
  cannot be fully resolved. Identifier-based import usage has no full scope analysis.
- Results cover only supported source files discovered under the selected root.
  They complement compiler, linter, and test results.

## Development

```sh
uv sync --group dev
uv run pytest
uv run black --check src tests
uv run black src tests
uv build
```

Optional Make targets: `setup`, `install`, `uninstall`, `run`, `test`, `format`,
`check`, and `tokens`. For example:

```sh
make run PROJECT_PATH=. ARGS="--html report.html -o report.json"
make check
make tokens
```

| Location | Responsibility |
| --- | --- |
| `install.sh`, `install.ps1` | User-level installation and PATH configuration |
| `src/tukey/cli.py` | CLI arguments and report output |
| `src/tukey/syntax.py` | Tree-sitter language adapters and syntax metrics |
| `src/tukey/analyzer.py` | Discovery, import resolution, and aggregation |
| `src/tukey/relations.py` | Conservative call resolution |
| `src/tukey/usage.py` | Reference and reachability analysis |
| `src/tukey/coverage_readers.py` | Coverage.py JSON and LCOV readers |
| `src/tukey/coverage.py` | Coverage association and aggregation |
| `src/tukey/html_report.py`, `report.html` | HTML data preparation and UI template |
| `src/tukey/design.tokens.json`, `design.py` | Shared design tokens and CSS export |
| `tests/` | Language examples, CLI integration, schema, coverage, and HTML checks |
| `docs/` | Report schema, example reports, and design documentation |

The standalone `log/` and `utils/` helpers are legacy scaffolding, separate from
the installed CLI. Tukey does not require their environment settings or optional
`aiofiles`/`python-dotenv` dependencies.

## Contributing

Issues and pull requests are welcome through the
[issue tracker](https://github.com/pedrohgoncalvess/tukey/issues) and repository.
For a bug report, include a minimal source example, your command, Python and Tukey
versions, and the observed and expected behavior. Remove private source and paths
from any report you share.

Keep changes focused, add meaningful tests for behavior changes, and run the test
suite and formatter before opening a pull request. Use English
[Conventional Commits](https://www.conventionalcommits.org/), for example
`feat(coverage): support another coverage format` or
`fix(analyzer): resolve relative imports correctly`.

## License

Licensed under the [Apache License 2.0](LICENSE). The SPDX identifier is
`Apache-2.0`; dependency licenses remain their own.

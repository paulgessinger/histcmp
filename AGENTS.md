# Repository Guidelines

## Project Structure & Module Organization

`histcmp` is a Python 3.10+ tool for comparing ROOT histograms and generating reports. Source code lives in `src/histcmp/`: `cli.py` defines the Typer command, `compare.py` and `checks.py` implement comparisons, `root_helpers.py` handles ROOT conversion, and `worker.py` supports multiprocessing. Plotting and report generation live in `plot.py` and `report.py`; configuration models live in `config.py`.

HTML templates are in `src/histcmp/templates/`, with bundled CSS and JavaScript in `src/histcmp/static/`. Tests live in `tests/`, and reference ROOT files are in `tests/data/`.

## Build, Test, and Development Commands

- `uv sync --dev`: install the project and development dependencies from `uv.lock`.
- `uv run histcmp --help`: inspect CLI arguments and options.
- `uv run histcmp tests/data/performance_ckf.root tests/data/performance_ckf_main.root -o report/index.html`: compare sample files and generate an HTML report.
- `uv run pytest`: run the test suite.
- `uv run pytest tests/test_2d3d.py`: run multidimensional histogram tests.
- `uv build`: build distributions using Hatchling.

Reports link to PNGs in a sibling `<report-stem>_plots/` directory; `--plots` overrides it. Publish the HTML and image directory together. PNG is the only plot format.

ROOT comparisons require an environment where Python can import `ROOT` (PyROOT); this dependency is not declared in `pyproject.toml`. Some tests skip when ROOT is unavailable, but the full suite requires it.

## Coding Style & Naming Conventions

Use four-space indentation, as specified by `.editorconfig`. Follow existing Python conventions: `snake_case` for functions, variables, and modules, and `PascalCase` for classes. Preserve type annotations and use Pydantic models for validated configuration. Match nearby code rather than reformatting unrelated sections. No formatter or linter is currently configured.

## Testing Guidelines

Use pytest with `test_*.py` files and `test_*` functions. Add regression tests for changed comparison, conversion, or rendering behavior. Use temporary directories for generated reports and plots, deterministic seeds for synthetic histograms, and parameterization for renderer or worker-count variants. Check meaningful outputs and numerical behavior. No coverage threshold is configured.

## Commit & Pull Request Guidelines

Recent history uses short, descriptive subjects such as “Create output directories in make_report”; no strict commit prefix convention is evident. Keep commits focused and describe the resulting behavior.

For pull requests, explain the problem, implementation, and validation performed. Link relevant issues and include sample reports or screenshots for visible plotting or report changes. Mention missing ROOT support or skipped tests when reporting validation.

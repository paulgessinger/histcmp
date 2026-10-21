"""Benchmark real histcmp plots without changing production rendering code.

Prepare once with PyROOT available, then benchmark the pickled, ROOT-free data:

    python benchmarks/plotting.py prepare monitored.root reference.root output-dir
    python benchmarks/plotting.py render output-dir --sample 4 --repeats 3

--sample selects evenly spaced occupancy ranks within each ROOT class/plot kind.
Omit --sample to render every supported histogram pair. Pickles are local benchmark
intermediates and must not be loaded from untrusted sources.
The "current" variant preserves the original inline SVG/PNG baseline, including
constrained layout and scatter outlines, for comparison with the measured variants.
"""

import argparse
import contextlib
import hashlib
import importlib.metadata
import io
import json
import os
from pathlib import Path
import pickle
import platform
import random
import re
import sys
import time


VARIANTS = {
    "current": {},
    "fixed-layout": {"fixed_layout": True},
    "imshow": {"imshow": True},
    "tuned-svg": {"fixed_layout": True, "imshow": True, "fixed_legend": True},
    "png": {"png": True},
    "png-fast": {"png": True, "compress_level": 1},
    "tuned-png": {
        "fixed_layout": True, "imshow": True, "fixed_legend": True,
        "png": True, "compress_level": 1,
    },
    "scatter-no-edges": {"scatter_no_edges": True},
    "fixed-layout-no-edges": {"fixed_layout": True, "scatter_no_edges": True},
}


def write_json(path, data):
    Path(path).write_text(json.dumps(data, indent=2) + "\n")


def environment():
    packages = ["hist", "matplotlib", "mplhep", "numpy", "scipy", "pillow"]
    return {
        "python": sys.version,
        "platform": platform.platform(),
        "packages": {p: importlib.metadata.version(p) for p in packages},
        "cpu_count": os.cpu_count(),
        "cpu_affinity": sorted(os.sched_getaffinity(0)),
        "load_average": os.getloadavg(),
        "MPLCONFIGDIR": os.environ.get("MPLCONFIGDIR"),
        "OPENBLAS_NUM_THREADS": os.environ.get("OPENBLAS_NUM_THREADS"),
    }


def prepare(args):
    start = time.perf_counter()
    import ROOT
    ROOT.gROOT.SetBatch(True)
    ROOT.gErrorIgnoreLevel = ROOT.kError
    root_seconds = time.perf_counter() - start
    start = time.perf_counter()
    import numpy as np
    from histcmp.compare import build_checks, build_plot_specs, can_handle_item, collect_items
    from histcmp.config import Config
    imports_seconds = time.perf_counter() - start
    config = Config(checks={"*": {
        "Chi2Test": {"threshold": 0.01},
        "KolmogorovTest": {"threshold": 0.68},
        "RatioCheck": {"threshold": 3},
        "ResidualCheck": {"threshold": 1},
        "IntegralCheck": {"threshold": 3},
    }})
    files = [ROOT.TFile.Open(str(p.resolve())) for p in (args.monitored, args.reference)]
    if any(not f or f.IsZombie() for f in files):
        raise RuntimeError("Cannot open benchmark input")
    start = time.perf_counter()
    maps = [collect_items(f) for f in files]
    read_seconds = time.perf_counter() - start
    records, inventory = [], []
    for key in sorted(maps[0].keys() & maps[1].keys()):
        a, b = (m[key] for m in maps)
        row = {"key": key, "class": a.ClassName(), "supported": can_handle_item(a)}
        inventory.append(row)
        if not row["supported"] or type(a) != type(b):
            continue
        start = time.perf_counter()
        checks = build_checks(config.checks, key, a, b)
        # Materialize lazy scores as the normal console/report pipeline does.
        row["checks"] = [
            {
                "name": str(c), "status": c.status.name,
                "applicable": bool(c.is_applicable),
                "label": c.label if c.is_applicable else "",
            }
            for c in checks
        ]
        row["checks_seconds"] = time.perf_counter() - start
        start = time.perf_counter()
        specs = build_plot_specs(a, b, config.plots)
        row["conversion_seconds"] = time.perf_counter() - start
        for spec in specs:
            row.update({
                "kind": spec.kind,
                "shape": list(spec.h_a.values().shape),
                "bins": int(spec.h_a.values().size),
                "occupied": int(np.count_nonzero(spec.h_a.values()) +
                                np.count_nonzero(spec.h_b.values())),
            })
            records.append({"key": key, "class": row["class"],
                            "occupied": row["occupied"], "spec": spec})
    args.output.mkdir(parents=True, exist_ok=True)
    with (args.output / "plots.pkl").open("wb") as stream:
        pickle.dump(records, stream, protocol=pickle.HIGHEST_PROTOCOL)
    metadata = {
        "command": sys.argv,
        "environment": environment(), "root": ROOT.gROOT.GetVersion(),
        "root_import_seconds": root_seconds, "other_imports_seconds": imports_seconds,
        "read_seconds": read_seconds,
        "checks_seconds": sum(r.get("checks_seconds", 0) for r in inventory),
        "conversion_seconds": sum(r.get("conversion_seconds", 0) for r in inventory),
        "inputs": [
            {"path": str(p.resolve()), "bytes": p.stat().st_size,
             "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
            for p in (args.monitored, args.reference)
        ],
        "inventory": inventory,
    }
    write_json(args.output / "preparation.json", metadata)
    print(json.dumps({k: v for k, v in metadata.items() if k != "inventory"}), flush=True)
    print(f"Prepared {len(records)} plot specifications", flush=True)


@contextlib.contextmanager
def rendering_options(options):
    import matplotlib
    from matplotlib.axes import Axes
    import numpy as np
    import histcmp.plot as plotting

    original_panel = plotting._new_2d_panel
    original_mesh = Axes.pcolormesh
    from mpl_toolkits.mplot3d.axes3d import Axes3D
    original_scatter = Axes3D.scatter

    def panel(a, title):
        fixed = options.get("fixed_layout", False)
        fig, ax = plotting.pyplot.subplots(figsize=(6, 4.5), constrained_layout=not fixed)
        if fixed:
            fig.subplots_adjust(left=0.14, right=0.90, bottom=0.14, top=0.83)
        ax.set_xlabel(a.axes[0].name)
        ax.set_ylabel(a.axes[1].name)
        ax.set_title(title)
        fig.suptitle(plotting.sanitize_name(a.name))
        return fig, ax

    def uniform_image(ax, *args, **kwargs):
        # Only replace histcmp's main heatmap, never the colorbar's own mesh.
        if len(args) == 3 and kwargs.get("rasterized") is True:
            x, y, values = args
            x, y = np.asarray(x), np.asarray(y)
            if (x.ndim == y.ndim == 1 and len(x) > 1 and len(y) > 1
                    and np.allclose(np.diff(x), x[1] - x[0])
                    and np.allclose(np.diff(y), y[1] - y[0])):
                return ax.imshow(
                    values, origin="lower", interpolation="nearest", aspect="auto",
                    extent=(x[0], x[-1], y[0], y[-1]), **kwargs,
                )
        return original_mesh(ax, *args, **kwargs)

    try:
        plotting._new_2d_panel = panel
        if options.get("imshow"):
            Axes.pcolormesh = uniform_image
        def scatter(ax, *args, **kwargs):
            no_edges = options.get("scatter_no_edges", False)
            kwargs.update(
                edgecolors="none" if no_edges else None,
                linewidths=0 if no_edges else None,
            )
            return original_scatter(ax, *args, **kwargs)

        Axes3D.scatter = scatter
        with matplotlib.rc_context(
            {"legend.loc": "upper right"} if options.get("fixed_legend") else {}
        ):
            yield
    finally:
        plotting._new_2d_panel = original_panel
        Axes.pcolormesh = original_mesh
        Axes3D.scatter = original_scatter


def build_figures(spec):
    import histcmp.plot as plotting
    a, b = spec.h_a, spec.h_b
    if spec.kind == "2d":
        return plotting.plot_2d(a, b, "KF", "GX2F", spec.comparison)
    if spec.kind == "3d":
        plotter = plotting.plot_3d_scatter if spec.renderer == "scatter" else plotting.plot_3d_voxel
        return plotter(a, b, "KF", "GX2F", spec.comparison)
    if spec.kind == "1d":
        return [("", plotting.plot_1d(a, b, "KF", "GX2F", spec.comparison)[0])]
    if spec.kind == "eff":
        import numpy as np
        fig, (ax, _) = plotting.plot_ratio_eff(a, spec.err_a, b, spec.err_b, "KF", "GX2F")
        nonzero = np.concatenate([a.values()[a.values() > 0], b.values()[b.values() > 0]])
        lower, upper = (np.min(nonzero), np.max(nonzero)) if len(nonzero) else (0, 1.015)
        ax.set_ylim(bottom=lower * 0.99, top=upper * 1.008)
        return [("", fig)]
    raise ValueError(spec.kind)


def svg_encode(svg):
    # Keep the old inline encoding here so the benchmark can reproduce its cost.
    def repl(match):
        char = match.group()
        return "'" if char == '"' else "%" + format(ord(char), "x")

    return " ".join(re.sub(r'["%#{}<>]', repl, svg).split())


def render_one(task):
    record, variant, file_format, reuse, preview_dir = task
    import base64
    import histcmp.plot as plotting

    if "ROOT" in sys.modules:
        raise RuntimeError("Rendering benchmark unexpectedly imported ROOT")
    options = VARIANTS[variant]
    spec = record["spec"]
    raster = spec.kind == "3d"
    report_format = "png" if raster or options.get("png") else "svg"
    report_kwargs = {"dpi": 120} if report_format == "png" else {}
    if report_format == "png" and "compress_level" in options:
        report_kwargs["pil_kwargs"] = {"compress_level": options["compress_level"]}
    row = {
        "key": record["key"], "class": record["class"], "kind": spec.kind,
        "bins": int(spec.h_a.values().size), "occupied": record["occupied"],
        "variant": variant, "report_format": report_format,
        "build_seconds": 0, "report_seconds": 0, "encode_seconds": 0,
        "export_seconds": 0, "report_bytes": 0, "export_bytes": 0,
        "figures": 0, "savefig_calls": 0,
    }
    with rendering_options(options):
        start = time.perf_counter()
        figures = build_figures(spec)
        row["build_seconds"] = time.perf_counter() - start
        for suffix, fig in figures:
            try:
                start = time.perf_counter()
                buf = io.BytesIO()
                fig.savefig(buf, format=report_format, **report_kwargs)
                row["report_seconds"] += time.perf_counter() - start
                row["savefig_calls"] += 1
                data = buf.getvalue()
                row["report_bytes"] += len(data)
                start = time.perf_counter()
                if report_format == "png":
                    uri = "data:image/png;base64," + base64.b64encode(data).decode("utf8")
                else:
                    uri = "data:image/svg+xml;utf8," + svg_encode(data.decode("utf8"))
                row["encode_seconds"] += time.perf_counter() - start
                if not uri:
                    raise AssertionError("Empty plot")
                row["figures"] += 1
                if file_format:
                    export_format = "png" if raster else file_format
                    start = time.perf_counter()
                    same_dpi = (export_format != "png" or raster
                                or fig.dpi == report_kwargs.get("dpi", fig.dpi))
                    if reuse and export_format == report_format and same_dpi:
                        # Reuse encoded image bytes; actual disk I/O is excluded
                        # from both branches to isolate rendering/encoding cost.
                        exported = data
                    else:
                        export_buf = io.BytesIO()
                        fig.savefig(export_buf, format=export_format,
                                    **({"dpi": 120} if raster else {}))
                        row["savefig_calls"] += 1
                        exported = export_buf.getvalue()
                    row["export_seconds"] += time.perf_counter() - start
                    row["export_bytes"] += len(exported)
                if preview_dir:
                    path = Path(preview_dir) / variant
                    path.mkdir(parents=True, exist_ok=True)
                    (path / f"{record['key'].replace('/', '_')}{suffix}.{report_format}").write_bytes(data)
            finally:
                plotting.pyplot.close(fig)
    return row


def worker_init():
    import matplotlib
    matplotlib.use("Agg", force=True)
    import histcmp.plot  # noqa: F401
    if "ROOT" in sys.modules:
        raise RuntimeError("Worker imported ROOT")


def select_sample(records, count):
    import numpy as np
    from collections import defaultdict
    groups = defaultdict(list)
    for record in records:
        groups[(record["class"], record["spec"].kind)].append(record)
    selected = []
    for group in groups.values():
        group.sort(key=lambda r: (r["occupied"], r["key"]))
        indices = np.linspace(0, len(group) - 1, min(count, len(group))).round().astype(int)
        selected.extend(group[i] for i in indices)
    return sorted(selected, key=lambda r: r["key"])


def render(args):
    from concurrent.futures import ProcessPoolExecutor
    import multiprocessing
    with (args.output / "plots.pkl").open("rb") as stream:
        records = pickle.load(stream)
    if args.sample:
        records = select_sample(records, args.sample)
    if args.kind:
        records = [r for r in records if r["spec"].kind == args.kind]
    worker_init()
    # Warm font/mathtext caches with one representative per plot kind. Each
    # variant's subsequent timings still include figure creation and full draws.
    seen = set()
    for record in records:
        kind = record["spec"].kind
        if kind not in seen:
            render_one((record, "current", None, False, None))
            seen.add(kind)
    result = {
        "command": sys.argv,
        "environment": environment(), "jobs": args.jobs,
        "file_format": args.file_format, "reuse": args.reuse,
        "sample": args.sample, "selected_keys": [r["key"] for r in records],
        "runs": [],
    }
    for repeat in range(args.repeats):
        variants = list(args.variants)
        random.Random(37 + repeat).shuffle(variants)
        for variant in variants:
            preview = str(args.output / "previews") if args.previews and repeat == 0 else None
            tasks = [(r, variant, args.file_format, args.reuse, preview) for r in records]
            started = time.perf_counter()
            if args.jobs == 1:
                rows = [render_one(t) for t in tasks]
            else:
                with ProcessPoolExecutor(
                    max_workers=args.jobs, mp_context=multiprocessing.get_context("spawn"),
                    initializer=worker_init,
                ) as pool:
                    rows = list(pool.map(render_one, tasks))
            elapsed = time.perf_counter() - started
            run = {"repeat": repeat, "variant": variant, "wall_seconds": elapsed, "rows": rows}
            result["runs"].append(run)
            write_json(args.output / args.result, result)
            print(json.dumps({
                "repeat": repeat, "variant": variant, "jobs": args.jobs,
                "items": len(rows), "wall_seconds": round(elapsed, 3),
                **{key: round(sum(r[key] for r in rows), 3) for key in
                   ("build_seconds", "report_seconds", "encode_seconds", "export_seconds",
                    "report_bytes", "figures", "savefig_calls")},
            }), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("monitored", type=Path)
    prep.add_argument("reference", type=Path)
    prep.add_argument("output", type=Path)
    bench = sub.add_parser("render")
    bench.add_argument("output", type=Path)
    bench.add_argument("--sample", type=int)
    bench.add_argument("--kind", choices=["1d", "2d", "3d", "eff"])
    bench.add_argument("--repeats", type=int, default=1)
    bench.add_argument("--jobs", type=int, default=1)
    bench.add_argument("--variants", nargs="+", choices=VARIANTS, default=["current"])
    bench.add_argument("--file-format", choices=["png", "pdf", "svg"])
    bench.add_argument("--reuse", action="store_true")
    bench.add_argument("--previews", action="store_true")
    bench.add_argument("--result", default="rendering.json")
    args = parser.parse_args()
    (prepare if args.command == "prepare" else render)(args)


if __name__ == "__main__":
    main()

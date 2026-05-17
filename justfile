set shell := ["bash", "-cu"]

bench_dir := "bench-out"
ckf := "tests/data/performance_ckf.root"
ckf_main := "tests/data/performance_ckf_main.root"

default:
    @just --list

# Run the hyperfine self-comparison benchmark used in CI
bench:
    mkdir -p {{bench_dir}}
    hyperfine \
        --warmup 1 \
        --runs 5 \
        --export-markdown {{bench_dir}}/results.md \
        --export-json {{bench_dir}}/results.json \
        --command-name 'performance_ckf self' \
        'histcmp {{ckf}} {{ckf}} -o {{bench_dir}}/ckf.html'

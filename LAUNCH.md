# Launch checklist

1. Use Python 3.10 or newer and synthetic UTF-8 JSON/JSONL inputs.
2. Install the published wheel, or install this checkout with `python -m pip install .`.
3. Run `pointer-presence-gate POLICY.json ROWS.jsonl` and check the exit code as well as the JSON status.
4. Treat `valid` as presence evidence only. It makes no claim about schema conformance, correctness, provider compatibility, content safety, or quality.
5. Keep input files local and synthetic; the command has no network or file-writing behavior.

See [README.md](README.md) for the precise input and output contract.

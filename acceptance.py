"""Fresh-wheel acceptance check; invoke with the deterministic built wheel path."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import venv
from pathlib import Path


def run(command: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, check=False)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"ACCEPTANCE FAIL: {message}")


def main() -> int:
    require(len(sys.argv) == 2, "usage: python acceptance.py dist/pointer_presence_gate-0.1.0-py3-none-any.whl")
    wheel = Path(sys.argv[1]).resolve(strict=True)
    require(wheel.name == "pointer_presence_gate-0.1.0-py3-none-any.whl", "unexpected wheel filename")
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    with tempfile.TemporaryDirectory(prefix="pointer-presence-acceptance-") as temp:
        root = Path(temp)
        environment = root / "venv"
        venv.EnvBuilder(with_pip=True, clear=True).create(environment)
        scripts = "Scripts" if os.name == "nt" else "bin"
        python = environment / scripts / ("python.exe" if os.name == "nt" else "python")
        console = environment / scripts / ("pointer-presence-gate.exe" if os.name == "nt" else "pointer-presence-gate")
        install = run([str(python), "-m", "pip", "install", "--no-index", "--no-deps", str(wheel)])
        require(install.returncode == 0 and not install.stderr.lower().count("error:"), "offline wheel install failed")
        script_dir = run([str(python), "-c", "import sysconfig; print(sysconfig.get_path('scripts'))"])
        require(script_dir.returncode == 0 and Path(script_dir.stdout.strip()).resolve() == console.parent.resolve(),
                "console script directory does not match sysconfig")
        version = run([str(python), "-c", "import pointer_presence_gate; print(pointer_presence_gate.__version__)"])
        require(version.returncode == 0 and version.stdout.strip() == "0.1.0", "installed import/version failed")
        checkout = Path(__file__).resolve().parent
        suite = run([str(python), "-m", "unittest", "discover", "-s", str(checkout / "tests"), "-v"],
                    cwd=checkout)
        require(suite.returncode == 0 and "Ran 16 tests" in suite.stderr and "OK" in suite.stderr,
                "full tests against fresh installed wheel failed")
        policy, rows = root / "policy.json", root / "rows.jsonl"
        policy.write_text('{"required":["/present"]}', encoding="utf-8")
        rows.write_text('{"id":"synthetic-ok","payload":{"present":null}}\n', encoding="utf-8")
        result = run([str(console), str(policy), str(rows)])
        require(result.returncode == 0 and result.stdout == '{"status":"valid","record_count":1,"missing_lines":[]}\n'
                and result.stderr == "", "installed success path failed")
        rows.write_text('{"id":"private-row-id","payload":{}}\n', encoding="utf-8")
        result = run([str(console), str(policy), str(rows)])
        require(result.returncode == 1 and result.stdout ==
                '{"status":"missing_required","record_count":1,"missing_lines":[1]}\n' and
                "private-row-id" not in result.stdout + result.stderr, "installed missing/privacy path failed")
        policy.write_text('{"required":["#bad-fragment"]}', encoding="utf-8")
        result = run([str(console), str(policy), str(rows)])
        require(result.returncode == 2 and result.stdout == '{"status":"invalid_input"}\n' and result.stderr == "",
                "installed invalid-input path failed")
        help_result = run([str(console), "--help"])
        require(help_result.returncode == 0 and "usage: pointer-presence-gate" in help_result.stdout and
                help_result.stderr == "", "installed help path failed")
        examples = checkout / "examples"
        quickstart = run([str(console), str(examples / "policy.json"), str(examples / "rows.jsonl")])
        require(quickstart.returncode == 1 and quickstart.stdout ==
                '{"status":"missing_required","record_count":2,"missing_lines":[2]}\n' and
                quickstart.stderr == "", "installed quickstart example failed")
        print(json.dumps({"acceptance": "PASS", "version": "0.1.0", "wheel": wheel.name,
                          "wheel_sha256": digest, "install": "fresh non-editable offline",
                          "console_script": str(console), "sysconfig_scripts": script_dir.stdout.strip(),
                          "full_tests": "PASS; 16 tests, 0 skipped",
                          "exit_codes": [0, 1, 2], "help": "PASS", "privacy": "PASS",
                          "quickstart": "PASS; installed command against examples"},
                         separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

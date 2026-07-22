import subprocess
import sys


def cli_runner(args, cwd):
    result = subprocess.run(
        [sys.executable, "s4chemist_cli.py", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=120,
    )
    return result.stdout, result.stderr, result.returncode

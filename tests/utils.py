import subprocess
import sys


def cli_runner(args, cwd):
    result = subprocess.run(
        [sys.executable, "s4chemist_cli.py", *args],
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
    )
    # Decode manually: text=True loses output on some Windows Pythons (3.11.9)
    # because the CLI reconfigures its stdout to UTF-8.
    return (
        result.stdout.decode("utf-8", errors="replace"),
        result.stderr.decode("utf-8", errors="replace"),
        result.returncode,
    )

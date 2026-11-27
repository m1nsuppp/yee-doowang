import subprocess
import sys
import unittest


def test() -> None:
    unittest.main(
        module=None,
        argv=["unittest", "discover", "-s", "tests", *sys.argv[1:]],
        exit=True,
    )


def lint() -> None:
    raise SystemExit(
        subprocess.call([sys.executable, "-m", "ruff", "check", "src", "tests"])
    )

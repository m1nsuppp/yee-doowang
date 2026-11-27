import subprocess
import sys
import unittest

import uvicorn


def dev() -> None:
    uvicorn.run("yee_doowang_api.main:app", host="127.0.0.1", port=8000, reload=True)


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

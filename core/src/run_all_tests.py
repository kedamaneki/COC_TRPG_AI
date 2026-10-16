# -*- coding: utf-8 -*-
"""Windows でも日本語が読めるよう UTF-8 で全テストを実行する。"""
from __future__ import annotations

import io
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
os.environ.setdefault("PYTHONUTF8", "1")

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# main の UTF-8 設定を先に適用
import main  # noqa: E402


class _Tee(io.TextIOBase):
    def __init__(self, *streams):
        self._streams = streams

    def write(self, s):
        for stream in self._streams:
            stream.write(s)
            stream.flush()
        return len(s)

    def flush(self):
        for stream in self._streams:
            stream.flush()


def main_cli():
    out_dir = ROOT.parent / "outputs"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "latest_log_tests.txt"

    loader = unittest.TestLoader()
    suite = loader.discover(str(ROOT), pattern="test_*.py")
    with out_path.open("w", encoding="utf-8", errors="replace", newline="\n") as fh:
        tee_out = _Tee(sys.stdout, fh)
        tee_err = _Tee(sys.stderr, fh)
        old_out, old_err = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = tee_out, tee_err
        try:
            runner = unittest.TextTestRunner(stream=fh, verbosity=2)
            result = runner.run(suite)
            fh.write("\n")
            fh.write(f"Ran {result.testsRun} tests\n")
            if result.wasSuccessful():
                fh.write("OK\n")
            else:
                fh.write(
                    f"FAILED (failures={len(result.failures)}, errors={len(result.errors)})\n"
                )
        finally:
            sys.stdout, sys.stderr = old_out, old_err
            # interpreter 終了時の flush が閉じたログファイルに触れないようにする。
            tee_out._streams = (old_out,)
            tee_err._streams = (old_err,)

    print(f"Wrote {out_path}")
    print(f"Ran {result.testsRun} tests")
    if result.wasSuccessful():
        print("OK")
        return 0
    print(f"FAILED (failures={len(result.failures)}, errors={len(result.errors)})")
    for label, bucket in (("FAIL", result.failures), ("ERROR", result.errors)):
        for test, tb in bucket:
            print(f"{label}: {test}")
            print(tb.splitlines()[-1] if tb else "")
    return 1


if __name__ == "__main__":
    raise SystemExit(main_cli())

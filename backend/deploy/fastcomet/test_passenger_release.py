"""Check that readiness identifies loaded code, not just uploaded files."""

import os
import runpy
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ENTRYPOINT = Path(__file__).parent / "app" / "passenger_wsgi.py"


def fake_bridge(app):
    def respond(environ, start_response):
        start_response("200 OK", [("Content-Type", "application/json")])
        return [b'{"status":"ready","database":"up"}']

    return respond


class ReleaseHeaderTest(unittest.TestCase):
    def test_header_identifies_loaded_release_even_after_files_change(self):
        self.check_release("a" * 40)

    def test_manual_install_without_marker_still_runs(self):
        self.check_release(None)

    def check_release(self, release):
        cwd, paths = os.getcwd(), sys.path[:]
        try:
            with tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                entrypoint = root / "passenger_wsgi.py"
                shutil.copyfile(ENTRYPOINT, entrypoint)
                marker = root / ".deploy-release"
                if release:
                    marker.write_text(release, encoding="utf-8")
                with patch.dict(sys.modules, {
                    "a2wsgi": SimpleNamespace(ASGIMiddleware=fake_bridge),
                    "app.main": SimpleNamespace(app=object()),
                }):
                    namespace = runpy.run_path(str(entrypoint))
                    marker.write_text("b" * 40, encoding="utf-8")
                    for url in ("/__wsgi_ping", "/api/health/ready"):
                        response = {}

                        def start_response(status, headers, exc_info=None, response=response):
                            response.update(status=status, headers=dict(headers))

                        body = namespace["application"]({"PATH_INFO": url}, start_response)
                        self.assertTrue(b"".join(body))
                        self.assertEqual(response["status"], "200 OK")
                        self.assertEqual(
                            response["headers"]["X-WRCC-Release"], release or "manual"
                        )
                # Windows cannot delete the temporary working directory while inside it.
                os.chdir(cwd)
        finally:
            os.chdir(cwd)
            sys.path[:] = paths


if __name__ == "__main__":
    unittest.main()

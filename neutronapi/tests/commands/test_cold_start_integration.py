import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path


class TestColdStartIntegration(unittest.TestCase):
    def setUp(self):
        self.cwd = os.getcwd()
        self.tmpdir = Path(tempfile.mkdtemp(prefix="neutronapi_integration_"))
        self.repo_root = Path(__file__).resolve().parents[3]

    def tearDown(self):
        os.chdir(self.cwd)
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _run(self, cmd, *, cwd):
        return subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )

    def _assert_success(self, result, *, context):
        if result.returncode != 0:
            self.fail(
                f"{context} failed with code {result.returncode}\n"
                f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
            )

    def test_packaged_cold_start(self):
        venv_dir = self.tmpdir / "venv"
        work_dir = self.tmpdir / "workspace"
        work_dir.mkdir()

        self._assert_success(
            self._run([sys.executable, "-m", "venv", str(venv_dir)], cwd=self.tmpdir),
            context="virtualenv creation",
        )

        python = venv_dir / "bin" / "python"
        neutronapi_bin = venv_dir / "bin" / "neutronapi"

        self._assert_success(
            self._run([str(python), "-m", "pip", "install", "-q", str(self.repo_root)], cwd=self.repo_root),
            context="package install",
        )
        self._assert_success(
            self._run([str(python), "-m", "neutronapi", "--help"], cwd=work_dir),
            context="python -m neutronapi --help",
        )
        self._assert_success(
            self._run([str(neutronapi_bin), "startproject", "blog"], cwd=work_dir),
            context="neutronapi startproject",
        )

        project_root = work_dir / "blog"
        self._assert_success(
            self._run([str(python), "manage.py", "check"], cwd=project_root),
            context="python manage.py check",
        )
        self._assert_success(
            self._run([str(python), "manage.py", "test", "-q"], cwd=project_root),
            context="python manage.py test -q",
        )

        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]

        proc = subprocess.Popen(
            [str(python), "manage.py", "start", "--no-reload", "--port", str(port)],
            cwd=project_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        try:
            deadline = time.time() + 15
            body = None
            while time.time() < deadline:
                if proc.poll() is not None:
                    output, _ = proc.communicate(timeout=1)
                    self.fail(f"development server exited early\nOUTPUT:\n{output}")
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1) as response:
                        body = response.read().decode("utf-8")
                        break
                except Exception:
                    time.sleep(0.25)

            self.assertIsNotNone(body, "Timed out waiting for the NeutronAPI dev server to boot.")
            self.assertIn("Hello from blog!", body)
        finally:
            if proc.poll() is None:
                proc.send_signal(signal.SIGINT)
            try:
                proc.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate(timeout=5)

"""Regression: LazySettings must not raise when the process cwd is removed.

Prod 2026-04-17 repro: systemd starts api.service with
`WorkingDirectory=/opt/layerbrain/current` (a symlink). `chdir` resolves
the symlink at service start, so the process's real cwd is the release
directory. A subsequent deploy that overwrites that release directory
(`rm -rf <release> && mkdir <release> && tar -xzf ...`) leaves the
still-running worker pointing at a deleted inode. Every request after
that used to 500 with

    File ".../neutronapi/conf.py", line 177, in _current_signature
        return (os.getcwd(), _settings_module_name())
    FileNotFoundError: [Errno 2] No such file or directory

because `LazySettings._current_signature()` calls `os.getcwd()` on every
request. Middleware like `request_logging._extract_ip` goes through
`settings.get(...)`, so every request tripped this.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from neutronapi.conf import LazySettings


class LazySettingsCwdRemovedTestCase(unittest.TestCase):
    def test_signature_survives_cwd_removal_after_initial_setup(self):
        # Arrange: prime LazySettings so it has a cached signature.
        ls = LazySettings()
        with tempfile.TemporaryDirectory() as tmp:
            ls._signature = (tmp, "apps.settings")

            # Act: simulate cwd being removed — os.getcwd now raises.
            def _raise_cwd_gone():
                raise FileNotFoundError(2, "No such file or directory")

            with patch("neutronapi.conf.os.getcwd", side_effect=_raise_cwd_gone):
                sig = ls._current_signature()

        # Assert: no crash; last-known signature is preserved so _setup
        # won't spuriously reload Settings on every request.
        self.assertEqual(sig, (tmp, "apps.settings"))

    def test_signature_survives_cwd_removal_before_initial_setup(self):
        # Arrange: fresh LazySettings, no cached signature yet.
        ls = LazySettings()
        self.assertIsNone(ls._signature)

        # Act: cwd already broken on first access.
        def _raise_cwd_gone():
            raise FileNotFoundError(2, "No such file or directory")

        with patch("neutronapi.conf.os.getcwd", side_effect=_raise_cwd_gone):
            sig = ls._current_signature()

        # Assert: returns a stable sentinel tuple so _setup can still run.
        self.assertEqual(sig[0], "<cwd-unavailable>")
        self.assertIsInstance(sig[1], str)

    def test_signature_normal_path_uses_getcwd(self):
        ls = LazySettings()
        with tempfile.TemporaryDirectory() as tmp:
            with patch("neutronapi.conf.os.getcwd", return_value=tmp):
                sig = ls._current_signature()
        self.assertEqual(sig[0], tmp)


if __name__ == "__main__":
    unittest.main()

"""Regression checks for verified assets and the installed controller entry point."""
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from service.core import model_catalog


class ReviewRegressions(unittest.TestCase):
    def test_inventory_reuses_digest_only_while_file_identity_is_unchanged(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "weights"
            path.write_bytes(b"good")
            asset = model_catalog.Asset("test", "weights", 4, "source", None, None,
                                        hashlib.sha256(b"good").hexdigest())
            with patch.object(model_catalog, "_digest", wraps=model_catalog._digest) as digest:
                self.assertEqual(asset.inventory(root)["state"], "verified")
                self.assertEqual(asset.inventory(root)["state"], "verified")
                self.assertEqual(digest.call_count, 1)
                replacement = root / "new"
                replacement.write_bytes(b"evil")
                os.replace(replacement, path)
                self.assertEqual(asset.inventory(root)["state"], "invalid")
                self.assertEqual(digest.call_count, 2)
                before = path.stat()
                path.write_bytes(b"good")
                os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
                self.assertEqual(asset.inventory(root)["state"], "verified")
                self.assertEqual(digest.call_count, 3)
                path.unlink()
                path.symlink_to(root / "other")
                self.assertEqual(asset.inventory(root)["state"], "absent")
                self.assertEqual(digest.call_count, 3)

    def test_packaged_controller_imports_service_from_other_directory(self):
        root = Path(__file__).resolve().parents[1]
        wrapper = (root / "packaging/arch/local-voice-controller").read_text()
        with tempfile.TemporaryDirectory() as temp:
            staged = Path(temp) / "lib/local-voice"
            (staged / "service").mkdir(parents=True)
            (staged / ".bundle-venv/bin").mkdir(parents=True)
            (staged / "service/__init__.py").write_text("")
            (staged / "service/clipboard_controller.py").write_text("print('staged controller')\n")
            python = staged / ".bundle-venv/bin/python"
            python.write_text(f"#!/bin/sh\ntest \"$PYTHONHOME\" = \"{staged}/.bundle-venv\" || exit 8\ntest \"$PYTHONNOUSERSITE\" = 1 || exit 9\nunset PYTHONHOME\nexec {sys.executable} \"$@\"\n")
            python.chmod(0o755)
            command = Path(temp) / "controller"
            command.write_text(wrapper.replace("root=/usr/lib/local-voice", f"root={staged}"))
            command.chmod(0o755)
            result = subprocess.run([str(command), "status"], cwd=temp,
                                    capture_output=True, text=True, env={**os.environ, "PYTHONPATH": ""})
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "staged controller")

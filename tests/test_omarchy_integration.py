"""Exercise the user integration against disposable homes and effective bind fixtures."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "integrations/omarchy/local-voice-integration"


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.home = root / "home"
        self.home.mkdir()
        self.bin = root / "bin"
        self.bin.mkdir()
        self.fixture = root / "binds.json"
        self.fixture.write_text("[]")
        hyprctl = self.bin / "hyprctl"
        hyprctl.write_text("#!/bin/sh\ncat \"$BIND_FIXTURE\"\n")
        hyprctl.chmod(0o755)
        self.env = dict(os.environ, HOME=str(self.home), PATH=f"{self.bin}:{os.environ['PATH']}", BIND_FIXTURE=str(self.fixture))
        self.bindings = self.home / ".config/hypr/bindings.conf"
        self.bindings.parent.mkdir(parents=True)
        self.bindings.write_text("# unrelated\nbindd = SUPER, Q, Existing, exec, other\n")
        self.record = self.home / ".config/local-voice/omarchy-integration.json"

    def command(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), *args], env=self.env, capture_output=True, text=True)

    def test_preview_apply_twice_remove_preserves_unrelated_changes(self):
        args = ("setup", "--read", "SUPER ALT + V", "--stop", "SUPER ALT + S")
        original = self.bindings.read_text()
        preview = self.command(*args)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        self.assertIn("local-voice-controller read-clipboard", preview.stdout)
        self.assertEqual(self.bindings.read_text(), original)
        self.assertFalse(self.record.exists())
        applied = self.command(*args, "--apply")
        self.assertEqual(applied.returncode, 0, applied.stderr)
        installed = self.bindings.read_text()
        self.assertIn("local-voice-controller stop", installed)
        self.assertEqual(self.command("setup", "--apply").returncode, 0)
        self.assertEqual(self.bindings.read_text(), installed)
        self.bindings.write_text(installed + "# later user edit\n")
        removed_preview = self.command("remove")
        self.assertEqual(removed_preview.returncode, 0, removed_preview.stderr)
        self.assertTrue(self.record.exists())
        removed = self.command("remove", "--apply")
        self.assertEqual(removed.returncode, 0, removed.stderr)
        self.assertEqual(self.bindings.read_text(), original + "# later user edit\n")
        self.assertFalse(self.record.exists())
        self.assertEqual(self.command("remove", "--apply").returncode, 0)

    def test_effective_collision_blocks_all_writes(self):
        self.fixture.write_text(json.dumps([{"modmask": 72, "key": "V", "submap": "", "description": "Existing action"}]))
        result = self.command("setup", "--read", "SUPER ALT + V", "--stop", "SUPER ALT + S", "--apply")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Existing action", result.stderr)
        self.assertFalse(self.record.exists())
        self.assertNotIn("Local Voice", self.bindings.read_text())

    def test_file_without_final_newline_round_trips(self):
        original = "# unrelated without newline"
        self.bindings.write_text(original)
        args = ("setup", "--read", "SUPER ALT + V", "--stop", "SUPER ALT + S", "--apply")
        self.assertEqual(self.command(*args).returncode, 0)
        self.assertEqual(self.command("remove", "--apply").returncode, 0)
        self.assertEqual(self.bindings.read_text(), original)

    def test_changed_owned_block_refuses_removal(self):
        self.assertEqual(self.command("setup", "--read", "SUPER ALT + V", "--stop", "SUPER ALT + S", "--apply").returncode, 0)
        self.bindings.write_text(self.bindings.read_text().replace("local-voice-controller stop", "other stop"))
        result = self.command("remove", "--apply")
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(self.record.exists())
        self.assertIn("other stop", self.bindings.read_text())

    def test_missing_effective_state_and_symlink_fail_closed(self):
        (self.bin / "hyprctl").unlink()
        result = self.command("setup", "--read", "SUPER ALT + V", "--stop", "SUPER ALT + S", "--apply")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.record.exists())
        self.bindings.unlink()
        self.bindings.symlink_to(self.home / "outside")
        self.assertNotEqual(self.command("remove", "--apply").returncode, 0)


if __name__ == "__main__":
    unittest.main()

"""Exercise the user integration against disposable homes and effective bind fixtures."""

import json
import importlib.machinery
import importlib.util
from unittest.mock import patch
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "integrations/omarchy/local-voice-integration"
loader = importlib.machinery.SourceFileLoader("integration", str(SCRIPT))
spec = importlib.util.spec_from_loader(loader.name, loader)
integration = importlib.util.module_from_spec(spec)
loader.exec_module(integration)


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
        (self.bindings.parent / "hyprland.conf").write_text("source = ~/.config/hypr/bindings.conf\n")
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

    def test_optional_selection_collision_and_legacy_removal(self):
        args = ("setup", "--read", "SUPER ALT + V", "--stop", "SUPER ALT + S",
                "--selection", "SUPER ALT + R")
        self.fixture.write_text(json.dumps([{"modmask": 72, "key": "r", "submap": ""}]))
        self.assertNotEqual(self.command(*args, "--apply").returncode, 0)
        self.assertFalse(self.record.exists())
        self.fixture.write_text("[]")
        self.assertEqual(self.command(*args, "--apply").returncode, 0)
        self.assertIn("toggle-selection", self.bindings.read_text())
        self.assertEqual(self.command("remove", "--apply").returncode, 0)
        legacy = ("setup", "--read", "SUPER ALT + V", "--stop", "SUPER ALT + S")
        self.assertEqual(self.command(*legacy, "--apply").returncode, 0)
        self.assertEqual(json.loads(self.record.read_text())["version"], 1)
        self.assertEqual(self.command("remove", "--apply").returncode, 0)

    def test_remove_detects_edit_after_initial_read(self):
        args = ("setup", "--read", "SUPER ALT + V", "--stop", "SUPER ALT + S", "--apply")
        self.assertEqual(self.command(*args).returncode, 0)
        original = self.bindings.read_text()
        def edit_before_apply(*args, **kwargs):
            self.bindings.write_text(original + "# concurrent edit\n")
        with patch.object(integration.Path, "home", return_value=self.home), patch.object(integration, "print", side_effect=edit_before_apply, create=True):
            with self.assertRaisesRegex(ValueError, "changed during removal"):
                integration.run(["remove", "--apply"])
        self.assertEqual(self.bindings.read_text(), original + "# concurrent edit\n")
        self.assertTrue(self.record.exists())

    def test_setup_rollback_leaves_absent_file_absent_and_preserves_key_case(self):
        self.bindings.unlink()
        self.assertEqual(integration.shortcut("super alt + XF86AudioPlay")[1], "XF86AudioPlay")
        with patch.object(integration.Path, "home", return_value=self.home), patch.object(integration, "effective_bindings", return_value=[]):
            original_write = integration.atomic_write
            def fail_record(path, text, mode=None):
                if path == self.record:
                    raise OSError("record write failed")
                return original_write(path, text, mode)
            with patch.object(integration, "atomic_write", side_effect=fail_record):
                with self.assertRaises(OSError):
                    integration.run(["setup", "--read", "super alt + XF86AudioPlay", "--stop", "super alt + S", "--apply"])
        self.assertFalse(self.bindings.exists())
        self.assertFalse(self.record.exists())

    def test_effective_collision_blocks_all_writes(self):
        self.fixture.write_text(json.dumps([{"modmask": 72, "key": "V", "submap": "", "description": "Existing action"}]))
        result = self.command("setup", "--read", "SUPER ALT + V", "--stop", "SUPER ALT + S", "--apply")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Existing action", result.stderr)
        self.assertFalse(self.record.exists())
        self.assertNotIn("Local Voice", self.bindings.read_text())

    def test_mixed_case_key_conflicts_with_existing_uppercase_binding(self):
        self.fixture.write_text(json.dumps([{"modmask": 64, "key": "DELETE", "submap": "", "description": "Existing delete"}]))
        result = self.command("setup", "--read", "SUPER + Delete", "--stop", "SUPER + Home", "--apply")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Existing delete", result.stderr)
        self.assertFalse(self.record.exists())
        self.assertNotIn("Local Voice", self.bindings.read_text())

    def test_read_and_stop_keys_conflict_even_when_case_differs(self):
        result = self.command("setup", "--read", "SUPER + Delete", "--stop", "SUPER + DELETE", "--apply")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("same shortcut", result.stderr)
        self.assertFalse(self.record.exists())

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

    def use_lua(self):
        (self.bindings.parent / "hyprland.lua").write_text('require("hypr.bindings")\n')
        self.lua_bindings = self.bindings.with_suffix(".lua")
        self.lua_bindings.write_text('-- unrelated\no.bind("SUPER + Q", "Existing", "other")')

    def test_lua_preview_apply_syntax_and_exact_remove(self):
        self.use_lua()
        original = self.lua_bindings.read_bytes()
        legacy = self.bindings.read_bytes()
        args = ("setup", "--read", "SUPER ALT + V", "--stop", "SUPER ALT + X",
                "--selection", "SUPER ALT + E")
        preview = self.command(*args)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        self.assertIn('o.bind("SUPER + ALT + V",', preview.stdout)
        self.assertEqual(self.lua_bindings.read_bytes(), original)
        self.assertFalse(self.record.exists())
        applied = self.command(*args, "--apply")
        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertEqual(json.loads(self.record.read_text())["provider"], "lua")
        text = self.lua_bindings.read_text()
        self.assertIn('-- local-voice integration BEGIN', text)
        self.assertIn('o.bind("SUPER + ALT + E", "Local Voice toggle selection", "local-voice-controller toggle-selection")', text)
        self.assertEqual(self.bindings.read_bytes(), legacy)
        self.assertEqual(self.command("setup", "--apply").returncode, 0)
        if subprocess.run(["sh", "-c", "command -v luac || command -v lua"], capture_output=True).returncode == 0:
            executable = "luac" if subprocess.run(["sh", "-c", "command -v luac"], capture_output=True).returncode == 0 else "lua"
            check = ([executable, "-p", str(self.lua_bindings)] if executable == "luac"
                     else [executable, "-e", "assert(loadfile(arg[1]))", str(self.lua_bindings)])
            parsed = subprocess.run(check, capture_output=True, text=True)
            self.assertEqual(parsed.returncode, 0, parsed.stderr)
        self.lua_bindings.write_text(text + "-- later edit\n")
        self.assertEqual(self.command("remove").returncode, 0)
        self.assertEqual(self.command("remove", "--apply").returncode, 0)
        self.assertEqual(self.lua_bindings.read_bytes(), original + b"-- later edit\n")
        self.assertEqual(self.bindings.read_bytes(), legacy)
        self.assertFalse(self.record.exists())

    def test_lua_collision_and_edited_block_fail_closed(self):
        self.use_lua()
        args = ("setup", "--read", "SUPER ALT + V", "--stop", "SUPER ALT + X", "--apply")
        self.fixture.write_text(json.dumps([{"modmask": 72, "key": "v", "submap": ""}]))
        result = self.command(*args)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.record.exists())
        self.fixture.write_text("[]")
        self.assertEqual(self.command(*args).returncode, 0)
        self.lua_bindings.write_text(self.lua_bindings.read_text().replace("local-voice-controller stop", "other stop"))
        result = self.command("remove", "--apply")
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(self.record.exists())

    def test_lua_record_write_failure_rolls_back(self):
        self.use_lua()
        original = self.lua_bindings.read_bytes()
        with patch.object(integration.Path, "home", return_value=self.home), patch.object(integration, "effective_bindings", return_value=[]):
            original_write = integration.atomic_write
            def fail_record(path, text, mode=None):
                if path == self.record:
                    raise OSError("record write failed")
                return original_write(path, text, mode)
            with patch.object(integration, "atomic_write", side_effect=fail_record):
                with self.assertRaises(OSError):
                    integration.run(["setup", "--read", "SUPER ALT + V", "--stop", "SUPER ALT + X", "--apply"])
        self.assertEqual(self.lua_bindings.read_bytes(), original)
        self.assertFalse(self.record.exists())

    def test_legacy_record_removes_conf_after_provider_switch(self):
        original = self.bindings.read_bytes()
        self.assertEqual(self.command("setup", "--read", "SUPER ALT + V", "--stop", "SUPER ALT + X", "--apply").returncode, 0)
        record = json.loads(self.record.read_text())
        record.pop("provider")
        self.record.write_text(json.dumps(record))
        self.use_lua()
        self.assertEqual(self.command("remove", "--apply").returncode, 0)
        self.assertEqual(self.bindings.read_bytes(), original)

    def test_missing_provider_or_lua_target_fails_closed(self):
        (self.bindings.parent / "hyprland.conf").unlink()
        args = ("setup", "--read", "SUPER ALT + V", "--stop", "SUPER ALT + X", "--apply")
        self.assertIn("No usable conf", self.command(*args).stderr)
        self.use_lua()
        self.lua_bindings.unlink()
        self.assertIn("No usable lua", self.command(*args).stderr)
        self.assertFalse(self.record.exists())

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

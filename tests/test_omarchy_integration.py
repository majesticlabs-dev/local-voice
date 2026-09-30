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
        hyprctl.write_text('#!/bin/sh\nif [ "$1" = binds ]; then cat "$BIND_FIXTURE"; fi\n')
        hyprctl.chmod(0o755)
        self.env = dict(os.environ, HOME=str(self.home), PATH=f"{self.bin}:{os.environ['PATH']}", BIND_FIXTURE=str(self.fixture))
        self.bindings = self.home / ".config/hypr/bindings.conf"
        self.bindings.parent.mkdir(parents=True)
        (self.bindings.parent / "hyprland.conf").write_text("source = ~/.config/hypr/bindings.conf\n")
        self.bindings.write_text("# unrelated\nbindd = SUPER, Q, Existing, exec, other\n")
        self.record = self.home / ".config/local-voice/omarchy-integration.json"

    def command(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), *args], env=self.env, capture_output=True, text=True)

    def write_settings(self, text):
        path = self.home / ".config/local-voice/shortcuts.toml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def test_settings_default_and_individual_enable_change_disable(self):
        self.use_lua()
        original = self.lua_bindings.read_text()
        self.assertEqual(self.command("sync").returncode, 0)
        self.assertEqual(self.lua_bindings.read_text(), original)
        path = self.write_settings(integration.TEMPLATE)
        self.assertEqual(self.command("sync").returncode, 0)
        self.assertFalse(self.record.exists())
        path.write_text('[selection]\nenabled = true\nbinding = "CTRL ALT + R"\n')
        result = self.command("sync")
        self.assertEqual(result.returncode, 0, result.stderr)
        text = self.lua_bindings.read_text()
        self.assertIn('o.bind("CTRL + ALT + R",', text)
        self.assertIn("toggle-selection", text)
        self.assertNotIn("read-clipboard", text)
        self.assertNotIn('"local-voice-controller stop"', text)
        self.fixture.write_text(json.dumps([{"modmask": 12, "key": "R", "dispatcher": "__lua",
                                            "arg": "140", "description": "Local Voice toggle selection", "submap": ""}]))
        self.assertEqual(self.command("sync").returncode, 0)
        self.assertEqual(self.lua_bindings.read_text(), text)
        path.write_text('[selection]\nenabled = true\nbinding = "SUPER ALT + E"\n')
        self.assertEqual(self.command("sync").returncode, 0)
        self.assertNotIn('"CTRL + ALT + R"', self.lua_bindings.read_text())
        self.assertIn('"SUPER + ALT + E"', self.lua_bindings.read_text())
        self.lua_bindings.write_text(self.lua_bindings.read_text() + "-- later edit\n")
        path.write_text('[selection]\nenabled = false\n')
        self.assertEqual(self.command("sync").returncode, 0)
        self.assertEqual(self.lua_bindings.read_text(), original + "-- later edit\n")
        self.assertFalse(self.record.exists())

    def test_missing_settings_removes_legacy_shortcuts_on_upgrade(self):
        self.use_lua()
        original = self.lua_bindings.read_text()
        self.assertEqual(self.command("setup", "--read", "SUPER ALT + V", "--stop", "SUPER ALT + X",
                                      "--selection", "SUPER ALT + E", "--apply").returncode, 0)
        self.assertEqual(self.command("sync").returncode, 0)
        self.assertEqual(self.lua_bindings.read_text(), original)
        self.assertFalse(self.record.exists())
        path = self.write_settings('[read]\nenabled = true\nbinding = "SUPER ALT + V"\n')
        self.assertEqual(self.command("sync").returncode, 0)
        path.unlink()
        self.assertEqual(self.command("sync").returncode, 0)
        self.assertEqual(self.lua_bindings.read_text(), original)

    def test_bad_settings_and_conflicts_skip_only_invalid_actions(self):
        original = self.bindings.read_text()
        path = self.write_settings('''[read]
enabled = true
binding = "SUPER ALT + V"
[stop]
enabled = "yes"
binding = "SUPER ALT + X"
[selection]
enabled = true
binding = "SUPER ALT + E; bad"
''')
        result = self.command("sync")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("warning", result.stderr)
        self.assertIn("read-clipboard", self.bindings.read_text())
        self.assertNotIn("toggle-selection", self.bindings.read_text())
        path.write_text('[read]\nenabled = true\nbinding = "SUPER ALT + V"\n'
                        '[stop]\nenabled = true\nbinding = "alt super + v"\n')
        result = self.command("sync")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Conflicting", result.stderr)
        self.assertEqual(self.bindings.read_text(), original)
        path.write_text('[read]\nenabled = true\nbinding = "SUPER ALT + V"\n'
                        '[stop]\nenabled = true\nbinding = "SUPER ALT + X"\n')
        self.fixture.write_text(json.dumps([{"modmask": 72, "key": "v", "submap": "", "dispatcher": "exec", "arg": "other"}]))
        result = self.command("sync")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("conflicts", result.stderr)
        self.assertNotIn("read-clipboard", self.bindings.read_text())
        self.assertIn("local-voice-controller stop", self.bindings.read_text())
        path.write_text('broken = [')
        result = self.command("sync")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("disabling", result.stderr)
        self.assertEqual(self.bindings.read_text(), original)

    def test_unknown_key_is_skipped_before_hyprland_reload(self):
        original = self.bindings.read_text()
        self.write_settings('[read]\nenabled = true\nbinding = "SUPER ALT + NotARealKey"\n')
        result = self.command("sync")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Unknown XKB key", result.stderr)
        self.assertEqual(self.bindings.read_text(), original)
        self.assertFalse(self.record.exists())

    def test_settings_missing_hyprctl_disables_previously_owned_bindings(self):
        original = self.bindings.read_text()
        self.write_settings('[read]\nenabled = true\nbinding = "SUPER ALT + V"\n')
        self.assertEqual(self.command("sync").returncode, 0)
        (self.bin / "hyprctl").unlink()
        self.env["PATH"] = str(self.bin)
        result = self.command("sync")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("disabling shortcuts", result.stderr)
        self.assertEqual(self.bindings.read_text(), original)

    def test_failed_reload_retries_and_edited_block_refuses_sync(self):
        path = self.write_settings('[read]\nenabled = true\nbinding = "SUPER ALT + V"\n')
        hyprctl = self.bin / "hyprctl"
        hyprctl.write_text('#!/bin/sh\nif [ "$1" = binds ]; then cat "$BIND_FIXTURE"; else exit 1; fi\n')
        result = self.command("sync")
        self.assertNotEqual(result.returncode, 0)
        pending = path.parent / ".shortcuts-reload-pending"
        self.assertTrue(pending.exists())
        hyprctl.write_text('#!/bin/sh\nif [ "$1" = binds ]; then cat "$BIND_FIXTURE"; fi\n')
        self.assertEqual(self.command("sync").returncode, 0)
        self.assertFalse(pending.exists())
        self.bindings.write_text(self.bindings.read_text().replace("read-clipboard", "other-command"))
        edited = self.bindings.read_text()
        path.unlink()
        result = self.command("sync")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Owned bindings changed", result.stderr)
        self.assertEqual(self.bindings.read_text(), edited)

    def test_ambiguous_lua_callback_collision_is_not_ignored(self):
        self.use_lua()
        self.write_settings('[read]\nenabled = true\nbinding = "SUPER ALT + V"\n')
        self.assertEqual(self.command("sync").returncode, 0)
        binding = {"modmask": 72, "key": "V", "submap": "", "dispatcher": "__lua",
                   "arg": "140", "description": "Local Voice read clipboard"}
        self.fixture.write_text(json.dumps([binding, {**binding, "arg": "141"}]))
        result = self.command("sync")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("conflicts", result.stderr)
        self.assertFalse(self.record.exists())

    def test_conflicting_same_command_not_in_owned_key_is_skipped(self):
        path = self.write_settings('[read]\nenabled = true\nbinding = "SUPER ALT + V"\n')
        self.assertEqual(self.command("sync").returncode, 0)
        path.write_text('[read]\nenabled = true\nbinding = "SUPER ALT + R"\n')
        self.fixture.write_text(json.dumps([{"modmask": 72, "key": "R", "submap": "",
                                            "dispatcher": "exec", "arg": "local-voice-controller read-clipboard"}]))
        result = self.command("sync")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("conflicts", result.stderr)
        self.assertFalse(self.record.exists())

    def test_editor_and_xdg_open_survive_panel_launcher_pipe_closure(self):
        import time
        result_path = self.bin / "launch-result"
        release = self.bin / "launch-release"
        launcher = f'''#!{sys.executable}
import os, sys, time
from pathlib import Path
deadline = time.monotonic() + 5
while not Path(os.environ["LAUNCH_RELEASE"]).exists():
    if time.monotonic() > deadline:
        sys.exit(1)
    time.sleep(0.01)
# A real terminal can emit startup warnings after the settings helper exits.
sys.stdout.write("terminal startup\\n")
sys.stdout.flush()
sys.stderr.write("terminal warning\\n")
sys.stderr.flush()
Path(os.environ["EDITOR_RESULT"]).write_text("\\n".join(sys.argv[1:]))
'''
        for name in ("xdg-terminal-exec", "xdg-open"):
            binary = self.bin / name
            binary.write_text(launcher)
            binary.chmod(0o755)
        self.env.update(EDITOR_RESULT=str(result_path), LAUNCH_RELEASE=str(release))
        for editor, expected_prefix in (("test-editor --wait", ["test-editor", "--wait"]), ("", [])):
            with self.subTest(editor=editor):
                result_path.unlink(missing_ok=True)
                release.unlink(missing_ok=True)
                self.env["EDITOR"] = editor
                process = subprocess.Popen([sys.executable, str(SCRIPT), "settings"],
                                           env=self.env, stdin=subprocess.PIPE,
                                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                try:
                    self.assertEqual(process.wait(timeout=5), 0)
                finally:
                    for stream in (process.stdin, process.stdout, process.stderr):
                        stream.close()
                    release.touch()
                deadline = time.monotonic() + 6
                while not result_path.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(result_path.exists(), "Editor died when the panel closed launcher pipes")
                self.assertEqual(result_path.read_text().splitlines(), expected_prefix + [str(self.home / ".config/local-voice/shortcuts.toml")])

    def test_editor_menu_command_creates_disabled_file_and_preserves_user_settings(self):
        editor = self.bin / "xdg-terminal-exec"
        editor.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$EDITOR_RESULT"\n')
        editor.chmod(0o755)
        result_path = self.bin / "editor-result"
        self.env.update(EDITOR="test-editor --wait", EDITOR_RESULT=str(result_path))
        result = self.command("settings")
        self.assertEqual(result.returncode, 0, result.stderr)
        # Wait for the launched editor fixture without testing shell source text.
        import time
        for _ in range(100):
            if result_path.exists():
                break
            time.sleep(0.01)
        self.assertEqual(result_path.read_text().splitlines(), ["test-editor", "--wait", str(self.home / ".config/local-voice/shortcuts.toml")])
        self.assertEqual(self.command("sync").returncode, 0)
        self.assertFalse(self.record.exists())
        path = self.write_settings('[stop]\nenabled = true\nbinding = "SUPER + X"\n')
        text = path.read_text()
        self.assertEqual(self.command("settings").returncode, 0)
        self.assertEqual(path.read_text(), text)

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

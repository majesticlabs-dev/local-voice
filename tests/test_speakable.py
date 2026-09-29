import unittest

from service.core.speakable import prepare


class SpeakableTests(unittest.TestCase):
    def test_terminal_noise(self):
        self.assertEqual(prepare("\x1b[31mError\x1b[0m \ue0b0 ── 😀 \x07failed"), "Error failed")

    def test_git_hash_uuid_url_and_path(self):
        text = ("commit 0123456789abcdef changed /home/user/project/readme.md at "
                "https://example.org/a/b?q=1 id 123e4567-e89b-12d3-a456-426614174000")
        self.assertEqual(prepare(text), "commit hash changed readme.md at example.org id ID")

    def test_decimal_number_is_not_a_hash(self):
        self.assertEqual(prepare("Call 123456789012 about abcdef123456"),
                         "Call 123456789012 about hash")

    def test_url_punctuation_and_directory_basename(self):
        self.assertEqual(prepare("See https://example.com. Open /usr/lib/!"),
                         "See example.com. Open lib!")

    def test_markdown_table_and_plain_prose(self):
        self.assertEqual(prepare("| Name | State |\n| --- | --- |\n| Voice | ready |"),
                         "Name State\nVoice ready")
        self.assertEqual(prepare("This is ordinary prose. It stays the same."),
                         "This is ordinary prose. It stays the same.")

    def test_only_symbols(self):
        self.assertEqual(prepare("\ue0b0 ── 😀\x1b[0m"), "")

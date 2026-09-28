"""Prepare explicitly requested clipboard or selection text for speech."""
import re
import unicodedata
from urllib.parse import urlsplit

from .markdown import strip_markdown

ANSI = re.compile(r"\x1b(?:\][^\x07\x1b]*(?:\x07|\x1b\\)|\[[0-?]*[ -/]*[@-~]|[@-_])")
URL = re.compile(r"https?://[^\s<>]+")
UUID = re.compile(r"\b[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}\b")
HASH = re.compile(r"\b[0-9a-fA-F]{12,}\b")
PATH = re.compile(r"(?<!\w)(?:/|\./|\.\./)[^\s,;:()<>]+")


def prepare(text: str) -> str:
    text = ANSI.sub("", text)
    text = "".join(ch for ch in text if ch in "\n\t" or
                   (unicodedata.category(ch) not in ("Cc", "Cf", "Co", "Cs") and
                    not 0x2500 <= ord(ch) <= 0x257f and
                    not (0x1f000 <= ord(ch) <= 0x1faff or 0x2600 <= ord(ch) <= 0x27bf)))
    text = URL.sub(lambda m: urlsplit(m.group().rstrip(".,;!?")).hostname or "", text)
    text = UUID.sub("ID", text)
    text = HASH.sub("hash", text)
    text = PATH.sub(lambda m: m.group().rstrip(".").split("/")[-1], text)
    text = strip_markdown(text)
    return re.sub(r"\n{2,}", "\n", text).strip()

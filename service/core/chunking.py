import re

SENTENCE_END = re.compile(r'(?<=[.!?])\s+')
PARAGRAPH_BREAK = re.compile(r'\n\s*\n')


def chunk_text(
    text: str,
    strategy: str = "sentence",
    target_chars: int = 500,
    max_chars: int = 1000,
) -> list[str]:
    if target_chars <= 0 or max_chars <= 0:
        raise ValueError("Chunk sizes must be positive")
    target_chars = min(target_chars, max_chars)
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    if strategy == "paragraph":
        return _chunk_by_paragraph(text, target_chars, max_chars)
    return _chunk_by_sentence(text, target_chars, max_chars)


def _chunk_by_sentence(text: str, target: int, maximum: int) -> list[str]:
    paragraphs = PARAGRAPH_BREAK.split(text)
    chunks: list[str] = []
    current = ""

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        if len(para) <= maximum:
            if len(current) + len(para) + 2 <= target:
                current = f"{current}\n\n{para}" if current else para
            else:
                if current:
                    chunks.append(current)
                current = para
        else:
            if current:
                chunks.append(current)
                current = ""
            sentences = SENTENCE_END.split(para)
            for sentence in sentences:
                sentence = sentence.strip()
                if not sentence:
                    continue
                if len(current) + len(sentence) + 1 <= target:
                    current = f"{current} {sentence}" if current else sentence
                else:
                    if current:
                        chunks.append(current)
                    # Keep every part of sentences that exceed the chunk limit.
                    while len(sentence) > maximum:
                        split_at = sentence.rfind(" ", 0, maximum + 1)
                        if split_at <= 0:
                            split_at = maximum
                        chunks.append(sentence[:split_at])
                        sentence = sentence[split_at:].lstrip()
                    current = sentence

    if current:
        chunks.append(current)
    return chunks

const SENTENCE_END = /(?<=[.!?])\s+/;
const PARAGRAPH_BREAK = /\n\s*\n/;

export function chunkText(text, { targetChars = 500, maxChars = 1000 } = {}) {
  text = text.trim();
  if (!text) return [];
  if (text.length <= maxChars) return [text];

  const paragraphs = text.split(PARAGRAPH_BREAK).filter(Boolean);
  const chunks = [];
  let current = '';

  for (const para of paragraphs) {
    if (para.length <= maxChars) {
      if (current.length + para.length + 1 <= targetChars) {
        current = current ? `${current}\n\n${para}` : para;
      } else {
        if (current) chunks.push(current);
        current = para;
      }
    } else {
      if (current) {
        chunks.push(current);
        current = '';
      }
      const sentences = para.split(SENTENCE_END).filter(Boolean);
      for (const sentence of sentences) {
        if (current.length + sentence.length + 1 <= targetChars) {
          current = current ? `${current} ${sentence}` : sentence;
        } else {
          if (current) chunks.push(current);
          current = sentence.length > maxChars ? sentence.slice(0, maxChars) : sentence;
        }
      }
    }
  }

  if (current) chunks.push(current);
  return chunks;
}

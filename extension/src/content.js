const X_HOSTS = new Set([
  'x.com',
  'www.x.com',
  'mobile.x.com',
  'twitter.com',
  'www.twitter.com',
  'mobile.twitter.com',
]);
const NFX_HOSTS = new Set([
  'nfx.com',
  'www.nfx.com',
]);

const RECENT_SELECTION_TTL_MS = 30000;
const INPUT_TYPES_WITH_TEXT_SELECTION = new Set([
  'text',
  'search',
  'url',
  'tel',
  'email',
  'number',
]);
const CONTAINER_TAGS = new Set([
  'ARTICLE',
  'ASIDE',
  'BLOCKQUOTE',
  'DIV',
  'LI',
  'MAIN',
  'P',
  'SECTION',
  'TD',
]);
const BLOCK_TAGS = new Set([
  'ARTICLE',
  'BLOCKQUOTE',
  'DIV',
  'FIGCAPTION',
  'FIGURE',
  'FOOTER',
  'H1',
  'H2',
  'H3',
  'H4',
  'H5',
  'H6',
  'HEADER',
  'LI',
  'MAIN',
  'OL',
  'P',
  'PRE',
  'SECTION',
  'TABLE',
  'TD',
  'TH',
  'TR',
  'UL',
]);
const SERIALIZE_SKIP_SELECTOR = [
  'script',
  'style',
  'noscript',
  'template',
  'svg',
  'canvas',
  'iframe',
  'button',
  'input',
  'textarea',
  'select',
  'option',
  'label',
  'form',
  '[role="dialog"]',
  '[aria-modal="true"]',
  '[aria-hidden="true"]',
  '[hidden]',
].join(', ');
const PRUNE_SELECTOR = [
  SERIALIZE_SKIP_SELECTOR,
  'nav',
  'header',
  'footer',
  'aside',
  '[role="dialog"]',
  '[aria-modal="true"]',
  '[aria-hidden="true"]',
  '[hidden]',
].join(', ');
const X_ARTICLE_PRUNE_SELECTOR = [
  PRUNE_SELECTOR,
  '[data-testid="sidebarColumn"]',
  '[data-testid="tweetButtonInline"]',
  '[data-testid="tweetButton"]',
  '[data-testid="bookmark"]',
  '[data-testid="like"]',
  '[data-testid="retweet"]',
  '[data-testid="reply"]',
  '[data-testid="share"]',
  '[data-testid="caret"]',
  '[data-testid="placementTracking"]',
  '[data-testid="app-text-transition-container"]',
  '[aria-label*="Timeline"]',
  '[aria-label*="trending"]',
  'a[href*="/likes"]',
  'a[href*="/retweets"]',
  'a[href*="/quotes"]',
  'a[href*="/analytics"]',
  '[data-testid="HelpButton"]',
  '[data-testid="keyboardShortcutsDialog"]',
].join(', ');
const BOILERPLATE_PATTERNS = [
  /get our weekly newsletter/i,
  /subscribe for more/i,
  /subscribe to/i,
  /table of contents/i,
  /related content/i,
  /add your email/i,
  /privacy policy/i,
  /terms/i,
  /contact/i,
];
const NFX_SKIP_LINES = new Set([
  'Content',
  'Team',
  'Companies',
  'About',
  'Products',
  'Jobs',
  'News',
  'Signal',
  'Brieflink',
  'BriefLink',
  'NFX Masterclass',
  'Privacy Policy',
  'Terms',
  'Contact',
  'Subscribe',
  'Add your email',
  'Related Content',
  'Table of Contents',
]);
const NFX_END_PATTERNS = [
  /^Subscribe for more /i,
  /^As Founders ourselves,/i,
  /^Related Content$/i,
  /^Privacy Policy$/i,
  /^©\d{4}/,
];

let cachedSelection = {
  sourceType: 'selection',
  text: '',
  updatedAt: 0,
  url: '',
};

function normalizeWhitespace(text, { preserveParagraphs = true } = {}) {
  let normalized = `${text ?? ''}`
    .replace(/\u00A0/g, ' ')
    .replace(/\u200B/g, '')
    .replace(/\r\n/g, '\n')
    .replace(/\r/g, '\n');
  normalized = normalized.replace(/[ \t]+\n/g, '\n').replace(/\n[ \t]+/g, '\n');
  if (preserveParagraphs) {
    normalized = normalized.replace(/[ \t]{2,}/g, ' ');
    normalized = normalized.replace(/\n{3,}/g, '\n\n');
  } else {
    normalized = normalized.replace(/\s+/g, ' ');
  }
  return normalized.trim();
}

function stripSpeechArtifacts(text, { preserveParagraphs = true } = {}) {
  let normalized = normalizeWhitespace(text, { preserveParagraphs });
  normalized = normalized.replace(/^[ \t]*Show more[ \t]*$/gim, '');
  normalized = normalized.replace(/^[ \t]*Translate post[ \t]*$/gim, '');
  normalized = normalized.replace(/^[ \t]*Who can reply\?[ \t]*$/gim, '');
  normalized = normalized.replace(/^[ \t]*To view keyboard shortcuts,? press .+$/gim, '');
  normalized = normalized.replace(/https?:\/\/\S+/gi, '');
  normalized = normalized.replace(/www\.\S+/gi, '');
  normalized = normalized.replace(/\n{3,}/g, '\n\n');
  return normalized.trim();
}

function truncatePreview(text, maxChars = 240) {
  if (!text) return '';
  if (text.length <= maxChars) return text;
  return `${text.slice(0, maxChars).trimEnd()}…`;
}

function dedupeAdjacentLines(lines) {
  const deduped = [];
  for (const line of lines) {
    if (!line) continue;
    if (deduped[deduped.length - 1] === line) continue;
    deduped.push(line);
  }
  return deduped;
}

function isLikelyParagraph(line) {
  return line.length >= 70 || /[.!?]["')\]]?$/.test(line);
}

function isNfxHost() {
  return NFX_HOSTS.has(location.hostname);
}

function normalizeNfxLines(text) {
  return dedupeAdjacentLines(
    normalizeWhitespace(text || '', { preserveParagraphs: true })
      .split('\n')
      .map((line) => stripSpeechArtifacts(line, { preserveParagraphs: false }))
      .filter(Boolean),
  );
}

function looksLikeNfxMetadata(line) {
  return /@[a-z0-9_]+/i.test(line)
    || /\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b/i.test(line)
    || /^AI$/i.test(line);
}

function scoreNfxArticleLines(lines, title) {
  if (!lines.length) return Number.NEGATIVE_INFINITY;

  const titleIndex = title ? lines.findIndex((line) => line === title) : -1;
  const startIndex = titleIndex >= 0 ? titleIndex : 0;

  let proseChars = 0;
  let paragraphCount = 0;
  for (let index = startIndex; index < lines.length; index += 1) {
    const line = lines[index];
    if (!line) continue;
    if (NFX_END_PATTERNS.some((pattern) => pattern.test(line))) break;
    if (line.includes('from NFX')) continue;
    if (NFX_SKIP_LINES.has(line)) continue;
    if (looksLikeNfxMetadata(line)) continue;
    if (!isLikelyParagraph(line)) continue;

    proseChars += line.length;
    paragraphCount += 1;
  }

  let score = proseChars + (paragraphCount * 260);
  if (titleIndex >= 0) score += 400;
  if (paragraphCount < 3) score -= 3000;
  return score;
}

function extractNfxArticle() {
  const title = stripSpeechArtifacts(
    document.querySelector('h1')?.textContent
      || document.title.replace(/\s*\|\s*NFX.*$/, ''),
    { preserveParagraphs: false },
  );
  const roots = [
    document.querySelector('article'),
    document.querySelector('main'),
    document.body,
  ].filter(Boolean);
  const candidates = [];

  for (const root of roots) {
    const lines = normalizeNfxLines(root.innerText || '');
    if (!lines.length) continue;
    candidates.push({
      lines,
      score: scoreNfxArticleLines(lines, title),
    });
  }

  const lines = candidates
    .sort((left, right) => right.score - left.score)[0]?.lines
    || normalizeNfxLines(document.body.innerText || '');
  if (!lines.length) return null;

  const titleIndex = title ? lines.findIndex((line) => line === title) : -1;
  const startIndex = titleIndex >= 0 ? titleIndex : 0;
  const body = [];
  let bodyStarted = false;
  let skippingToc = false;

  for (let index = startIndex; index < lines.length; index += 1) {
    const line = lines[index];
    if (!line) continue;

    if (index > startIndex && NFX_END_PATTERNS.some((pattern) => pattern.test(line))) {
      break;
    }
    if (line.includes('from NFX')) continue;
    if (NFX_SKIP_LINES.has(line)) {
      if (line === 'Table of Contents') skippingToc = true;
      continue;
    }

    if (index === startIndex && title) {
      body.push(title);
      continue;
    }

    if (!bodyStarted) {
      if (skippingToc) {
        if (!isLikelyParagraph(line) && !/^#+\s*/.test(line)) {
          continue;
        }
        skippingToc = false;
      }

      if (looksLikeNfxMetadata(line)) continue;
      if (!isLikelyParagraph(line) && !/^#+\s*/.test(line)) continue;
      bodyStarted = true;
    }

    if (NFX_SKIP_LINES.has(line)) continue;
    if (looksLikeNfxMetadata(line) && !bodyStarted) continue;
    body.push(line);
  }

  const cleaned = dedupeAdjacentLines(body)
    .filter((line) => line && !line.includes('from NFX'));
  const text = cleaned.join('\n\n').trim();
  if (!text || text.length < 200) return null;

  return finalizeExtraction({
    sourceType: 'article',
    text,
    title,
  });
}

function isTextInputElement(element) {
  if (!element) return false;
  if (element instanceof HTMLTextAreaElement) return true;
  if (!(element instanceof HTMLInputElement)) return false;
  const type = (element.type || 'text').toLowerCase();
  return INPUT_TYPES_WITH_TEXT_SELECTION.has(type);
}

function asElement(node) {
  if (!node) return null;
  if (node.nodeType === Node.ELEMENT_NODE) return node;
  return node.parentElement || null;
}

function getTextInputSelection() {
  const active = document.activeElement;
  if (!isTextInputElement(active)) return null;

  const start = active.selectionStart ?? 0;
  const end = active.selectionEnd ?? 0;
  if (end <= start) return null;

  const text = active.value.slice(start, end).trim();
  if (!text) return null;

  return {
    sourceType: 'selection',
    text,
    node: active,
  };
}

function getDomSelection() {
  const selection = window.getSelection();
  if (!selection || selection.rangeCount === 0 || selection.isCollapsed) return null;

  const text = selection.toString().trim();
  if (!text) return null;

  return {
    sourceType: 'selection',
    text,
    node: asElement(selection.anchorNode),
  };
}

function rememberSelection() {
  const selection = getTextInputSelection() || getDomSelection();
  if (!selection?.text) return;

  cachedSelection = {
    sourceType: selection.sourceType,
    text: selection.text,
    updatedAt: Date.now(),
    url: location.href,
  };
}

function getRecentSelection() {
  if (!cachedSelection.text) return null;
  if (cachedSelection.url !== location.href) return null;
  if ((Date.now() - cachedSelection.updatedAt) > RECENT_SELECTION_TTL_MS) return null;
  return { ...cachedSelection };
}

function getLiveSelection() {
  return getTextInputSelection() || getDomSelection();
}

function pruneNode(root, selector) {
  if (!root || !selector) return;
  for (const node of root.querySelectorAll(selector)) {
    node.remove();
  }
}

function getLinkTextLength(node) {
  return Array.from(node.querySelectorAll('a'))
    .map((link) => (link.textContent || '').trim().length)
    .reduce((sum, length) => sum + length, 0);
}

function removeBoilerplateNodes(root) {
  if (!root) return;

  const candidates = Array.from(root.querySelectorAll('div, section, aside, nav, footer, ul, ol'));
  for (const node of candidates) {
    const text = stripSpeechArtifacts(node.textContent || '', { preserveParagraphs: true });
    if (!text) continue;

    const paragraphTexts = Array.from(node.querySelectorAll('p, blockquote'))
      .map((paragraph) => stripSpeechArtifacts(paragraph.textContent || '', { preserveParagraphs: false }))
      .filter(Boolean);
    const paragraphCount = paragraphTexts.length;
    const longParagraphCount = paragraphTexts.filter((paragraph) => paragraph.length >= 90).length;
    const linkCount = node.querySelectorAll('a').length;
    const linkTextLength = getLinkTextLength(node);
    const linkDensity = text.length ? (linkTextLength / text.length) : 0;
    const matchesBoilerplatePattern = BOILERPLATE_PATTERNS.some((pattern) => pattern.test(text));
    const looksLikeSignup = /newsletter|subscribe/i.test(text) && node.querySelector('form, input, button');
    const looksLikeToc = /table of contents/i.test(text) || (
      paragraphCount <= 1
      && linkCount >= 3
      && text.length < 1600
      && /contents/i.test(text)
    );
    const looksLikeLinkCluster = linkDensity > 0.55 && paragraphCount <= 1 && text.length < 1600;
    const looksLikeBoilerplate = matchesBoilerplatePattern && (
      text.length < 1200
      || longParagraphCount === 0
      || linkDensity > 0.4
      || Boolean(node.querySelector('form, input, button'))
    );

    if (looksLikeBoilerplate || looksLikeSignup || looksLikeToc || looksLikeLinkCluster) {
      node.remove();
    }
  }
}

function serializeNodeText(node) {
  if (!node) return '';
  if (node.nodeType === Node.TEXT_NODE) return node.textContent || '';
  if (node.nodeType !== Node.ELEMENT_NODE) return '';

  const element = node;
  if (element.matches(SERIALIZE_SKIP_SELECTOR)) return '';
  if (element.tagName === 'BR') return '\n';
  if (element.tagName === 'PRE') return '\n(see code example)\n';

  let text = '';
  const isHeading = /^H[1-6]$/.test(element.tagName);
  const isListItem = element.tagName === 'LI';
  const isBlock = BLOCK_TAGS.has(element.tagName);

  if (isHeading || isBlock) text += '\n';
  if (isListItem) {
    const parent = element.parentElement;
    if (parent?.tagName === 'OL') {
      const items = Array.from(parent.children).filter((child) => child.tagName === 'LI');
      const index = items.indexOf(element) + 1;
      text += `${index}. `;
    } else {
      text += '- ';
    }
  }

  let childText = '';
  for (const child of element.childNodes) {
    childText += serializeNodeText(child);
  }
  text += isListItem ? childText.replace(/^\n+/, '') : childText;

  if (isHeading || isBlock) text += '\n';
  return text;
}

function extractNodeText(node, options = {}) {
  const text = serializeNodeText(node);
  return stripSpeechArtifacts(text, options);
}

function finalizeExtraction(extraction) {
  if (!extraction?.text) return null;
  const text = extraction.text.trim();
  if (!text) return null;

  return {
    charCount: text.length,
    previewText: truncatePreview(text),
    sourceType: extraction.sourceType || 'selection',
    text,
    title: extraction.title || document.title || '',
    url: location.href,
    warnings: extraction.warnings || [],
  };
}

function scoreContainer(element) {
  const text = extractNodeText(element, { preserveParagraphs: true });
  if (text.length < 80) return null;

  const paragraphTexts = Array.from(element.querySelectorAll('p, blockquote'))
    .map((node) => stripSpeechArtifacts(node.textContent || '', { preserveParagraphs: false }))
    .filter(Boolean);
  const paragraphCount = paragraphTexts.length;
  const longParagraphs = paragraphTexts.filter((paragraph) => paragraph.length >= 90);
  const paragraphTextLength = longParagraphs.reduce((sum, paragraph) => sum + paragraph.length, 0);
  const averageParagraphLength = paragraphCount
    ? Math.round(paragraphTexts.reduce((sum, paragraph) => sum + paragraph.length, 0) / paragraphCount)
    : 0;
  const headingCount = element.querySelectorAll('h1, h2, h3').length;
  const linkCount = element.querySelectorAll('a').length;
  const formCount = element.querySelectorAll('form, input, button').length;
  const listCount = element.querySelectorAll('ol, ul').length;
  const linkTextLength = getLinkTextLength(element);
  const linkDensity = text.length ? (linkTextLength / text.length) : 0;
  const boilerplatePenalty = BOILERPLATE_PATTERNS.reduce(
    (sum, pattern) => sum + (pattern.test(text) ? 700 : 0),
    0,
  );

  let score = Math.min(text.length, 2200);
  score += Math.min(paragraphTextLength, 5000);
  score += longParagraphs.length * 280;
  score += Math.min(averageParagraphLength * 2, 500);
  score += Math.min(headingCount * 120, 360);
  score -= Math.min(linkCount * 25, 500);
  score -= Math.min(listCount * 80, 320);
  score -= formCount * 260;
  score -= Math.round(linkDensity * 900);
  score -= boilerplatePenalty;
  if (element.matches('article, main, section, [role="main"]')) score += 180;
  if (text.length > 7000) score -= 500;
  if (paragraphTextLength < 300 && headingCount < 2) score -= 1000;
  if (longParagraphs.length < 2 && paragraphTextLength < 500) score -= 1200;

  return { score, text };
}

function findBestBlockContainer(startNode) {
  const anchor = asElement(startNode) || document.body;
  if (!anchor) return null;

  let best = null;
  let depth = 0;
  for (let current = anchor; current && current !== document.body; current = current.parentElement) {
    depth += 1;
    if (!CONTAINER_TAGS.has(current.tagName) && !current.matches('article, main, section, [role="main"]')) {
      continue;
    }
    if (current.matches('nav, header, footer, aside, form')) continue;

    const scored = scoreContainer(current);
    if (!scored) continue;

    const weightedScore = scored.score - (depth * 60);
    if (!best || weightedScore > best.score) {
      best = { node: current, score: weightedScore };
    }
  }

  if (best?.node) return best.node;

  for (let current = anchor; current && current !== document.body; current = current.parentElement) {
    if (CONTAINER_TAGS.has(current.tagName)) return current;
  }

  return null;
}

function extractGenericBlock(baseNode) {
  const container = findBestBlockContainer(baseNode);
  if (!container) return null;

  const clone = container.cloneNode(true);
  pruneNode(clone, PRUNE_SELECTOR);
  const text = extractNodeText(clone, { preserveParagraphs: true });
  if (!text) return null;

  return finalizeExtraction({
    sourceType: 'block',
    text,
  });
}

function extractGenericArticle() {
  const root = document.querySelector('article, [role="main"], main') || document.body;
  if (!root) return null;

  const clone = root.cloneNode(true);
  pruneNode(clone, isXHost() ? X_ARTICLE_PRUNE_SELECTOR : PRUNE_SELECTOR);
  removeBoilerplateNodes(clone);

  const candidates = [clone, ...Array.from(clone.querySelectorAll('article, section, div')).slice(0, 160)];
  let best = null;
  for (const candidate of candidates) {
    const scored = scoreContainer(candidate);
    if (!scored) continue;
    if (!best || scored.score > best.score) {
      best = { node: candidate, score: scored.score };
    }
  }

  const target = best?.node || clone;
  const text = extractNodeText(target, { preserveParagraphs: true });
  if (!text) return null;

  return finalizeExtraction({
    sourceType: 'article',
    text,
  });
}

function isXHost() {
  return X_HOSTS.has(location.hostname);
}

function isXArticlePath() {
  return /\/article(?:s)?\//.test(location.pathname);
}

function isXStatusPath() {
  return /\/status\/\d+/.test(location.pathname);
}

function findXPrimaryColumn() {
  return document.querySelector('[data-testid="primaryColumn"]')
    || document.querySelector('[role="main"]')
    || document.querySelector('main');
}

function findXPostContainer(baseNode) {
  const anchor = asElement(baseNode);
  const anchoredPost = anchor?.closest?.('article[data-testid="tweet"]');
  if (anchoredPost) return anchoredPost;

  if (!isXStatusPath()) return null;

  const primaryColumn = findXPrimaryColumn();
  if (!primaryColumn) return null;

  return primaryColumn.querySelector('article[data-testid="tweet"][tabindex="-1"]')
    || primaryColumn.querySelector('article[data-testid="tweet"]');
}

function normalizeXPostText(text) {
  let normalized = stripSpeechArtifacts(text, {
    preserveParagraphs: true,
  });
  normalized = normalized.replace(/^[ \t]*·[ \t]*$/gim, '');
  normalized = normalized.replace(/\n{3,}/g, '\n\n');
  return normalized.trim();
}

function extractXPost(baseNode) {
  const post = findXPostContainer(baseNode);
  if (!post) return null;

  const textNodes = Array.from(post.querySelectorAll('[data-testid="tweetText"]'))
    .map((node) => stripSpeechArtifacts(node.innerText || '', {
      preserveParagraphs: true,
      }))
    .filter(Boolean);
  if (!textNodes.length) return null;

  const [mainText, ...quotedTexts] = textNodes;
  let text = mainText;
  if (quotedTexts.length) {
    text += `\n\nQuoted post:\n${quotedTexts.join('\n\n')}`;
  }

  return finalizeExtraction({
    sourceType: 'x-post',
    text: normalizeXPostText(text),
  });
}

function selectBestStructuredSubtree(root) {
  const candidates = [root, ...Array.from(root.querySelectorAll('article, section, div')).slice(0, 80)];
  let best = null;

  for (const candidate of candidates) {
    const textLength = (candidate.textContent || '').trim().length;
    if (textLength < 200) continue;

    const paragraphCount = candidate.querySelectorAll('p').length;
    const headingCount = candidate.querySelectorAll('h1, h2, h3').length;
    const listCount = candidate.querySelectorAll('ol, ul').length;
    const linkCount = candidate.querySelectorAll('a').length;

    let score = Math.min(textLength, 5000);
    score += paragraphCount * 140;
    score += headingCount * 180;
    score += listCount * 120;
    score -= Math.min(linkCount * 15, 300);

    if (!best || score > best.score) {
      best = { node: candidate, score };
    }
  }

  return best?.node || root;
}

function extractXArticle() {
  const titleEl = document.querySelector('[data-testid="twitter-article-title"]');
  const title = titleEl ? stripSpeechArtifacts(titleEl.textContent || '') : '';

  const body = document.querySelector('[data-testid="twitterArticleRichTextView"]');
  if (!body) return null;

  const clone = body.cloneNode(true);

  // Prune embedded tweets and UI chrome from article body
  pruneNode(clone, [
    X_ARTICLE_PRUNE_SELECTOR,
    '[data-testid="simpleTweet"]',
    '[role="group"]',
    '[data-testid="card.wrapper"]',
    '[data-testid="UserCell"]',
  ].join(', '));

  let text = title ? `${title}\n\n` : '';
  text += extractNodeText(clone, { preserveParagraphs: true });
  text = normalizeXPostText(text);

  if (!text || text.length < 200) return null;
  return finalizeExtraction({ sourceType: 'x-article', text });
}

function extractFromX(mode, selection) {
  if (mode === 'selection' && selection?.text) {
    return finalizeExtraction({
      sourceType: selection.sourceType || 'selection',
      text: stripSpeechArtifacts(selection.text, { preserveParagraphs: true }),
    });
  }
  if (mode === 'selection') return null;

  if (isXArticlePath()) {
    const article = extractXArticle();
    if (article) return article;
  }

  if (mode === 'article') {
    return extractXArticle() || extractXPost(selection?.node) || null;
  }

  if (mode === 'block') {
    return extractXPost(selection?.node) || extractGenericBlock(selection?.node) || extractXArticle() || null;
  }

  return (
    extractXPost(selection?.node)
    || extractXArticle()
    || extractGenericBlock(selection?.node)
    || null
  );
}

function extractGeneric(mode, selection) {
  if (mode === 'selection') {
    return finalizeExtraction({
      sourceType: selection?.sourceType || 'selection',
      text: stripSpeechArtifacts(selection?.text || '', { preserveParagraphs: true }),
    });
  }

  if (mode === 'block') {
    return extractGenericBlock(selection?.node) || extractGenericArticle();
  }

  return extractGenericArticle();
}

function extractCurrentText(mode = 'selection') {
  const liveSelection = getLiveSelection();
  if (liveSelection?.text) {
    cachedSelection = {
      sourceType: liveSelection.sourceType,
      text: liveSelection.text,
      updatedAt: Date.now(),
      url: location.href,
    };
  }

  const selection = liveSelection || getRecentSelection();
  if (isNfxHost() && mode === 'article') {
    return extractNfxArticle() || extractGenericArticle();
  }
  if (isXHost()) {
    return extractFromX(mode, selection);
  }

  return extractGeneric(mode, selection);
}

document.addEventListener('selectionchange', rememberSelection, true);
document.addEventListener('mouseup', rememberSelection, true);
document.addEventListener('keyup', rememberSelection, true);

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg.type === 'GET_SELECTION') {
    const extraction = extractCurrentText(msg.mode || 'selection');
    sendResponse(extraction || {
      charCount: 0,
      previewText: '',
      sourceType: 'selection',
      text: '',
      title: document.title || '',
      url: location.href,
      warnings: ['No readable text found'],
    });
  }
});

globalThis.__LOCAL_VOICE_CONTENT_SCRIPT_READY__ = true;

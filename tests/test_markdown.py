import unittest

from service.core.markdown import strip_markdown


class StripMarkdownTests(unittest.TestCase):
    def test_strips_frontmatter_and_common_markdown(self):
        source = """---
title: Example
author: Test
---

# Heading

This is **bold** with a [link](https://example.com).
"""

        self.assertEqual(
            strip_markdown(source),
            "Heading\n\nThis is bold with a link.",
        )

    def test_strips_lists_blockquotes_and_code_fences(self):
        source = """
> Quoted line

- first item
- [x] done item

```py
print("hello")
```
"""

        self.assertEqual(
            strip_markdown(source),
            'Quoted line\nfirst item\ndone item\n\nprint("hello")',
        )


if __name__ == "__main__":
    unittest.main()

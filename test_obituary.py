import unittest
from types import SimpleNamespace
from unittest.mock import patch

from feedparser import FeedParserDict

import dgd_bot


def gurdon_entry(**changes):
    data = {
        "title": "Sir John B. Gurdon (1933–2025)",
        "link": "https://onlinelibrary.wiley.com/doi/10.1111/dgd.70039?af=R",
        "prism_section": "OBITUARY",
        "tags": [{"term": "OBITUARY"}],
        "authors": [{"name": "Makoto Asashima"}],
        "summary": "Development, Growth & Differentiation, Volume 68, Issue 1",
        "content": [],
    }
    data.update(changes)
    return FeedParserDict(data)


class ObituaryTests(unittest.TestCase):
    def test_gurdon_article_uses_obituary_format(self):
        entry = gurdon_entry()
        section = dgd_bot.obituary_section(entry)
        self.assertEqual(section, "OBITUARY")
        self.assertEqual(
            dgd_bot.format_obituary_post(entry, "10.1111/dgd.70039", section),
            "OBITUARY\nSir John B. Gurdon (1933–2025)\n"
            "Makoto Asashima\nhttps://doi.org/10.1111/dgd.70039",
        )

    def test_category_fallback_and_long_title_preserve_doi(self):
        entry = gurdon_entry(
            prism_section="",
            title="A" * 400,
            authors=[{"name": "Researcher " * 30}],
        )
        section = dgd_bot.obituary_section(entry)
        text = dgd_bot.format_obituary_post(entry, "10.1111/dgd.70039", section)
        self.assertEqual(section, "OBITUARY")
        self.assertLessEqual(len(text), dgd_bot.MAX_LEN)
        self.assertTrue(text.endswith("\nhttps://doi.org/10.1111/dgd.70039"))
        self.assertEqual(dgd_bot.obituary_section(gurdon_entry(tags=[])), "OBITUARY")
        self.assertIsNone(dgd_bot.obituary_section(gurdon_entry(prism_section="REVIEW ARTICLE", tags=[])))

    def test_main_posts_and_emails_once(self):
        entry = gurdon_entry()
        posted = []
        posts = []
        emails = []

        def save_posted(items):
            posted[:] = items

        with (
            patch.object(dgd_bot.feedparser, "parse", return_value=SimpleNamespace(entries=[entry])),
            patch.object(dgd_bot, "load_dotenv"),
            patch.object(dgd_bot, "load_posted", side_effect=lambda: posted.copy()),
            patch.object(dgd_bot, "save_posted", side_effect=save_posted),
            patch.object(dgd_bot, "post_to_bluesky", side_effect=posts.append),
            patch.object(dgd_bot, "send_email", side_effect=emails.append),
        ):
            dgd_bot.main()
            dgd_bot.main()

        self.assertEqual(len(posts), 1)
        self.assertEqual(len(emails), 1)
        self.assertEqual(posted, ["10.1111/dgd.70039"])
        self.assertIn("OBITUARY\nSir John B. Gurdon", posts[0])
        self.assertIn(posts[0], emails[0])


if __name__ == "__main__":
    unittest.main()

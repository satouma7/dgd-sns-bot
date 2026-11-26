import unittest
from email import policy
from email.parser import BytesParser
from types import SimpleNamespace
from unittest.mock import patch

from feedparser import FeedParserDict

import dgd_bot

IMAGE_URL = "https://onlinelibrary.wiley.com/cms/asset/example/dgd70039-toc-0001-m.png"


def gurdon_entry(**changes):
    data = {
        "title": "Sir John B. Gurdon (1933–2025)",
        "link": "https://onlinelibrary.wiley.com/doi/10.1111/dgd.70039?af=R",
        "prism_section": "OBITUARY",
        "tags": [{"term": "OBITUARY"}],
        "authors": [{"name": "Makoto Asashima"}],
        "summary": "Development, Growth & Differentiation, Volume 68, Issue 1",
        "content": [{"type": "text/html", "value": f'<img alt="Sir John B. Gurdon" src="{IMAGE_URL}" />'}],
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

    def test_image_url_is_taken_from_rss_html(self):
        self.assertEqual(dgd_bot.obituary_image_url(gurdon_entry()), IMAGE_URL)
        self.assertIsNone(dgd_bot.obituary_image_url(gurdon_entry(content=[])))

    def test_bluesky_image_keeps_doi_facet(self):
        sent = []
        client = SimpleNamespace(send_image=lambda **kwargs: sent.append(kwargs))
        with patch.object(dgd_bot, "bsky_client", client):
            self.assertTrue(dgd_bot.post_to_bluesky(
                "OBITUARY\nhttps://doi.org/10.1111/dgd.70039",
                image=b"image bytes", image_alt="DGD article image"))
        self.assertEqual(sent[0]["image"], b"image bytes")
        self.assertEqual(sent[0]["image_alt"], "DGD article image")
        self.assertEqual(sent[0]["facets"][0]["features"][0]["uri"],
                         "https://doi.org/10.1111/dgd.70039")

    def test_main_posts_and_emails_once(self):
        entry = gurdon_entry()
        posted = []
        posts = []
        emails = []

        def save_posted(items):
            posted[:] = items

        def record_post(text, **kwargs):
            posts.append((text, kwargs))
            return True

        def record_email(text, **kwargs):
            emails.append((text, kwargs))
            return True

        with (
            patch.object(dgd_bot.feedparser, "parse", return_value=SimpleNamespace(entries=[entry])),
            patch.object(dgd_bot, "load_dotenv"),
            patch.object(dgd_bot, "load_posted", side_effect=lambda: posted.copy()),
            patch.object(dgd_bot, "save_posted", side_effect=save_posted),
            patch.object(dgd_bot, "download_obituary_image", return_value=(b"image bytes", "image/png")),
            patch.object(dgd_bot, "post_to_bluesky", side_effect=record_post),
            patch.object(dgd_bot, "send_email", side_effect=record_email),
        ):
            dgd_bot.main()
            dgd_bot.main()

        self.assertEqual(len(posts), 1)
        self.assertEqual(len(emails), 1)
        self.assertEqual(posted, ["10.1111/dgd.70039"])
        self.assertIn("OBITUARY\nSir John B. Gurdon", posts[0][0])
        self.assertEqual(posts[0][1]["image"], b"image bytes")
        self.assertIn(posts[0][0], emails[0][0])
        self.assertEqual(emails[0][1]["attachment"],
                         (b"image bytes", "image/png", "dgd-obituary.png"))

    def test_missing_image_does_not_mark_article_posted(self):
        entry = gurdon_entry(content=[])
        with (
            patch.object(dgd_bot.feedparser, "parse", return_value=SimpleNamespace(entries=[entry])),
            patch.object(dgd_bot, "load_dotenv"),
            patch.object(dgd_bot, "load_posted", return_value=[]),
            patch.object(dgd_bot, "save_posted") as save,
            patch.object(dgd_bot, "post_to_bluesky") as post,
            patch.object(dgd_bot, "send_email") as mail,
        ):
            with self.assertRaisesRegex(RuntimeError, "No RSS image"):
                dgd_bot.main()
        save.assert_called_once_with([])
        post.assert_not_called()
        mail.assert_not_called()

    def test_missing_obituary_image_preserves_other_successful_posts(self):
        article = gurdon_entry(
            title="A regular DGD article",
            link="https://onlinelibrary.wiley.com/doi/10.1111/dgd.test-article?af=R",
            prism_section="REVIEW ARTICLE",
            tags=[{"term": "REVIEW ARTICLE"}],
        )
        obituary = gurdon_entry(content=[])
        with (
            patch.object(dgd_bot.feedparser, "parse", return_value=SimpleNamespace(entries=[article, obituary])),
            patch.object(dgd_bot, "load_dotenv"),
            patch.object(dgd_bot, "load_posted", return_value=[]),
            patch.object(dgd_bot, "save_posted") as save,
            patch.object(dgd_bot, "post_to_bluesky", return_value=True) as post,
            patch.object(dgd_bot, "send_email", return_value=True) as mail,
        ):
            with self.assertRaisesRegex(RuntimeError, "No RSS image"):
                dgd_bot.main()
        save.assert_called_once_with(["10.1111/dgd.test-article"])
        post.assert_called_once()
        mail.assert_called_once()

    def test_email_contains_image_attachment(self):
        with (
            patch.dict("os.environ", {
                "MAIL_FROM": "bot@example.org",
                "MAIL_TO": "sato@example.org,momozu@example.org",
                "MAIL_USER": "bot@example.org",
                "MAIL_PASS": "test-password",
            }),
            patch.object(dgd_bot.smtplib, "SMTP_SSL") as smtp,
        ):
            self.assertTrue(dgd_bot.send_email(
                "OBITUARY\nhttps://doi.org/10.1111/dgd.70039",
                attachment=(b"image bytes", "image/png", "dgd-obituary.png")))
        raw = smtp.return_value.__enter__.return_value.sendmail.call_args.args[2]
        message = BytesParser(policy=policy.default).parsebytes(raw)
        self.assertEqual(message["To"], "sato@example.org, momozu@example.org")
        self.assertEqual(message.get_body(preferencelist=("plain",)).get_content().splitlines()[0], "OBITUARY")
        attachment = list(message.iter_attachments())[0]
        self.assertEqual(attachment.get_content_type(), "image/png")
        self.assertEqual(attachment.get_payload(decode=True), b"image bytes")


if __name__ == "__main__":
    unittest.main()

"""
Test script: sends email for a specific DOI without posting to Bluesky/X.
Usage: python test_email.py [doi]
Default DOI: 10.1111/dgd.70062 (2026-06-21 paper)
"""
import sys
import feedparser
from dotenv import load_dotenv
from dgd_bot import (
    send_email, extract_doi, extract_authors, shorten_title,
    doi_link, normalize_text, trim_post,
    extract_volume_issue, extract_cover_text, extract_cover_image,
    fetch_cover_image_from_page, get_html, clean_link,
    MAIL_PREFIX, MAIL_SUFFIX, RSS_URL
)

args = [a for a in sys.argv[1:] if not a.startswith("-")]
flags = [a for a in sys.argv[1:] if a.startswith("-")]
TARGET_DOI = args[0] if args else "10.1111/dgd.70062"
AUTO_YES = "--yes" in flags or "-y" in flags

load_dotenv()
feed = feedparser.parse(RSS_URL)

entry = next((e for e in feed.entries if extract_doi(e.link) == TARGET_DOI), None)
if entry is None:
    print(f"DOI not found in RSS feed: {TARGET_DOI}")
    sys.exit(1)

title = entry.title
link = entry.link
html = get_html(entry)
doi = extract_doi(link)

if title == "Issue Information":
    volume = issue = None
    for e in feed.entries:
        v, i = extract_volume_issue(e.summary)
        if v:
            volume, issue = v, i
            break
    cover_text = extract_cover_text(html)
    cover_image = extract_cover_image(html)
    if cover_image is None:
        cover_image = fetch_cover_image_from_page(link)
    toc_lines = []
    for e in feed.entries:
        if e.title == "Issue Information":
            continue
        a = extract_authors(e) or ""
        d = extract_doi(e.link) or ""
        toc_lines.append(f"{e.title}\n{a}\n{doi_link(d)}")
    toc_text = "\n\n".join(toc_lines)
    email_body = (
        f"DGD Volume {volume}, Issue {issue} was released!!\n\n"
        f"Cover: {cover_text}\n"
        f"{doi_link(doi)}\n\n"
        f"--- Table of Contents ---\n\n"
        f"{toc_text}"
    )
    email_text = MAIL_PREFIX + normalize_text(email_body) + MAIL_SUFFIX
else:
    authors = extract_authors(entry) or ""
    post_text = (
        "New article in DGD.\n"
        f"{shorten_title(title)}\n"
        f"{authors}\n"
        f"{doi_link(doi)}"
    )
    post_text = normalize_text(trim_post(post_text))
    email_text = MAIL_PREFIX + post_text + MAIL_SUFFIX

print("=== Email preview ===")
print(email_text)
print("=====================")
if AUTO_YES:
    ok = send_email(email_text)
    print("Email sent." if ok else "Email failed.")
    sys.exit(0 if ok else 1)

confirm = input("\nSend this email? [y/N]: ")
if confirm.strip().lower() == "y":
    ok = send_email(email_text)
    print("Email sent." if ok else "Email failed.")
else:
    print("Cancelled.")

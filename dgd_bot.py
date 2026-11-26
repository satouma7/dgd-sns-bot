import feedparser
import json
import os
import re
import requests
from atproto import Client
import tweepy
from dotenv import load_dotenv
import smtplib
import base64
from email.message import EmailMessage
from email import policy
from html import unescape
from urllib.parse import urlsplit

RSS_URL = "https://onlinelibrary.wiley.com/action/showFeed?type=etoc&feed=rss&jc=1440169x"
POSTED_FILE = "posted.json"
MAX_TITLE = 180
MAX_LEN = 300
MAX_IMAGE_BYTES = 1_000_000
DRY_RUN = False
bsky_client = None

def send_email(text, attachment=None):
    try:
        def to_ascii(s):
            return (s or "").encode('ascii', 'ignore').decode('ascii')
        from_addr = to_ascii(os.getenv("MAIL_FROM"))
        to_addrs = [to_ascii(a.strip()) for a in (os.getenv("MAIL_TO") or "").split(",") if a.strip()]
        if attachment:
            image, content_type, filename = attachment
            msg = EmailMessage()
            msg["From"] = from_addr
            msg["To"] = ", ".join(to_addrs)
            msg["Subject"] = "DGD Bot Post"
            msg.set_content(text, charset="utf-8")
            msg.add_attachment(image, maintype="image", subtype=content_type.split("/", 1)[1], filename=filename)
            raw_msg = msg.as_bytes(policy=policy.SMTP)
        else:
            body_b64 = base64.b64encode(text.encode('utf-8')).decode('ascii')
            raw_msg = "\r\n".join([
                f"From: {from_addr}",
                f"To: {', '.join(to_addrs)}",
                "Subject: DGD Bot Post",
                "MIME-Version: 1.0",
                "Content-Type: text/plain; charset=utf-8",
                "Content-Transfer-Encoding: base64",
                "",
                body_b64
            ]).encode('ascii')
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(os.getenv("MAIL_USER"), os.getenv("MAIL_PASS"))
            server.sendmail(from_addr, to_addrs, raw_msg)
        return True
    except Exception as e:
        print(f"Email sending failed: {repr(e)}")
        return False

def post_to_x(text):
    if DRY_RUN:
        print(f"DRY RUN: Posting to X - \n{text}")
        return
    try:
        client = tweepy.Client(
            consumer_key = os.getenv("X_CONSUMER_KEY"),
            consumer_secret = os.getenv("X_CONSUMER_SECRET"),
            access_token = os.getenv("X_ACCESS_TOKEN"),
            access_token_secret = os.getenv("X_ACCESS_TOKEN_SECRET"),
        )
        client.create_tweet(text=text)
    except Exception as e:
        print(f"X post failed: {e}")

def post_to_bluesky(text, image=None, image_alt=""):
    global bsky_client
    if DRY_RUN:
        print(f"DRY RUN: Posting to Bluesky - \n\n{text}")
        return True
    try:
        if bsky_client is None:
            bsky_client = Client()
            bsky_client.login(
                os.getenv("BSKY_USERNAME"),
                os.getenv("BSKY_PASSWORD"),
            )
        facets = []
        for match in re.finditer(r'https://doi\.org/\S+', text):
            url = match.group(0).rstrip(").,;")
            start = text.find(url)
            byte_start = len(text[:start].encode("utf-8"))
            byte_end = byte_start + len(url.encode("utf-8"))
            facets.append({
                "index": {
                    "byteStart": byte_start,
                    "byteEnd": byte_end
                },
                "features": [{
                    "$type": "app.bsky.richtext.facet#link",
                    "uri": url
                }]
            })
        if image is not None:
            bsky_client.send_image(text=text, image=image, image_alt=image_alt, facets=facets)
        elif facets:
            bsky_client.send_post(text=text, facets=facets)
        else:
            bsky_client.send_post(text=text)
        return True
    except Exception as e:
        print(f"Bluesky post failed: {repr(e)}")
        return False

def normalize_text(text):
    return text.replace('\xa0', ' ').replace('\u200b', '').strip()

def trim_post(text):
    if len(text) <= MAX_LEN:
        return text
    return text[:MAX_LEN-1] + "…"

def shorten_title(title):
    if len(title) > MAX_TITLE:
        return title[:MAX_TITLE-1] + "…"
    return title

def doi_link(doi):
    return f"https://doi.org/{doi}"

def extract_authors(entry, max_authors=10):
    if hasattr(entry, "authors") and entry.authors:
        raw = entry.authors[0].get("name")
        if not raw:
            return ""
        raw = raw.replace("\n", " ")
        names = [n.strip() for n in raw.split(",") if n.strip()]
        formatted = []
        for name in names:
            parts = name.split()
            if len(parts) == 1:
                formatted.append(parts[0])
                continue
            last = parts[-1]
            initials = "".join(p[0] for p in parts[:-1])
            formatted.append(f"{last} {initials}")
        if len(formatted) > max_authors:
            return ", ".join(formatted[:max_authors]) + ", et al."
        return ", ".join(formatted)
    return ""

def obituary_section(entry):
    sections = [entry.get("prism_section") or ""]
    sections.extend(tag.get("term") or "" for tag in (entry.get("tags") or []))
    for section in sections:
        label = section.strip().upper()
        if label in {"OBITUARY", "IN MEMORIAM", "MEMORIAL"}:
            return label
    return None

def format_obituary_post(entry, doi, section):
    authors = entry.get("authors") or []
    byline = authors[0].get("name", "") if authors else ""
    byline = " ".join(byline.split())
    lines = [section, shorten_title(normalize_text(entry.title))]
    if byline:
        lines.append(byline)

    link = doi_link(doi)
    body = "\n".join(lines)
    max_body_len = MAX_LEN - len(link) - 1
    if len(body) > max_body_len:
        body = body[:max_body_len - 1].rstrip(" ,;") + "…"
    return f"{body}\n{link}"

def obituary_image_url(entry):
    for content in entry.get("content") or []:
        if content.get("type") == "text/html":
            url = extract_cover_image(content.get("value") or "")
            if url:
                return unescape(url)
    return None

def download_obituary_image(entry):
    url = obituary_image_url(entry)
    if not url:
        raise ValueError(f"No RSS image for obituary: {entry.title}")
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname != "onlinelibrary.wiley.com" or not parsed.path.startswith("/cms/asset/"):
        raise ValueError(f"Unexpected obituary image URL: {url}")

    with requests.get(url, headers={"User-Agent": "DGD-SNS-Bot/1.0"},
                      timeout=20, stream=True, allow_redirects=False) as response:
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
        if content_type not in {"image/jpeg", "image/png", "image/webp"}:
            raise ValueError(f"Unexpected obituary image type: {content_type}")
        image = bytearray()
        for chunk in response.iter_content(65536):
            image.extend(chunk)
            if len(image) > MAX_IMAGE_BYTES:
                raise ValueError(f"Obituary image exceeds {MAX_IMAGE_BYTES} bytes")
    if not image:
        raise ValueError(f"Empty obituary image: {url}")
    return bytes(image), content_type

def generate_wiley_image_url(doi):
    suffix = doi.split('/')[-1] # dgd.70051
    id_num = suffix.replace('.', '') # dgd70051
    return f"https://onlinelibrary.wiley.com/cms/asset/10.1111/{suffix}/{id_num}-gra-0001-m.jpg"

def clean_link(link):
    return link.split("?")[0]

def fetch_cover_image_from_page(url):
    headers = {
        "User-Agent": "Mozilla/5.0"
    }
    r = requests.get(url + "?mobileUi=0", headers=headers)
    # print(f"DEBUG: Status Code: {r.status_code}")
    # print("DEBUG: HTML Snippet:", r.text[:1000])
    html = r.text
    match = re.search(r'property="og:image"\s*content="([^"]+)"', html)
    if match:
        return match.group(1)
    return None

def get_html(entry):
    if hasattr(entry, "content"):
        return entry.content[0].value
    if hasattr(entry, "summary"):
        return entry.summary
    if hasattr(entry, "summary_detail"):
        return entry.summary_detail.value
    return ""

def load_posted():
    if not os.path.exists(POSTED_FILE):
        return []
    with open(POSTED_FILE) as f:
        return json.load(f)

def save_posted(posted):
    with open(POSTED_FILE, "w") as f:
        json.dump(posted, f, indent=2)

def extract_doi(link):
    if "/doi/" not in link:
        return None
    doi = link.split("/doi/")[1]
    doi = doi.split("?")[0]
    return doi

def extract_volume_issue(text):
    match = re.search(r'Volume\s+(\d+),\s+Issue\s+(\d+)', text)
    if match:
        return match.group(1), match.group(2)
    return None, None

def extract_cover_image(html):
    match = re.search(r'<img[^>]*src="([^"]+)"', html)
    if match:
        return match.group(1)
    return None

def extract_cover_text(html):
    if not html:
        return None
    text = html.strip()
    text = text.split("\n\n")[0]
    text = text.replace("Cover Photograph:", "").strip()
    return text

MAIL_PREFIX = "桃津様、\nDGDの新着情報をお知らせします。BlueskyとXでのリポストをお願いします。\n\n"
MAIL_SUFFIX = "\n\n引き続きよろしくお願い致します。\n佐藤"

def main():
    load_dotenv()
    posted = load_posted()
    failures = []
    feed = feedparser.parse(RSS_URL)
    # print(feed)
    for entry in feed.entries:
        title = entry.title
        link = entry.link
        doi = extract_doi(link)
        section = obituary_section(entry)
        if doi in posted:
            continue

        # ---- Issue ----
        if title == "Issue Information":
            html = get_html(entry)
            volume = None
            issue = None
            for e in feed.entries:
                v, i = extract_volume_issue(e.summary)
                if v:
                    volume = v
                    issue = i
                    break
            cover_text = extract_cover_text(html)
            cover_image = extract_cover_image(html)
            if cover_image is None:
                cover_image = fetch_cover_image_from_page(link)
            # if cover_image is None:
            #     cover_image = generate_wiley_image_url(doi)

            toc_lines = []
            for e in feed.entries:
                if e.title == "Issue Information":
                    continue
                a = extract_authors(e) or ""
                d = extract_doi(e.link) or ""
                toc_lines.append(f"{e.title}\n{a}\n{doi_link(d)}")
            toc_text = "\n\n".join(toc_lines)

            post_text = (
                f"DGD Volume {volume}, Issue {issue} was released!!\n"
                f"{doi_link(doi)}\n"
                f"Cover: {cover_text}"
            )
            email_text = (
                f"DGD Volume {volume}, Issue {issue} was released!!\n\n"
                f"{doi_link(doi)}\n\n"
                f"Cover: {cover_text}\n\n"
                f"--- Table of Contents ---\n\n"
                f"{toc_text}"
            )
            print("POST ISSUE")
            post_text = normalize_text(trim_post(post_text))
            print(post_text)
            post_to_bluesky(post_text)
            send_email(MAIL_PREFIX + normalize_text(email_text) + MAIL_SUFFIX)
            # post_to_x(post_text)
            # print("IMAGE:", cover_image)
            # print(cover_text)
            # print("FETCH URL:", clean_link(link))
            # print("HTML:")
            # print(html)
            # ---- Article ----
        elif section:
            post_text = format_obituary_post(entry, doi, section)
            try:
                image, content_type = download_obituary_image(entry)
            except Exception as e:
                failures.append(f"Obituary image failed for {doi}: {e}")
                continue
            image_alt = f"Image accompanying the DGD obituary: {title}"
            extension = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}[content_type]
            print("POST OBITUARY")
            print(post_text)
            if not post_to_bluesky(post_text, image=image, image_alt=image_alt):
                failures.append(f"Obituary Bluesky post failed: {doi}")
                continue
            if not send_email(MAIL_PREFIX + post_text + MAIL_SUFFIX,
                              attachment=(image, content_type, f"dgd-obituary.{extension}")):
                failures.append(f"Obituary email failed for {doi}; Bluesky post was recorded")
            # post_to_x(post_text)
        else:
            authors = extract_authors(entry) or ""
            post_lines = ["New article in DGD.", shorten_title(title)]
            if authors:
                post_lines.append(authors)
            post_lines.append(doi_link(doi))
            post_text = "\n".join(post_lines)
            print("POST ARTICLE")
            post_text = normalize_text(trim_post(post_text))
            print(post_text)
            post_to_bluesky(post_text)
            send_email(MAIL_PREFIX + post_text + MAIL_SUFFIX)
            # post_to_x(post_text)
        print("-----")
        posted.append(doi)
    save_posted(posted)
    if failures:
        raise RuntimeError("; ".join(failures))

if __name__ == "__main__":
    main()

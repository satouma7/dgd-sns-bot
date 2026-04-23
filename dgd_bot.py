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

RSS_URL = "https://onlinelibrary.wiley.com/action/showFeed?type=etoc&feed=rss&jc=1440169x"
POSTED_FILE = "posted.json"
MAX_TITLE = 180
MAX_LEN = 300
DRY_RUN = False
bsky_client = None

def send_email(text):
    try:
        def to_ascii(s):
            return (s or "").encode('ascii', 'ignore').decode('ascii')
        from_addr = to_ascii(os.getenv("MAIL_FROM"))
        to_addr = to_ascii(os.getenv("MAIL_TO"))
        body_b64 = base64.b64encode(text.encode('utf-8')).decode('ascii')
        raw_msg = "\r\n".join([
            f"From: {from_addr}",
            f"To: {to_addr}",
            "Subject: DGD Bot Post",
            "MIME-Version: 1.0",
            "Content-Type: text/plain; charset=utf-8",
            "Content-Transfer-Encoding: base64",
            "",
            body_b64
        ])
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(os.getenv("MAIL_USER"), os.getenv("MAIL_PASS"))
            server.sendmail(from_addr, [to_addr], raw_msg.encode('ascii'))
    except Exception as e:
        print(f"Email sending failed: {repr(e)}")

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

def post_to_bluesky(text):
    global bsky_client
    if DRY_RUN:
        print(f"DRY RUN: Posting to Bluesky - \n\n{text}")
        return
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
        if facets:
            bsky_client.send_post(text=text, facets=facets)
        else:
            bsky_client.send_post(text=text)
    except Exception as e:
        print(f"Bluesky post failed: {repr(e)}")

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
    if hasattr(entry, "authors"):
        raw = entry.authors[0]["name"]
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

def main():
    load_dotenv()
    posted = load_posted()
    feed = feedparser.parse(RSS_URL)
    # print(feed)
    for entry in feed.entries:
        title = entry.title
        link = entry.link
        html = get_html(entry)
        doi = extract_doi(link)
        if doi in posted:
            continue

        # ---- Issue ----
        if title == "Issue Information":
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
                f"Cover: {cover_text}\n"
                f"{doi_link(doi)}"
            )
            email_text = (
                f"DGD Volume {volume}, Issue {issue} was released!!\n\n"
                f"Cover: {cover_text}\n"
                f"{doi_link(doi)}\n\n"
                f"--- Table of Contents ---\n\n"
                f"{toc_text}"
            )
            print("POST ISSUE")
            post_text = normalize_text(trim_post(post_text))
            print(post_text)
            post_to_bluesky(post_text)
            send_email(normalize_text(email_text))
            # post_to_x(post_text)
            # print("IMAGE:", cover_image)
            # print(cover_text)
            # print("FETCH URL:", clean_link(link))
            # print("HTML:")
            # print(html)
            # ---- Article ----
        else:
            authors = extract_authors(entry) or ""
            post_text = (
                "New article in DGD.\n"
                f"{shorten_title(title)}\n"
                f"{authors}\n"
                f"{doi_link(doi)}")
            print("POST ARTICLE")
            post_text = normalize_text(trim_post(post_text))
            print(post_text)
            post_to_bluesky(post_text)
            send_email(post_text)
            # post_to_x(post_text)
        print("-----")
        posted.append(doi)
    save_posted(posted)

if __name__ == "__main__":
    main()
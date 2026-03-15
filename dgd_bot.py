import feedparser
import json
import os
import re
import requests

RSS_URL = "https://onlinelibrary.wiley.com/action/showFeed?type=etoc&feed=rss&jc=1440169x"
POSTED_FILE = "posted.json"

def clean_link(link):
    return link.split("?")[0]

def fetch_cover_image_from_page(url):
    url = clean_link(url)
    r = requests.get(url)
    # ① og:image
    match = re.search(r'property="og:image"\s+content="([^"]+)"', r.text)
    if match:
        return match.group(1)
    # ② Wiley cover image
    match = re.search(r'name="citation_cover_image"\s+content="([^"]+)"', r.text)
    if match:
        return match.group(1)
    return None

def get_html(entry):
    if hasattr(entry, "content"):
        return entry.content[0].value
    return entry.summary

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
    match = re.search(r'Cover Photograph:\s*(.*)', html)
    if match:
        text = match.group(1)
        text = text.split("<")[0]
        return text.strip()
    return None

def extract_authors(entry):
    if hasattr(entry, "authors"):
        names = [a["name"] for a in entry.authors]
        return ", ".join(names)
    if hasattr(entry, "author"):
        return entry.author
    return ""

def main():
    posted = load_posted()
    feed = feedparser.parse(RSS_URL)
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

            # 他のエントリからVolume/Issue取得
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

            post_text = f"""
    DGD Volume {volume}, Issue {issue} was released!!

    Cover Photograph:
    {cover_text}
    {link}
    """
            print("POST ISSUE")
            print(post_text)
            print("IMAGE:", cover_image)
            # print(html)
            print("FETCH URL:", clean_link(link))
            # ---- Article ----
        else:
            authors = extract_authors(entry) or ""
            post_text = f"""New article in DGD
        {title}
        {authors}
        {link}
        """

            print("POST ARTICLE")
            print(post_text)
        print("-----")
        posted.append(doi)
    save_posted(posted)

if __name__ == "__main__":
    main()
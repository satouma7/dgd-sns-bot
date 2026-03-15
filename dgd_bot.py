import feedparser

RSS_URL = "https://onlinelibrary.wiley.com/action/showFeed?type=etoc&feed=rss&jc=1440169x"

def main():
    feed = feedparser.parse(RSS_URL)

    for entry in feed.entries:
        print("TITLE:", entry.title)
        print("LINK:", entry.link)
        print("-----")

if __name__ == "__main__":
    main()
from dotenv import load_dotenv
import os

load_dotenv()

print(os.getenv("BSKY_USERNAME"))
print(os.getenv("BSKY_PASSWORD"))
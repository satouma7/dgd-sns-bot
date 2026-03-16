from atproto import Client
client = Client()

client.login("username.bsky.social", "app-password")

client.send_post("test post from python")
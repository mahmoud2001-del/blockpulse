import feedparser
import requests
import time
import html
from datetime import datetime
from bs4 import BeautifulSoup
from flask import Flask
import threading

TELEGRAM_BOT_TOKEN = "7926832585:AAGvYcom3rHJxKGib52iZ7s7yI9RgA-61qQ"
TELEGRAM_CHANNEL = "@blockpulse_official"

RSS_FEEDS = [
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "https://cointelegraph.com/rss",
    "https://cryptoslate.com/feed/",
    "https://bitcoinmagazine.com/.rss/full/",
    "https://decrypt.co/feed",
    "https://www.theblock.co/feed",
    "https://news.bitcoin.com/feed/",
    "https://cryptobriefing.com/feed/",
    "https://beincrypto.com/feed/",
    "https://www.ccn.com/feed/",
    "https://www.coingape.com/feed/",
    "https://www.cryptoninjas.net/feed/",
    "https://www.newsbtc.com/feed/",
    "https://blockonomi.com/feed/",
    "https://www.cryptopotato.com/feed/",
]

KEYWORDS = [
    "acquisition", "investment", "etf", "partnership", "collaboration",
    "license", "regulation", "upgrade", "network", "development",
    "price increase", "price drop", "dominance", "bitcoin", "ethereum",
    "altcoin", "protocol", "launch", "decentralized", "staking", "bullish",
    "bearish", "fund", "token", "defi", "nft", "dao", "staking rewards",
    "market cap", "exchange listing"
]

EVENTS_RSS_URL = "https://coinmarketcal.com/en/rss/events"

sent_titles = set()
sent_images = set()
last_prices = {"bitcoin": None, "ethereum": None, "btc_dominance": None}


def clean_html(raw_html):
    soup = BeautifulSoup(raw_html, "html.parser")
    return soup.get_text(separator=' ', strip=True)


def simple_summarize(text, max_sentences=2):
    sentences = text.split('. ')
    summary = '. '.join(sentences[:max_sentences])
    if len(sentences) > max_sentences:
        summary += '...'
    return summary


def extract_image_url(entry):
    if 'media_content' in entry:
        for media in entry.media_content:
            if 'url' in media:
                return media['url']

    if 'enclosures' in entry:
        for enclosure in entry.enclosures:
            if ('image' in enclosure.type) or enclosure.href.endswith(('.jpg', '.png', '.jpeg')):
                return enclosure.href

    if 'summary' in entry:
        soup = BeautifulSoup(entry.summary, "html.parser")
        img_tag = soup.find("img")
        if img_tag and img_tag.get('src'):
            return img_tag['src']

    return None


def send_to_telegram(text_message, title, image_url=None):
    global sent_images
    text_message = html.escape(text_message)
    if image_url:
        if image_url in sent_images:
            print("⚠ Image URL already sent, skipping image.")
            image_url = None
        else:
            sent_images.add(image_url)

    if image_url:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
        payload = {
            "chat_id": TELEGRAM_CHANNEL,
            "photo": image_url,
            "caption": text_message[:1024],
            "parse_mode": "HTML"
        }
    else:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHANNEL,
            "text": text_message,
            "parse_mode": "HTML",
            "disable_web_page_preview": False
        }

    resp = requests.post(url, data=payload)
    print("✅ Sent:", title[:60], "status:", resp.status_code)
    if resp.status_code == 429:
        retry_after = int(resp.headers.get("Retry-After", 10))
        print(f"⚠ Rate limited. Retrying after {retry_after} seconds...")
        time.sleep(retry_after)
        requests.post(url, data=payload)


def fetch_and_send_news():
    for feed_url in RSS_FEEDS:
        feed = feedparser.parse(feed_url)
        for entry in feed.entries[:5]:
            title_lower = entry.title.lower()
            if any(keyword in title_lower for keyword in KEYWORDS):
                if entry.title not in sent_titles:
                    summary = ""
                    if 'summary' in entry:
                        summary = simple_summarize(clean_html(entry.summary))
                    message = f"📰 {entry.title}\n{summary}\n{entry.link}"
                    image_url = extract_image_url(entry)
                    send_to_telegram(message, entry.title, image_url)
                    sent_titles.add(entry.title)
        time.sleep(4)


def fetch_and_check_prices():
    global last_prices
    try:
        url = "https://api.coingecko.com/api/v3/global"
        data = requests.get(url).json()
        prices = requests.get(
            "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum&vs_currencies=usd"
        ).json()

        btc_price = prices["bitcoin"]["usd"]
        eth_price = prices["ethereum"]["usd"]
        btc_dominance = data["data"]["market_cap_percentage"]["btc"]

        messages = []

        if last_prices["bitcoin"] is None:
            last_prices["bitcoin"] = btc_price
        else:
            change = (btc_price - last_prices["bitcoin"]) / last_prices["bitcoin"] * 100
            if abs(change) >= 5:
                messages.append(f"🚨 Bitcoin price changed by {change:.2f}%: ${btc_price}")
            last_prices["bitcoin"] = btc_price

        if last_prices["ethereum"] is None:
            last_prices["ethereum"] = eth_price
        else:
            change = (eth_price - last_prices["ethereum"]) / last_prices["ethereum"] * 100
            if abs(change) >= 5:
                messages.append(f"🚨 Ethereum price changed by {change:.2f}%: ${eth_price}")
            last_prices["ethereum"] = eth_price

        if last_prices["btc_dominance"] is None:
            last_prices["btc_dominance"] = btc_dominance
        else:
            change = btc_dominance - last_prices["btc_dominance"]
            if abs(change) >= 2:
                messages.append(f"📊 Bitcoin Dominance changed by {change:.2f}%: {btc_dominance:.2f}%")
            last_prices["btc_dominance"] = btc_dominance

        for msg in messages:
            send_to_telegram(msg, "Price Alert")

    except Exception as e:
        print("❌ Error fetching prices:", e)


def fetch_and_send_events_rss():
    feed = feedparser.parse(EVENTS_RSS_URL)
    entries = feed.entries[:5]
    if not entries:
        print("No events found in RSS.")
        return
    msg = "🗓 Upcoming Crypto Events (RSS):\n"
    for entry in entries:
        title = entry.title
        published = entry.get("published", "N/A")
        link = entry.link
        msg += f"\n• {title}\n  Date: {published}\n  {link}\n"
    send_to_telegram(msg, "Crypto Events (RSS)")


def main():
    while True:
        print(f"{datetime.now()} 🔄 Fetching news, prices, and events...")
        fetch_and_send_news()
        fetch_and_check_prices()
        fetch_and_send_events_rss()
        print("⏳ Sleeping for 20 minutes...")
        time.sleep(60 * 20)


# 🔥 Web server for UptimeRobot
app = Flask(__name__)

@app.route("/")
def home():
    return "✅ BlockPulse Bot is running with Flask and threading!"

def run_web_server():
    app.run(host="0.0.0.0", port=8080)


# ✅ تشغيل كل شيء داخل Threads
if __name__ == "__main__":
    threading.Thread(target=run_web_server).start()
    threading.Thread(target=main).start()
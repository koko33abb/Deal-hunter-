import os
import re
import requests
import google.generativeai as genai
from bs4 import BeautifulSoup

# ============ الإعدادات ============
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
MIN_PROFIT_THRESHOLD = 200  # الحد الأدنى للربح الصافي المقبول لكل صفقة

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-2.5-flash")

# ============ دالة إرسال تنبيه Telegram ============
def send_telegram_alert(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
    try:
        resp = requests.get(url, timeout=10).json()
        chat_id = None
        if resp.get("result"):
            chat_id = resp["result"][-1]["message"]["chat"]["id"]
        if not chat_id:
            print("لم يتم العثور على chat_id بعد - أرسل أي رسالة للبوت أولاً على تيليجرام")
            return
        send_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        requests.post(send_url, data={"chat_id": chat_id, "text": message}, timeout=10)
        print("تم إرسال التنبيه بنجاح")
    except Exception as e:
        print(f"خطأ في إرسال تيليجرام: {e}")

# ============ دالة تحليل صورة عبر Gemini ============
def analyze_image_with_gemini(image_url, listing_title):
    try:
        img_data = requests.get(image_url, timeout=10).content
        prompt = f"""
        هذا إعلان بعنوان: "{listing_title}"
        افحص هذه الصورة بدقة وحدد: هل يوجد بها أي قطعة كمبيوتر واضحة (مثل SSD, GPU, RAM, CPU)
        لم يُذكر اسمها في العنوان؟ إذا وُجدت، اذكر اسمها المحتمل باختصار.
        إذا لم تجد شيئاً، اكتب: لا يوجد.
        """
        response = model.generate_content(
            [prompt, {"mime_type": "image/jpeg", "data": img_data}]
        )
        return response.text.strip()
    except Exception as e:
        print(f"خطأ في تحليل الصورة: {e}")
        return "لا يوجد"

# ============ دالة تقدير القيمة السوقية (مبسّطة - تُطوَّر لاحقاً) ============
def estimate_market_value(component_name):
    price_table = {
        "ssd": 60,
        "rtx 3070": 280,
        "rtx 3060": 200,
        "gtx 1660": 130,
        "ram": 40,
        "cpu": 100,
    }
    component_name = component_name.lower()
    for key, value in price_table.items():
        if key in component_name:
            return value
    return 0

# ============ دالة البحث الرئيسية (Craigslist كمثال أولي) ============
def search_listings(query, city="losangeles"):
    url = f"https://{city}.craigslist.org/search/sss?query={query}"
    listings = []
    try:
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        soup = BeautifulSoup(resp.text, "html.parser")
        items = soup.select("li.cl-search-result")[:10]
        for item in items:
            title_tag = item.select_one("a.cl-app-anchor")
            price_tag = item.select_one("span.priceinfo")
            if not title_tag or not price_tag:
                continue
            title = title_tag.get_text(strip=True)
            link = title_tag.get("href")
            price_text = re.sub(r"[^\d]", "", price_tag.get_text())
            price = int(price_text) if price_text else 0
            img_tag = item.select_one("img")
            image_url = img_tag.get("src") if img_tag else None
            listings.append({
                "title": title,
                "price": price,
                "link": link,
                "image": image_url
            })
    except Exception as e:
        print(f"خطأ في البحث: {e}")
    return listings

# ============ منطق القرار الرئيسي ============
def process_listing(listing):
    title = listing["title"]
    price = listing["price"]
    image_url = listing.get("image")

    detected_component = "لا يوجد"
    if image_url:
        detected_component = analyze_image_with_gemini(image_url, title)

    if "لا يوجد" in detected_component:
        return

    market_value = estimate_market_value(detected_component)
    if market_value == 0:
        return

    estimated_profit = market_value - price

    if estimated_profit >= MIN_PROFIT_THRESHOLD:
        message = (
            f"🔥 صفقة محتملة!\n"
            f"📦 العنوان: {title}\n"
            f"🔎 مكوّن مكتشف: {detected_component}\n"
            f"💰 سعر الإعلان: {price}$\n"
            f"📊 القيمة السوقية التقديرية: {market_value}$\n"
            f"✅ الربح الصافي المتوقع: {estimated_profit}$\n"
            f"🔗 {listing['link']}"
        )
        send_telegram_alert(message)
        print("تم العثور على صفقة وإرسال تنبيه")

# ============ نقطة البداية ============
def main():
    search_terms = ["gaming pc", "computer parts", "gpu"]
    for term in search_terms:
        listings = search_listings(term)
        for listing in listings:
            process_listing(listing)

if __name__ == "__main__":
    main()

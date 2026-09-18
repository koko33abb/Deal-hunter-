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

# ============ جلب chat_id ============
def get_chat_id():
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
    try:
        resp = requests.get(url, timeout=10).json()
        if resp.get("result"):
            return resp["result"][-1]["message"]["chat"]["id"]
    except Exception as e:
        print(f"خطأ في جلب chat_id: {e}")
    return None

# ============ إرسال صورة مع تعليق إلى Telegram ============
def send_telegram_photo(image_url, caption):
    chat_id = get_chat_id()
    if not chat_id:
        print("لم يتم العثور على chat_id - تأكد من إرسال رسالة للبوت أولاً")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    try:
        resp = requests.post(url, data={
            "chat_id": chat_id,
            "photo": image_url,
            "caption": caption
        }, timeout=15)
        print(f"نتيجة إرسال الصورة إلى Telegram: {resp.status_code}")
        print(f"محتوى الرد: {resp.text[:300]}")
    except Exception as e:
        print(f"خطأ في إرسال الصورة: {e}")

# ============ تحليل صورة تفصيلي (تقرير كامل) ============
def analyze_image_full_report(image_url, listing_title):
    print("--- بدء تحليل الصورة ---")
    print(f"رابط الصورة المُرسل إلى Gemini: {image_url}")
    try:
        img_data = requests.get(image_url, timeout=10).content
        print(f"تم تحميل الصورة بنجاح - الحجم بالبايت: {len(img_data)}")

        prompt = f"""
أنت خبير تقييم قطع كمبيوتر مستعملة من الصور.
عنوان الإعلان: "{listing_title}"

افحص الصورة بدقة، وأجب بهذا التنسيق بالضبط (سطر واحد لكل بند، بدون أي شرح إضافي):

القطعة_المكتشفة: <اسم القطعة أو "لا يوجد">
الموديل_المحتمل: <رقم/اسم الموديل أو "غير واضح">
الحالة: <ممتازة / جيدة / متوسطة / تالفة / غير معروفة>
علامات_التلف: <وصف مختصر أو "لا يوجد">
درجة_الثقة: <رقم من 0 إلى 100>
"""
        print("جاري إرسال الصورة والطلب إلى Gemini API...")
        response = model.generate_content(
            [prompt, {"mime_type": "image/jpeg", "data": img_data}]
        )
        raw_text = response.text.strip()
        print("--- الرد الخام الكامل من Gemini ---")
        print(raw_text)
        print("--- نهاية الرد ---")
        return raw_text
    except Exception as e:
        print(f"خطأ أثناء تحليل الصورة: {e}")
        return None

# ============ وضع الاختبار: إعلان واحد حقيقي فقط ============
def run_vision_test():
    print("=== بدء اختبار نظام الرؤية على إعلان واحد حقيقي ===")
    listings = search_listings("computer parts")
    print(f"عدد الإعلانات التي تم جلبها من الموقع: {len(listings)}")

    test_listing = None
    for listing in listings:
        if listing.get("image"):
            test_listing = listing
            break

    if not test_listing:
        print("لم يتم العثور على أي إعلان بصورة صالحة للاختبار")
        send_telegram_alert("⚠️ اختبار الرؤية: لم يتم العثور على إعلان بصورة للاختبار")
        return

    print(f"الإعلان المختار: {test_listing['title']}")
    print(f"السعر المعروض: {test_listing['price']}$")
    print(f"رابط الإعلان: {test_listing['link']}")

    analysis = analyze_image_full_report(test_listing["image"], test_listing["title"])

    if not analysis:
        send_telegram_alert("⚠️ فشل اختبار الرؤية - راجع الـ Logs في GitHub Actions لمعرفة السبب")
        return

    caption = (
        f"🧪 اختبار نظام الرؤية\n\n"
        f"📦 العنوان: {test_listing['title']}\n"
        f"💰 السعر: {test_listing['price']}$\n\n"
        f"{analysis}\n\n"
        f"🔗 {test_listing['link']}"
    )
    send_telegram_photo(test_listing["image"], caption)
    print("=== انتهى الاختبار - تحقق من Telegram الآن ===")
    if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        run_vision_test()
    else:
        main()

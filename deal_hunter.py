# -*- coding: utf-8 -*-
"""
Deal Hunter - النسخة الكاملة المرتبة

طريقة التشغيل:
    python deal_hunter.py          -> التشغيل العادي (البحث عن صفقات)
    python deal_hunter.py test     -> وضع الاختبار (تحليل صورة + إرسالها لتيليجرام)

المتغيرات السرية المطلوبة (GitHub Secrets):
    TELEGRAM_BOT_TOKEN
    GEMINI_API_KEY
"""

import os
import re
import sys
import warnings

import requests
from bs4 import BeautifulSoup

warnings.filterwarnings("ignore")
import google.generativeai as genai  # noqa: E402


# ============================================================
# الإعدادات
# ============================================================

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()

CRAIGSLIST_CITY = "losangeles"
SEARCH_TERMS = ["gaming pc", "computer parts", "gpu"]

MIN_PROFIT = 200            # الحد الأدنى للربح الصافي بالدولار
SELLING_FEE_RATE = 0.13     # نسبة عمولة البيع التقديرية
SHIPPING_COST = 25          # تكلفة شحن تقديرية بالدولار
MAX_ITEMS_PER_SEARCH = 40   # أقصى عدد إعلانات يُفحص لكل كلمة بحث
MAX_ALERTS_PER_RUN = 5      # أقصى عدد تنبيهات في التشغيل الواحد

# النماذج تُجرَّب بالترتيب حتى ينجح أحدها (ثم تُكتشف نماذج أخرى تلقائياً)
GEMINI_MODELS = ["gemini-3.6-flash"]

# كلمات بحث وضع الاختبار: نبحث عن كروت شاشة حقيقية بدل الكابلات والإكسسوارات
TEST_SEARCH_TERMS = ["rtx 3070", "rtx 3080", "rtx 4070", "rtx 3060"]

# أسباب فشل Gemini تُحفظ هنا ليُرسَل ملخصها لتيليجرام
GEMINI_ERRORS = []

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# جدول أسعار السوق التقريبية (بالدولار) - يمكن تعديله يدوياً لاحقاً
PRICE_TABLE = {
    "rtx4090": 1500,
    "rtx4080super": 950,
    "rtx4080": 900,
    "rtx4070tisuper": 750,
    "rtx4070ti": 650,
    "rtx4070super": 550,
    "rtx4070": 480,
    "rtx4060ti": 350,
    "rtx4060": 270,
    "rtx3090ti": 750,
    "rtx3090": 650,
    "rtx3080ti": 450,
    "rtx3080": 380,
    "rtx3070ti": 280,
    "rtx3070": 240,
    "rtx3060ti": 200,
    "rtx3060": 160,
    "rx7900xtx": 800,
    "rx7900xt": 650,
    "rx6800xt": 300,
    "rx6700xt": 200,
    "ps5": 400,
}


# ============================================================
# تيليجرام
# ============================================================

def get_chat_id():
    """يجلب رقم المحادثة. يتطلب أن يكون المستخدم قد أرسل /start للبوت."""
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if chat_id:
        return chat_id

    url = "https://api.telegram.org/bot" + TELEGRAM_BOT_TOKEN + "/getUpdates"
    try:
        response = requests.get(url, timeout=30)
        data = response.json()
    except Exception as error:
        print("خطأ أثناء الاتصال بتيليجرام (getUpdates):", error)
        return None

    if not data.get("ok"):
        print("رد تيليجرام غير ناجح:", data)
        return None

    for update in reversed(data.get("result", [])):
        message = update.get("message") or update.get("edited_message") or {}
        chat = message.get("chat") or {}
        if chat.get("id"):
            return str(chat["id"])

    print("لا توجد رسائل للبوت. أرسل /start للبوت في تيليجرام ثم أعد التشغيل.")
    return None


def send_telegram_alert(text):
    """يرسل رسالة نصية عادية."""
    chat_id = get_chat_id()
    if not chat_id:
        return False

    url = "https://api.telegram.org/bot" + TELEGRAM_BOT_TOKEN + "/sendMessage"
    success = True
    for start in range(0, len(text), 3900):
        part = text[start:start + 3900]
        try:
            response = requests.post(
                url,
                data={"chat_id": chat_id, "text": part},
                timeout=30,
            )
            print("إرسال رسالة نصية:", response.status_code)
            if not response.ok:
                print(response.text)
                success = False
        except Exception as error:
            print("خطأ في إرسال الرسالة:", error)
            success = False
    return success


def send_telegram_photo(image_url, caption):
    """يحمّل الصورة ثم يرسلها لتيليجرام مع وصف."""
    chat_id = get_chat_id()
    if not chat_id:
        return False

    try:
        image_response = requests.get(image_url, headers=HEADERS, timeout=30)
        image_response.raise_for_status()

        url = "https://api.telegram.org/bot" + TELEGRAM_BOT_TOKEN + "/sendPhoto"
        response = requests.post(
            url,
            data={"chat_id": chat_id, "caption": caption[:1000]},
            files={"photo": ("photo.jpg", image_response.content)},
            timeout=60,
        )
        print("إرسال صورة:", response.status_code)
        if not response.ok:
            print(response.text)
        return response.ok
    except Exception as error:
        print("خطأ في إرسال الصورة:", error)
        return False


# ============================================================
# تحليل الصور (Gemini Vision)
# ============================================================

def record_gemini_error(message):
    """يحفظ سبب الفشل بعد إخفاء مفتاح Gemini إن ظهر فيه."""
    text = str(message)
    if GEMINI_API_KEY:
        text = text.replace(GEMINI_API_KEY, "***")
    text = text.replace("\n", " ")[:300]
    print("سبب الفشل:", text)
    GEMINI_ERRORS.append(text)


def discover_gemini_models():
    """يسأل Gemini عن النماذج المتاحة لهذا المفتاح، ويعيد أسماء نماذج flash."""
    names = []
    try:
        for model in genai.list_models():
            methods = model.supported_generation_methods or []
            name = model.name.replace("models/", "")
            if "generateContent" not in methods or "flash" not in name:
                continue
            if any(word in name for word in ["image", "tts", "live", "audio"]):
                continue
            names.append(name)
    except Exception as error:
        record_gemini_error("تعذر جلب قائمة النماذج: " + str(error))
    return names[:5]


def analyze_image_full_report(image_url):
    """يحلل صورة الإعلان ويعيد تقريراً منظماً، أو None عند الفشل."""
    if not GEMINI_API_KEY:
        record_gemini_error("مفتاح GEMINI_API_KEY غير موجود في GitHub Secrets")
        return None

    try:
        image_response = requests.get(image_url, headers=HEADERS, timeout=30)
        image_response.raise_for_status()
    except Exception as error:
        record_gemini_error("تعذر تحميل الصورة للتحليل: " + str(error))
        return None

    mime_type = image_response.headers.get("Content-Type", "image/jpeg")
    mime_type = mime_type.split(";")[0].strip()
    if not mime_type.startswith("image/"):
        mime_type = "image/jpeg"

    prompt = (
        "أنت خبير في قطع الحاسوب وأجهزة الألعاب المستعملة. حلّل هذه الصورة "
        "من إعلان بيع، وأعطني تقريراً قصيراً بالعربية بهذا الشكل بالضبط:\n"
        "القطعة: (نوع القطعة أو الجهاز)\n"
        "الموديل: (الموديل إن ظهر، وإلا اكتب غير واضح)\n"
        "الحالة: (جيدة / متوسطة / سيئة / غير واضح)\n"
        "علامات التلف: (أي تلف أو غبار أو صدأ ظاهر، وإلا اكتب لا يوجد)\n"
        "درجة الثقة: (رقم من 0 إلى 100)\n"
        "لا تخمّن موديلاً لا يظهر في الصورة بوضوح."
    )

    genai.configure(api_key=GEMINI_API_KEY)
    model_names = list(GEMINI_MODELS)
    tried_first_round = False
    while True:
        for model_name in model_names:
            result = try_gemini_model(model_name, prompt, mime_type, image_response.content)
            if result:
                return result
        if tried_first_round:
            return None
        tried_first_round = True
        extra = [name for name in discover_gemini_models() if name not in model_names]
        print("نماذج إضافية مكتشفة:", extra)
        if not extra:
            return None
        model_names = extra


def try_gemini_model(model_name, prompt, mime_type, image_bytes):
    """يجرب نموذجاً واحداً ويعيد النص أو None."""
    try:
        model = genai.GenerativeModel(model_name)
        response = model.generate_content(
            [prompt, {"mime_type": mime_type, "data": image_bytes}]
        )
        text = (response.text or "").strip()
        if text:
            print("نجح تحليل الصورة بالنموذج:", model_name)
            return text
        record_gemini_error(model_name + ": رد فارغ")
    except Exception as error:
        record_gemini_error(model_name + ": " + str(error))
    return None


# ============================================================
# البحث في Craigslist
# ============================================================

def parse_price(price_text):
    """يحوّل نص مثل $1,200 إلى رقم صحيح."""
    digits = re.sub(r"[^\d]", "", price_text or "")
    if not digits:
        return None
    return int(digits)


def search_listings(term):
    """يبحث في Craigslist ويعيد قائمة إعلانات (عنوان، سعر، رابط)."""
    url = "https://" + CRAIGSLIST_CITY + ".craigslist.org/search/sss"
    try:
        response = requests.get(
            url,
            params={"query": term, "sort": "date"},
            headers=HEADERS,
            timeout=30,
        )
    except Exception as error:
        print("خطأ في البحث عن", term, ":", error)
        return []

    print("البحث عن", term, "-> رمز الرد:", response.status_code)
    if not response.ok:
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    results = []
    for item in soup.select("li.cl-static-search-result")[:MAX_ITEMS_PER_SEARCH]:
        link_tag = item.find("a")
        title_tag = item.select_one(".title")
        price_tag = item.select_one(".price")
        if not link_tag or not link_tag.get("href"):
            continue

        title = title_tag.get_text(strip=True) if title_tag else "بدون عنوان"
        price = parse_price(price_tag.get_text(strip=True)) if price_tag else None
        results.append(
            {"title": title, "price": price, "link": link_tag["href"]}
        )

    print("عدد الإعلانات:", len(results))
    return results


def get_listing_image(link):
    """يفتح صفحة الإعلان ويعيد رابط أول صورة، أو None."""
    try:
        response = requests.get(link, headers=HEADERS, timeout=30)
    except Exception as error:
        print("تعذر فتح الإعلان:", error)
        return None

    if not response.ok:
        return None

    soup = BeautifulSoup(response.text, "html.parser")

    meta = soup.find("meta", attrs={"property": "og:image"})
    if meta and meta.get("content"):
        return meta["content"]

    for image in soup.find_all("img"):
        source = image.get("src", "")
        if "images.craigslist.org" in source:
            return source

    return None


# ============================================================
# تقييم الصفقات
# ============================================================

def estimate_market_value(title):
    """يبحث في العنوان عن قطعة معروفة ويعيد (الاسم، القيمة)."""
    compact = re.sub(r"[\s\-]+", "", title.lower())
    for key in sorted(PRICE_TABLE, key=len, reverse=True):
        if key in compact:
            return key, PRICE_TABLE[key]
    return None, 0


def evaluate_listing(listing):
    """يحسب الربح الصافي التقديري. يعيد None إن لم تُعرف القطعة."""
    price = listing["price"]
    if not price or price <= 0:
        return None

    key, market_value = estimate_market_value(listing["title"])
    if not key:
        return None

    net_revenue = market_value * (1 - SELLING_FEE_RATE)
    profit = net_revenue - price - SHIPPING_COST
    return {"part": key, "market_value": market_value, "profit": round(profit)}


# ============================================================
# التشغيل العادي
# ============================================================

def main():
    print("=== بدء التشغيل العادي ===")
    seen_links = set()
    alerts_sent = 0

    for term in SEARCH_TERMS:
        for listing in search_listings(term):
            if listing["link"] in seen_links:
                continue
            seen_links.add(listing["link"])

            evaluation = evaluate_listing(listing)
            if not evaluation or evaluation["profit"] < MIN_PROFIT:
                continue

            print("صفقة محتملة:", listing["title"], listing["price"])
            image_url = get_listing_image(listing["link"])
            report = analyze_image_full_report(image_url) if image_url else None

            message = (
                "صفقة محتملة\n\n"
                "العنوان: " + listing["title"] + "\n"
                "السعر المطلوب: " + str(listing["price"]) + "$\n"
                "القطعة المكتشفة: " + evaluation["part"] + "\n"
                "القيمة السوقية التقديرية: " + str(evaluation["market_value"]) + "$\n"
                "الربح الصافي التقديري: " + str(evaluation["profit"]) + "$\n"
            )
            if report:
                message += "\nتحليل الصورة:\n" + report + "\n"
            message += "\n" + listing["link"]

            if image_url:
                sent = send_telegram_photo(image_url, message)
                if not sent:
                    send_telegram_alert(message)
            else:
                send_telegram_alert(message)

            alerts_sent += 1
            if alerts_sent >= MAX_ALERTS_PER_RUN:
                print("تم بلوغ الحد الأقصى للتنبيهات.")
                return

    print("=== انتهى التشغيل العادي. عدد التنبيهات:", alerts_sent, "===")


# ============================================================
# وضع الاختبار
# ============================================================

def find_test_listing():
    """يختار إعلاناً للاختبار: يفضّل كرت شاشة معروفاً، ثم أي إعلان بصورة."""
    # الجولة الأولى: إعلانات يعرفها جدول الأسعار (كروت شاشة)
    for term in TEST_SEARCH_TERMS:
        for listing in search_listings(term)[:15]:
            key, _ = estimate_market_value(listing["title"])
            if not key:
                continue
            image_url = get_listing_image(listing["link"])
            if image_url:
                return listing, image_url

    # الجولة الثانية: أي إعلان له صورة
    for term in SEARCH_TERMS:
        for listing in search_listings(term)[:15]:
            image_url = get_listing_image(listing["link"])
            if image_url:
                return listing, image_url

    return None, None


def run_vision_test():
    print("=== بدء اختبار الرؤية ===")

    if not send_telegram_alert("بدأ اختبار الرؤية. جاري البحث عن إعلان بصورة..."):
        print("فشل الإرسال لتيليجرام. تأكد من إرسال /start للبوت ثم أعد التشغيل.")
        return

    test_listing, test_image = find_test_listing()

    if not test_listing:
        print("لم يُعثر على إعلان بصورة.")
        send_telegram_alert("فشل الاختبار: لم يُعثر على أي إعلان بصورة.")
        return

    print("الإعلان المختار:", test_listing["title"])
    print("رابط الصورة:", test_image)

    analysis = analyze_image_full_report(test_image)
    if not analysis:
        reasons = "\n".join(GEMINI_ERRORS[-4:]) or "سبب غير معروف"
        send_telegram_alert("فشل تحليل الصورة عبر Gemini.\n\nالأسباب:\n" + reasons)
        return

    caption = (
        "اختبار نظام الرؤية\n\n"
        "العنوان: " + test_listing["title"] + "\n"
        "السعر: " + str(test_listing["price"]) + "$\n\n"
        + analysis + "\n\n"
        + test_listing["link"]
    )

    if not send_telegram_photo(test_image, caption):
        send_telegram_alert(caption)

    print("=== انتهى الاختبار. تحقق من تيليجرام الآن ===")


# ============================================================
# نقطة البداية
# ============================================================

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        run_vision_test()
    else:
        main()

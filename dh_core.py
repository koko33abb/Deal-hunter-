# -*- coding: utf-8 -*-
"""
dh_core.py - الجزء الأول من Deal Hunter:
الإعدادات، وإرسال تيليجرام، وتحليل الصور عبر Gemini.
هذا الملف يُستورد من deal_hunter.py ولا يُشغَّل وحده.
"""

import json
import os
import re
import warnings

import requests

warnings.filterwarnings("ignore")
import google.generativeai as genai  # noqa: E402


# ============================================================
# الإعدادات
# ============================================================

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()

# رقم محادثتك مع البوت (ليس سراً: لا يُستخدم دون توكن البوت)
DEFAULT_TELEGRAM_CHAT_ID = "8035757986"

CRAIGSLIST_CITY = "losangeles"
SEARCH_TERMS = ["gaming pc", "computer parts", "gpu"]

MIN_PROFIT = 200            # الحد الأدنى للربح بالدولار (القيمة ناقص سعر الشراء)
SELLING_FEE_RATE = 0.0      # نسبة عمولة البيع (0 = بيع مباشر بلا عمولة)
SHIPPING_COST = 0           # تكلفة شحن بالدولار (0 = استلام شخصي)
MAX_ITEMS_PER_SEARCH = 40   # أقصى عدد إعلانات يُفحص لكل كلمة بحث
MAX_ALERTS_PER_RUN = 5      # أقصى عدد تنبيهات في التشغيل الواحد
SEEN_FILE = "seen_deals.json"   # ملف يحفظ الصفقات التي أُرسلت سابقاً
MAX_SEEN = 500                  # أقصى عدد روابط محفوظة في الذاكرة
COMPS_MIN_SAMPLES = 5           # أقل عدد إعلانات مماثلة لاعتماد القيمة السوقية
MIN_VISION_CONFIDENCE = 70      # أقل ثقة في تعرّف الصورة لإصدار قرار شراء

# النماذج تُجرَّب بالترتيب حتى ينجح أحدها (ثم تُكتشف نماذج أخرى تلقائياً)
GEMINI_MODELS = ["gemini-3.6-flash"]

# كلمات بحث وضع الاختبار: نبحث عن كروت شاشة حقيقية بدل الكابلات والإكسسوارات
TEST_SEARCH_TERMS = ["rtx 3070", "rtx 3080", "rtx 4070", "rtx 3060"]

# كلمات بحث الاختبار الثاني: ملحقات تحمل اسم منتج معروف (مثل سماعة PS5)
TEST_ACCESSORY_TERMS = ["ps5 headset", "ps5 controller", "ps5 charging station"]

# أسباب فشل Gemini تُحفظ هنا ليُرسَل ملخصها لتيليجرام
GEMINI_ERRORS = []

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# الأصناف المعروفة: المفتاح -> (كلمة البحث عن إعلانات مماثلة، الصنف المتوقع من الصورة)
# لا توجد هنا أي أسعار: القيمة السوقية تُحسب من إعلانات مماثلة حقيقية فقط
KNOWN_PARTS = {
    "rtx4090": ("rtx 4090", "graphics_card"),
    "rtx4080super": ("rtx 4080 super", "graphics_card"),
    "rtx4080": ("rtx 4080", "graphics_card"),
    "rtx4070tisuper": ("rtx 4070 ti super", "graphics_card"),
    "rtx4070ti": ("rtx 4070 ti", "graphics_card"),
    "rtx4070super": ("rtx 4070 super", "graphics_card"),
    "rtx4070": ("rtx 4070", "graphics_card"),
    "rtx4060ti": ("rtx 4060 ti", "graphics_card"),
    "rtx4060": ("rtx 4060", "graphics_card"),
    "rtx3090ti": ("rtx 3090 ti", "graphics_card"),
    "rtx3090": ("rtx 3090", "graphics_card"),
    "rtx3080ti": ("rtx 3080 ti", "graphics_card"),
    "rtx3080": ("rtx 3080", "graphics_card"),
    "rtx3070ti": ("rtx 3070 ti", "graphics_card"),
    "rtx3070": ("rtx 3070", "graphics_card"),
    "rtx3060ti": ("rtx 3060 ti", "graphics_card"),
    "rtx3060": ("rtx 3060", "graphics_card"),
    "rx7900xtx": ("rx 7900 xtx", "graphics_card"),
    "rx7900xt": ("rx 7900 xt", "graphics_card"),
    "rx6800xt": ("rx 6800 xt", "graphics_card"),
    "rx6700xt": ("rx 6700 xt", "graphics_card"),
    "ps5": ("ps5 console", "console"),
}

# الأصناف التي يُسمح لـ Gemini بإرجاعها، مع أسمائها بالعربية
VISION_CATEGORIES = {
    "graphics_card": "كرت شاشة",
    "console": "جهاز ألعاب",
    "headset": "سماعة",
    "controller": "يد تحكم",
    "keyboard": "لوحة مفاتيح",
    "mouse": "فأرة",
    "monitor": "شاشة",
    "cable": "كابل",
    "pc_case": "صندوق حاسوب",
    "motherboard": "لوحة أم",
    "cpu": "معالج",
    "ram": "ذاكرة عشوائية",
    "ssd": "قرص تخزين",
    "laptop": "حاسوب محمول",
    "desktop_pc": "حاسوب مكتبي كامل",
    "phone": "هاتف",
    "other": "أخرى",
}

# كلمات في العنوان تدل على ملحق وليس القطعة نفسها
ACCESSORY_WORDS = [
    "headset", "headphone", "earbud", "earphone", "controller", "gamepad",
    "joystick", "charger", "charging", "stand", "case", "cover", "skin",
    "cable", "adapter", "dock", "bracket", "riser", "backplate",
    "waterblock", "water block", "box only", "empty box", "keyboard",
    "mouse", "monitor",
]

# كلمات تدل على تلف أو عطل أو عدم فحص
BROKEN_WORDS = [
    "for parts", "parts only", "broken", "not working", "doesn't work",
    "doesnt work", "does not work", "damaged", "dead", "no display",
    "artifact", "artifacts", "faulty", "defective", "repair", "untested",
]

# كلمات تدل على جهاز كامل أو حزمة (لا تصلح للمقارنة بالقطعة المنفردة)
BUNDLE_WORDS = [
    "desktop", "laptop", "computer", "prebuilt", "pre built", "tower",
    "gaming pc", "custom pc", "pc build", "rig", "bundle", "combo", "lot",
]

# قرارات النظام
DECISION_BUY = "شراء محتمل"
DECISION_REVIEW = "مراجعة يدوية"
DECISION_UNKNOWN = "لا قرار (القيمة السوقية غير معروفة)"
DECISION_SKIP = "تجاهل (الربح أقل من الحد)"


# ============================================================
# تيليجرام
# ============================================================

def get_chat_id():
    """يجلب رقم المحادثة. يتطلب أن يكون المستخدم قد أرسل /start للبوت."""
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip() or DEFAULT_TELEGRAM_CHAT_ID
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
        "أنت خبير في تعريف قطع الحاسوب وأجهزة الألعاب المستعملة من الصور. "
        "انظر إلى الصورة فقط، ولا تخمّن ما لا يظهر فيها. "
        "أعد JSON فقط بلا أي نص قبله أو بعده وبلا علامات تنسيق أو backticks، بالمفاتيح التالية بالضبط:\n"
        "{\n"
        '  "category": "واحدة فقط من: ' + ", ".join(VISION_CATEGORIES) + '",\n'
        '  "brand": "العلامة التجارية كما تظهر في الصورة، وإلا: غير واضح",\n'
        '  "model": "الموديل كما يظهر مكتوباً على المنتج أو علبته، وإلا: غير واضح",\n'
        '  "condition": "جيدة أو متوسطة أو سيئة أو غير واضح",\n'
        '  "damage": "وصف أي تلف ظاهر، وإلا: لا يوجد",\n'
        '  "confidence": "رقم من 0 إلى 100 يعبّر عن ثقتك في الصنف والموديل معاً"\n'
        "}\n"
        "القاعدة الأهم: الصنف هو ما تراه فعلاً في الصورة. "
        "السماعة تبقى headset حتى لو كُتب على علبتها أنها تناسب جهاز ألعاب، "
        "ولا تكتب console إلا إذا ظهر جهاز الألعاب نفسه. "
        "لا تكتب موديلاً إلا إذا كان مكتوباً أو واضحاً في الصورة."
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


def parse_vision_json(text):
    """يحوّل رد Gemini إلى قاموس نظيف، أو None إن لم يكن JSON صالحاً."""
    if not text:
        return None
    cleaned = re.sub(r"`{3}(?:json)?", "", text).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(cleaned[start:end + 1])
    except Exception:
        return None
    if not isinstance(data, dict):
        return None

    category = str(data.get("category", "other")).strip().lower()
    if category not in VISION_CATEGORIES:
        category = "other"
    try:
        confidence = int(float(data.get("confidence", 0)))
    except (TypeError, ValueError):
        confidence = 0

    return {
        "category": category,
        "brand": str(data.get("brand", "غير واضح")).strip()[:60] or "غير واضح",
        "model": str(data.get("model", "غير واضح")).strip()[:60] or "غير واضح",
        "condition": str(data.get("condition", "غير واضح")).strip()[:40] or "غير واضح",
        "damage": str(data.get("damage", "غير واضح")).strip()[:120] or "غير واضح",
        "confidence": max(0, min(100, confidence)),
    }


def analyze_image_structured(image_url):
    """يحلل الصورة ويعيد قاموساً منظماً (الصنف والموديل والحالة...) أو None."""
    text = analyze_image_full_report(image_url)
    if not text:
        return None
    data = parse_vision_json(text)
    if data is None:
        record_gemini_error("تعذر قراءة رد Gemini كـ JSON: " + text[:120])
    return data

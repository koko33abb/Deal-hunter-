# -*- coding: utf-8 -*-
"""
Deal Hunter - الملف الرئيسي

طريقة التشغيل:
    python deal_hunter.py          -> التشغيل العادي (البحث عن صفقات)
    python deal_hunter.py test     -> وضع الاختبار (اختباران على إعلانات حقيقية)

يعتمد على الملف dh_core.py (الإعدادات وتيليجرام وGemini) الموجود بجانبه.

المتغيرات السرية المطلوبة (GitHub Secrets):
    TELEGRAM_BOT_TOKEN
    GEMINI_API_KEY
"""

import json
import re
import statistics
import sys

import requests
from bs4 import BeautifulSoup

from dh_core import *  # noqa: F401,F403


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

def match_known_part(title):
    """يبحث في العنوان عن اسم قطعة معروفة ويعيد مفتاحها أو None."""
    compact = re.sub(r"[\s\-]+", "", title.lower())
    for key in sorted(KNOWN_PARTS, key=len, reverse=True):
        if key in compact:
            return key
    return None


def has_word(text, words):
    """هل يحوي النص إحدى الكلمات (ككلمة كاملة، مع جمعها بحرف s)؟"""
    lowered = text.lower()
    for word in words:
        pattern = r"(?<![a-z0-9])" + re.escape(word) + r"s?(?![a-z0-9])"
        if re.search(pattern, lowered):
            return True
    return False


def is_damage_free(damage_text):
    """هل وصف التلف يعني عدم وجود تلف ظاهر؟"""
    text = (damage_text or "").strip().lower()
    return text in ("", "none", "no") or text.startswith("لا يوجد") or text.startswith("لا شيء")


def prefilter_listing(listing):
    """فحص سريع على العنوان قبل أي تحليل. يعيد (مفتاح القطعة، سبب الرفض)."""
    title = listing["title"]
    key = match_known_part(title)
    if not key:
        return None, ""
    if not listing["price"] or listing["price"] <= 0:
        return None, ""
    if has_word(title, ACCESSORY_WORDS):
        return None, "العنوان يذكر " + key + " لكنه يصف ملحقاً"
    if has_word(title, BROKEN_WORDS):
        return None, "العنوان يشير إلى تلف أو عطل"
    return key, ""


_COMPS_CACHE = {}


def get_comparable_stats(part_key):
    """يحسب وسيط أسعار إعلانات مماثلة حالية في المدينة نفسها، أو None إن لم تكفِ."""
    if part_key in _COMPS_CACHE:
        return _COMPS_CACHE[part_key]

    query = KNOWN_PARTS[part_key][0]
    prices = []
    for item in search_listings(query):
        if match_known_part(item["title"]) != part_key:
            continue
        if not item["price"] or item["price"] <= 0:
            continue
        if has_word(item["title"], ACCESSORY_WORDS + BROKEN_WORDS + BUNDLE_WORDS):
            continue
        prices.append(item["price"])

    stats = None
    if len(prices) >= COMPS_MIN_SAMPLES:
        rough = statistics.median(prices)
        kept = [price for price in prices if 0.4 * rough <= price <= 2.5 * rough]
        if len(kept) >= COMPS_MIN_SAMPLES:
            stats = {"median": round(statistics.median(kept)), "count": len(kept)}

    print("بيانات المقارنة لـ", part_key, ":", stats)
    _COMPS_CACHE[part_key] = stats
    return stats


def compute_valuation(listing, part_key):
    """يعيد القيمة السوقية والربح، أو None إن لم تتوفر بيانات مقارنة كافية."""
    stats = get_comparable_stats(part_key)
    if not stats:
        return None
    value = stats["median"]
    profit = round(value * (1 - SELLING_FEE_RATE) - listing["price"] - SHIPPING_COST)
    return {"value": value, "count": stats["count"], "profit": profit}


def assess_listing(listing, image_url):
    """يجمع الفحوص كلها ويعيد قراراً منظماً مع أسبابه."""
    title = listing["title"]
    title_key = match_known_part(title)
    vision = analyze_image_structured(image_url) if image_url else None
    notes = []
    blocked = False

    if not title_key:
        notes.append("لا يوجد اسم قطعة معروفة في العنوان")
    else:
        expected = KNOWN_PARTS[title_key][1]
        if has_word(title, ACCESSORY_WORDS):
            blocked = True
            notes.append("العنوان يذكر " + title_key + " لكنه يصف ملحقاً وليس القطعة نفسها")
        if has_word(title, BROKEN_WORDS):
            blocked = True
            notes.append("العنوان يشير إلى تلف أو عطل")
        if vision and vision["category"] != expected:
            blocked = True
            notes.append(
                "تعارض: العنوان يشير إلى " + title_key + " ("
                + VISION_CATEGORIES[expected] + ") لكن الصورة تُظهر: "
                + VISION_CATEGORIES[vision["category"]]
            )

    valuation = None
    if title_key and not blocked and listing["price"]:
        valuation = compute_valuation(listing, title_key)
        if not valuation:
            notes.append("لا توجد إعلانات مماثلة كافية لتقدير القيمة السوقية")

    if blocked:
        decision = DECISION_REVIEW
    elif vision is None:
        decision = DECISION_REVIEW
        notes.append("تعذر تحليل الصورة")
    elif not valuation:
        decision = DECISION_UNKNOWN
    elif valuation["profit"] < MIN_PROFIT:
        decision = DECISION_SKIP
    elif vision["confidence"] < MIN_VISION_CONFIDENCE:
        decision = DECISION_REVIEW
        notes.append("ثقة التعرف على الصورة منخفضة")
    elif not is_damage_free(vision["damage"]):
        decision = DECISION_REVIEW
        notes.append("تلف ظاهر أو غير واضح في الصورة")
    else:
        decision = DECISION_BUY

    return {"decision": decision, "vision": vision, "valuation": valuation, "notes": notes}


def format_report(listing, result):
    """يبني نص رسالة تيليجرام من نتيجة الفحص."""
    vision = result["vision"]
    valuation = result["valuation"]
    lines = ["القرار: " + result["decision"], "", "العنوان: " + listing["title"]]

    if vision:
        lines.append("الصنف (من الصورة): " + VISION_CATEGORIES[vision["category"]])
        lines.append("العلامة والموديل: " + vision["brand"] + " / " + vision["model"])
        lines.append("الحالة: " + vision["condition"])
        lines.append("التلف الظاهر: " + vision["damage"])
        lines.append("درجة الثقة: " + str(vision["confidence"]) + "/100")
    else:
        lines.append("تحليل الصورة: غير متاح")

    lines.append("")
    price_text = str(listing["price"]) + "$" if listing["price"] else "غير مذكور"
    lines.append("السعر المطلوب: " + price_text)
    if SHIPPING_COST:
        lines.append("الشحن: " + str(SHIPPING_COST) + "$ (تقدير ثابت)")
    else:
        lines.append("الشحن: غير محسوب (استلام شخصي)")

    if valuation:
        lines.append(
            "القيمة السوقية: " + str(valuation["value"]) + "$ (وسيط "
            + str(valuation["count"]) + " إعلانات مماثلة في المدينة نفسها؛ أسعار طلب وليست أسعار بيع)"
        )
        lines.append(
            "الربح التقديري: " + str(valuation["profit"])
            + "$ (القيمة السوقية ناقص السعر المطلوب"
            + (" والرسوم والشحن" if (SELLING_FEE_RATE or SHIPPING_COST) else "") + ")"
        )
    else:
        lines.append("القيمة السوقية: غير معروفة")
        lines.append("الربح التقديري: لم يُحسب")

    if result["notes"]:
        lines.append("")
        lines.append("ملاحظات:")
        for note in result["notes"]:
            lines.append("- " + note)

    lines.append("")
    lines.append(listing["link"])
    return "\n".join(lines)


def send_report(image_url, text):
    """يرسل التقرير مع الصورة، وإن طال النص يرسله كاملاً في رسالة منفصلة."""
    if not image_url:
        return send_telegram_alert(text)
    if len(text) <= 1000:
        return send_telegram_photo(image_url, text) or send_telegram_alert(text)
    short = "\n".join(text.split("\n")[:3])
    photo_ok = send_telegram_photo(image_url, short)
    text_ok = send_telegram_alert(text)
    return photo_ok or text_ok


# ============================================================
# ذاكرة الصفقات المرسلة (لمنع تكرار التنبيه)
# ============================================================

def load_seen():
    """يقرأ قائمة الروابط المرسلة سابقاً."""
    try:
        with open(SEEN_FILE, encoding="utf-8") as file:
            data = json.load(file)
        if isinstance(data, list):
            return data
    except FileNotFoundError:
        pass
    except Exception as error:
        print("تعذر قراءة ملف الذاكرة:", error)
    return []


def save_seen(seen_list):
    """يحفظ آخر الروابط المرسلة."""
    try:
        with open(SEEN_FILE, "w", encoding="utf-8") as file:
            json.dump(seen_list[-MAX_SEEN:], file, ensure_ascii=False, indent=0)
    except Exception as error:
        print("تعذر حفظ ملف الذاكرة:", error)


# ============================================================
# التشغيل العادي
# ============================================================

def main():
    print("=== بدء التشغيل العادي ===")
    seen_links = set()
    sent_list = load_seen()
    sent_set = set(sent_list)
    alerts_sent = 0

    for term in SEARCH_TERMS:
        for listing in search_listings(term):
            link = listing["link"]
            if link in seen_links:
                continue
            seen_links.add(link)

            # 1) فحص سريع على العنوان
            part_key, reject_reason = prefilter_listing(listing)
            if not part_key:
                if reject_reason:
                    print("تُجاهل:", listing["title"], "-", reject_reason)
                continue

            # 2) قيمة سوقية من إعلانات مماثلة، وإلا لا شيء
            valuation = compute_valuation(listing, part_key)
            if not valuation:
                print("قيمة غير معروفة، تُتجاهل:", listing["title"])
                continue
            if valuation["profit"] < MIN_PROFIT:
                continue

            if link in sent_set:
                print("أُرسلت هذه الصفقة سابقاً، تُتجاهل:", listing["title"])
                continue

            # 3) تحليل الصورة والتحقق من تطابق الصنف
            print("مرشحة للفحص:", listing["title"], listing["price"])
            image_url = get_listing_image(link)
            result = assess_listing(listing, image_url)
            print("القرار:", result["decision"], "|", result["notes"])
            if result["decision"] not in (DECISION_BUY, DECISION_REVIEW):
                continue

            sent = send_report(image_url, format_report(listing, result))
            if sent:
                sent_list.append(link)
                sent_set.add(link)
                save_seen(sent_list)
                alerts_sent += 1
                if alerts_sent >= MAX_ALERTS_PER_RUN:
                    print("تم بلوغ الحد الأقصى للتنبيهات.")
                    return

    save_seen(sent_list)
    print("=== انتهى التشغيل العادي. عدد التنبيهات:", alerts_sent, "===")


# ============================================================
# وضع الاختبار
# ============================================================

# كل اختبار: (اسمه، كلمات البحث، هل يقبل أي إعلان بصورة إن لم يجد المطلوب)
TEST_SCENARIOS = [
    ("الاختبار 1: كرت شاشة", TEST_SEARCH_TERMS, True),
    ("الاختبار 2: ملحق يحمل اسم PS5 (للتأكد من عدم الخلط)", TEST_ACCESSORY_TERMS, False),
]


def find_test_listing(terms, fallback_any):
    """يختار إعلاناً حقيقياً بصورة، يفضّل من يحمل عنوانه اسم قطعة معروفة."""
    for term in terms:
        for listing in search_listings(term)[:15]:
            if not match_known_part(listing["title"]):
                continue
            image_url = get_listing_image(listing["link"])
            if image_url:
                return listing, image_url

    if fallback_any:
        for term in SEARCH_TERMS:
            for listing in search_listings(term)[:15]:
                image_url = get_listing_image(listing["link"])
                if image_url:
                    return listing, image_url

    return None, None


def run_vision_test():
    print("=== بدء الاختبار ===")

    if not send_telegram_alert(
        "بدأ الاختبار: سيصلك اختباران على إعلانات حقيقية. الأول كرت شاشة، "
        "والثاني ملحق يحمل اسم PS5 للتأكد من عدم الخلط بينهما."
    ):
        print("فشل الإرسال لتيليجرام. تأكد من صحة توكن البوت.")
        return

    for name, terms, fallback_any in TEST_SCENARIOS:
        listing, image_url = find_test_listing(terms, fallback_any)
        if not listing:
            print(name, ": لم يُعثر على إعلان مناسب")
            send_telegram_alert(name + "\n\nلم يُعثر على إعلان مناسب الآن. أعد التشغيل لاحقاً.")
            continue

        print(name, "->", listing["title"])
        result = assess_listing(listing, image_url)
        text = name + "\n\n" + format_report(listing, result)
        if not result["vision"] and GEMINI_ERRORS:
            text += "\n\nأسباب فشل Gemini:\n" + "\n".join(GEMINI_ERRORS[-4:])
        send_report(image_url, text)

    print("=== انتهى الاختبار. تحقق من تيليجرام الآن ===")


# ============================================================
# نقطة البداية
# ============================================================

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        run_vision_test()
    else:
        main()

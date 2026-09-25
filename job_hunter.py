import requests
from bs4 import BeautifulSoup
import os
import json

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
STATE_FILE = "seen_jobs.json"

KEYWORDS = [
    "ترجمة", "كتابة محتوى", "تفريغ صوتي", "إدخال بيانات", "كتابة",
    "translation", "content writing", "data entry", "transcription",
    "python", "web scraping", "برمجة", "سكربت", "automation", "script"
]

SCAM_KEYWORDS = [
    "whatsapp only", "telegram only", "تواصل واتساب فقط",
    "دفع اشتراك", "رسوم تسجيل", "registration fee", "pay to start",
    "بدون خبرة راتب ضخم", "دخل يومي مضمون", "guaranteed daily income",
    "ادفع اولا", "تحويل مسبق"
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}


def load_seen():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_seen(seen):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(list(seen), f, ensure_ascii=False)


def get_chat_id():
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
    r = requests.get(url).json()
    try:
        return r["result"][-1]["message"]["chat"]["id"]
    except Exception:
        print("لم يتم إيجاد chat_id — تأكد أنك أرسلت أي رسالة للبوت أولاً")
        return None


def send_telegram_message(chat_id, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {"chat_id": chat_id, "text": text}
    requests.post(url, data=data)


def matches_keywords(text):
    text_lower = text.lower()
    return any(k.lower() in text_lower for k in KEYWORDS)


def is_scam_pattern(text):
    text_lower = text.lower()
    return any(k.lower() in text_lower for k in SCAM_KEYWORDS)


def search_freelancer():
    jobs = []
    try:
        url = "https://www.freelancer.com/jobs/"
        r = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
        links = soup.find_all("a", href=True)
        for link in links:
            href = link["href"]
            title = link.get_text(strip=True)
            if "/projects/" in href and title and len(title) > 5:
                full_link = href if href.startswith("http") else "https://www.freelancer.com" + href
                jobs.append({"id": full_link, "title": title, "desc": "", "link": full_link})
    except Exception as e:
        print("خطأ في Freelancer:", e)
    return jobs


def search_mostaql():
    jobs = []
    try:
        url = "https://mostaql.com/projects"
        r = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
        links = soup.find_all("a", href=True)
        for link in links:
            href = link["href"]
            title = link.get_text(strip=True)
            if "/project/" in href and title and len(title) > 5:
                full_link = href if href.startswith("http") else "https://mostaql.com" + href
                jobs.append({"id": full_link, "title": title, "desc": "", "link": full_link})
    except Exception as e:
        print("خطأ في Mostaql:", e)
    return jobs


def main():
    chat_id = get_chat_id()
    if not chat_id:
        return

    seen = load_seen()
    all_jobs = search_freelancer() + search_mostaql()
    print(f"عدد المشاريع المكتشفة إجمالاً: {len(all_jobs)}")

    new_jobs = [
        j for j in all_jobs
        if j["id"] not in seen
        and matches_keywords(j["title"])
        and not is_scam_pattern(j["title"])
    ]
    print(f"عدد المشاريع الجديدة المطابقة: {len(new_jobs)}")

    for job in new_jobs:
        message = f"🆕 فرصة عمل جديدة\n\n{job['title']}\n\n🔗 {job['link']}"
        send_telegram_message(chat_id, message)
        seen.add(job["id"])

    save_seen(seen)


if __name__ == "__main__":
    main()

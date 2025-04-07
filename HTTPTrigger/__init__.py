import azure.functions as func
import feedparser
import requests
import os
import json
import re
from datetime import datetime, timedelta

def get_recent_posts(rss_url):
    feed = feedparser.parse(rss_url)
    today = datetime.utcnow()
    one_week_ago = today - timedelta(days=7)
    recent_posts = []

    for entry in feed.entries:
        pub_date = datetime(*entry.published_parsed[:6])
        tterms = [t['term'] for t in entry.tags] if 'tags' in entry else []
        tag_ = ', '.join(tterms[1:]) if tterms else ""

        if pub_date >= one_week_ago:
            recent_posts.append({
                "title": entry.title,
                "link": entry.link,
                "date": pub_date.strftime("%Y-%m-%d"),
                "summary": entry.summary,
                "tag": tag_,
            })

    return recent_posts

def make_message(posts):
    if not posts:
        return {"text": "최근 일주일 내 새 포스팅이 없습니다."}

    nposts = ""
    for post in posts:
        nposts += (f"{post['date']}\n[{post.get('summary', 'Update')}] {post['title']}\n"
                   f"category > {post['tag']}\n{post['link']}\n\n ")

    message_text = edit_message(nposts)
    return {"text": message_text}


def edit_message(message):
    pattern = re.compile(r"(\d{4}-\d{2}-\d{2})\n\[(.*?)\] (.*?)\ncategory > (.*?)\n(https://\S+)")
    matches = pattern.findall(message)

    # title에서 Launched, Preview, Retirement 제거
    cleaned = []
    for date, status, title, category, link in matches:
        for keyword in ["Launched", "Preview", "Retirement"]:
            title = title.replace(keyword, "").strip()
        cleaned.append((date, status, title, category, link))

    # 날짜 기준 정렬 (내림차순)
    cleaned.sort(reverse=True, key=lambda x: x[0])

    grouped = {
        "Launched": [],
        "Preview": [],
        "Retirement": [],
        "Other": []
    }

    for date, status, title, category, link in cleaned:
        if "Launched" in status:
            grouped["Launched"].append((date, title, category, link))
        elif "Preview" in status:
            grouped["Preview"].append((date, title, category, link))
        elif "Retirement" in status:
            grouped["Retirement"].append((date, title, category, link))
        else:
            grouped["Other"].append((date, title, category, link))

    output = "🆕 Azure Updates (최근 1주일)\n\n"

    def format_group(name, emoji, items):
        if not items:
            return ""
        section = f"## {emoji} {name}\n\n"
        for date, title, category, link in items:
            section += (f"📅 {date}\n"
                        f"🔹 {title}\n"
                        f"📌 Category: {category}\n"
                        f"🔗 {link}\n\n")
        return section

    output += format_group("Launched", "🟢", grouped["Launched"])
    output += format_group("Preview", "🟡", grouped["Preview"])
    output += format_group("Retirement", "❌", grouped["Retirement"])
    output += format_group("기타", "ℹ️", grouped["Other"])

    return output


def send_to_teams(message, webhook_url):
    headers = {"Content-Type": "application/json"}
    response = requests.post(webhook_url, headers=headers, data=json.dumps(message))
    return response

def main(req: func.HttpRequest) -> func.HttpResponse:
    try:
        rss_url = os.getenv("URL")
        webhook_url = os.getenv("WEBHOOK")

        if not rss_url or not webhook_url:
            return func.HttpResponse("환경 변수(URL, WEBHOOK)가 설정되지 않았습니다.", status_code=500)

        recent_posts = get_recent_posts(rss_url)
        message = make_message(recent_posts)
        response = send_to_teams(message, webhook_url)

        if response.status_code == 200:
            return func.HttpResponse("✅ Microsoft Teams 메시지 전송 성공!", status_code=200)
        else:
            return func.HttpResponse(f"❌ 메시지 전송 실패: {response.status_code} - {response.text}", status_code=500)

    except Exception as e:
        return func.HttpResponse(f"에러 발생: {str(e)}", status_code=500)

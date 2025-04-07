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
    matches.sort(reverse=True, key=lambda x: x[0])

    output = "🆕 Azure Updates \n\n<br>"
    current_date = None
    for date, status, title, category, link in matches:
        if date != current_date:
            output += f"📅 {date}\n\n"
            current_date = date
        emoji = "🟢" if "Launched" in status else "🟡"
        output += f"{emoji} {title} \n\n 🔗 {link}  \n  📌Category: {category}\n\n<br>"

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

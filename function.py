import feedparser
import requests
import os
import json
import re
from datetime import datetime, timedelta
import azure.functions as func


# Microsoft Teams Webhook URL (생성한 URL 입력)
TEAMS_WEBHOOK_URL = os.getenv("WEBHOOK")

# RSS 피드 URL
RSS_FEED_URL = os.getenv("URL")

def get_recent_posts():
    """ 최근 1주일 내의 블로그 포스팅 가져오기 """
    feed = feedparser.parse(RSS_FEED_URL)
    today = datetime.utcnow()
    one_week_ago = today - timedelta(days=7)
    recent_posts = []

    for entry in feed.entries:
        pub_date = datetime(*entry.published_parsed[:6])  # 날짜 변환
        tterms = [ t['term'] for t in entry.tags ]
        tag_ = ', '.join(tterms[1:])
        # 최근 7일 이내라면 리스트에 추가
        if pub_date >= one_week_ago:
            recent_posts.append({
                "title": entry.title,
                "link": entry.link,
                "date": pub_date.strftime("%Y-%m-%d"),
                "summary":entry.summary,
                "tag":tag_,
            })
    
    return recent_posts

def make_message(posts):
    """ Microsoft Teams로 메시지 전송 """
    if not posts:
        message = {
            "text": "최근 일주일 내 새 포스팅이 없습니다."
        }
    else:
        nposts = ""
        for post in posts:
            nposts += (f"{post['date']}\n{post['title']}\ncategory > {post['tag']}\n{post['link']}\n\n ")

        message_text = edit_message(nposts)
        message = {"text": message_text}

    return message
    
def edit_message(message):
    # 정규식으로 데이터 파싱

    pattern = re.compile(r"(\d{4}-\d{2}-\d{2})\n\[(.*?)\] (.*?)\ncategory > (.*?)\n(https://\S+)")
    matches = pattern.findall(message)
    # 날짜별 정렬
    matches.sort(reverse=True, key=lambda x: x[0])

    output = "🆕 Azure Updates \n\n "
    output+=f"<br>"


    current_date = None
    for date, status, title, category, link in matches:
        if date != current_date:
            output += f"📅 {date}\n\n"
            current_date = date

        emoji = "🟢" if "Launched" in status else "🟡"
        output += f"{emoji} {title} \n\n 🔗 {link}  \n  📌Category: {category}\n\n"
        output+=f"<br>"
        

    # 출력
    return output


def send_to_teams(message):
    headers = {"Content-Type": "application/json"}
    response = requests.post(TEAMS_WEBHOOK_URL, headers=headers, data=json.dumps(message))

    if response.status_code == 200:
        print("Teams 메시지 전송 성공!")
    else:
        print(f"Teams 메시지 전송 실패 > 상태 코드: {response.status_code}, 응답: {response.text}")


def main(mytimer: func.TimerRequest)->None:
    recent_posts = get_recent_posts()
    message = make_message(recent_posts)
    send_to_teams(message)

# 실행
if __name__ == "__main__":
    main(func.TimerRequst(""))

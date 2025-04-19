import logging
import os
import datetime
import requests
from collections import defaultdict
from azure.identity import ClientSecretCredential
import azure.functions as func

def query_cost_by_group(subscription_id, credential, start_date, end_date):
    url = f"https://management.azure.com/subscriptions/{subscription_id}/providers/Microsoft.CostManagement/query?api-version=2023-03-01"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {credential.get_token('https://management.azure.com/.default').token}"
    }

    body = {
        "type": "ActualCost",
        "timeframe": "Custom",
        "timePeriod": {
            "from": start_date,
            "to": end_date
        },
        "dataset": {
            "granularity": "None",
            "aggregation": {
                "totalCost": {
                    "name": "PreTaxCost",
                    "function": "Sum"
                }
            },
            "grouping": [
                {"type": "Dimension", "name": "ResourceGroup"},
                {"type": "Dimension", "name": "ServiceName"}
            ]
        }
    }

    response = requests.post(url, headers=headers, json=body)
    if response.status_code == 200:
        return response.json()["properties"]["rows"]
    else:
        logging.error(f"Error querying group cost for subscription {subscription_id}: {response.status_code}, {response.text}")
        return []

def get_top_resource(subscription_id, credential, start_date, end_date):
    url = f"https://management.azure.com/subscriptions/{subscription_id}/providers/Microsoft.CostManagement/query?api-version=2023-03-01"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {credential.get_token('https://management.azure.com/.default').token}"
    }

    body = {
        "type": "ActualCost",
        "timeframe": "Custom",
        "timePeriod": {
            "from": start_date,
            "to": end_date
        },
        "dataset": {
            "granularity": "None",
            "aggregation": {
                "totalCost": {
                    "name": "PreTaxCost",
                    "function": "Sum"
                }
            },
            "grouping": [
                {"type": "Dimension", "name": "ResourceId"}
            ]
        }
    }

    response = requests.post(url, headers=headers, json=body)
    if response.status_code == 200:
        rows = response.json()["properties"]["rows"]
        if rows:
            top_resource = max(rows, key=lambda x: x[1])  # [resourceId, cost]
            return {"resourceId": top_resource[0], "cost": top_resource[1]}
    else:
        logging.error(f"Error getting top resource: {response.status_code}, {response.text}")
    return None

def parse_cost_to_message(subscription_id, rows):
    grouped_data = defaultdict(lambda: defaultdict(float))
    for row in rows:
        resource_group = row[0] or "Unnamed"
        service_name = row[1] or "Unknown Service"
        cost = row[2]
        grouped_data[resource_group][service_name] += cost

    msg = f"📦 **Subscription**: `{subscription_id}`\n"
    for rg, services in grouped_data.items():
        msg += f"  └ 📁 **Resource Group**: `{rg}`\n"
        for service, cost in services.items():
            msg += f"     └ 🔧 `{service}`: **${cost:.2f}**\n"
    return msg

def send_to_teams(webhook_url, message):
    payload = {
        "text": message
    }
    response = requests.post(webhook_url, json=payload)
    if response.status_code != 200:
        logging.error(f"Failed to send message to Teams: {response.status_code}, {response.text}")

def main(mytimer: func.TimerRequest) -> None:
    logging.info('Azure Cost Function with Teams Notification started.')

    tenant_id = os.environ["AZURE_TENANT_ID"]
    # api 호출을 위해서 필요한 인증 정보
    client_id = os.environ["AZURE_CLIENT_ID"]
    client_secret = os.environ["AZURE_CLIENT_SECRET"]
    c = os.environ["SUBSCRIPTION_IDS"].split(",")
    webhook_url = os.environ["TEAMS_WEBHOOK_URL"]

    credential = ClientSecretCredential(tenant_id, client_id, client_secret)

    # TYPE1. 현재부터 매월 1일 까지의 누적 비용 
    today = datetime.date.today()
    first_day = today.replace(day=1)
    start_date = first_day.isoformat()
    end_date = today.isoformat()
    full_report = f"📊 **Azure 누적 비용 리포트 ({start_date} ~ {end_date})**\n\n"
    
    # TYPE2. 일주일 간의 누적 비용
    today = datetime.date.today()
    week_ago = today - datetime.timedelta(days=6)  # 오늘 포함해서 7일간

    start_date = week_ago.isoformat()
    end_date = today.isoformat()

    full_report = f"📊 **Azure 주간 비용 리포트 ({start_date} ~ {end_date})**\n\n"

    for sub_id in subscription_list:
        rows = query_cost_by_group(sub_id.strip(), credential, start_date, end_date)
        section = parse_cost_to_message(sub_id.strip(), rows)
        full_report += section + "\n"

        # 가장 비용 많이 발생한 리소스
        top = get_top_resource(sub_id.strip(), credential, start_date, end_date)
        if top:
            full_report += (
                f"💸 **Top Resource** in `{sub_id.strip()}`:\n"
                f"   🔗 `{top['resourceId']}`\n"
                f"   💰 Cost: **${top['cost']:.2f}**\n\n"
            )

    send_to_teams(webhook_url, full_report)

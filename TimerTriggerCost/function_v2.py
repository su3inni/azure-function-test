import logging
import os
import datetime
import requests
from collections import defaultdict
from azure.identity import ClientSecretCredential
import azure.functions as func

def get_subscription_names(token):
    url = "https://management.azure.com/subscriptions?api-version=2020-01-01"
    headers = {
        "Authorization": f"Bearer {token}"
    }

    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        subs = response.json().get("value", [])
        return {s["subscriptionId"]: s["displayName"] for s in subs}
    else:
        logging.error(f"Failed to get subscription names: {response.status_code}, {response.text}")
        return {}

def query_cost_data(subscription_id, token, start_date, end_date):
    url = f"https://management.azure.com/subscriptions/{subscription_id}/providers/Microsoft.CostManagement/query?api-version=2023-03-01"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
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
                {"type": "Dimension", "name": "ServiceName"},
                {"type": "Dimension", "name": "ResourceId"}
            ]
        }
    }

    response = requests.post(url, headers=headers, json=body)
    if response.status_code == 200:
        return response.json()["properties"]["rows"]
    else:
        logging.error(f"Error querying cost data for subscription {subscription_id}: {response.status_code}, {response.text}")
        return []

def parse_cost_data(subscription_display_name, rows):
    grouped_data = defaultdict(lambda: defaultdict(float))
    top_resource = {"resourceId": None, "cost": 0.0}

    for row in rows:
        cost = row[0]
        resource_group = row[1]
        service_name = row[2]
        resource_id = row[3] 
        cost_unit = row[4]
        
        grouped_data[resource_group][service_name] += cost

        if resource_id and cost > top_resource["cost"]:
            top_resource = {"resourceId": resource_id, "cost": cost}

    msg = f"📦 **Subscription**: `{subscription_display_name}`<br>"
    for rg, services in grouped_data.items():
        msg += f" &ensp; └ 📁 **Resource Group**: `{rg}`<br>"
        for service, cost in services.items():
            msg += f"   &emsp; └ 🔧 `{service}`: **{cost_unit}{cost:.2f}**<br>"

    msg += (
        f"<br>💸 **Top Resource** in `{subscription_display_name}`:<br>"
        f"  &ensp; 🔗 `{top_resource['resourceId']}`<br>"
        f"  &ensp; 💰 Cost: **{cost_unit}{top_resource['cost']:.2f}**<br>"
    )

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
    client_id = os.environ["AZURE_CLIENT_ID"]
    client_secret = os.environ["AZURE_CLIENT_SECRET"]
    # subscription_list = os.environ["SUBSCRIPTION_IDS"].split(",")
    webhook_url = os.environ["TEAMS_WEBHOOK_URL"]

    credential = ClientSecretCredential(tenant_id, client_id, client_secret)
    token = credential.get_token('https://management.azure.com/.default').token

    # 주간 비용 계산 (오늘 포함 7일)
    today = datetime.date.today()
    week_ago = today - datetime.timedelta(days=6)
    start_date = week_ago.isoformat()
    end_date = today.isoformat()

    full_report = f"📊 **Azure 주간 비용 리포트 ({start_date} ~ {end_date})**\n\n"

    # Subscription 이름 가져오기
    subscription_name_map = get_subscription_names(token)
    for sub_id, display_name in subscription_name_map.items():
        sub_id = sub_id.strip()
        display_name = subscription_name_map.get(sub_id, sub_id)  # fallback to ID
        rows = query_cost_data(sub_id, token, start_date, end_date)
        section = parse_cost_data(display_name, rows)
        full_report += section + "\n"

    send_to_teams(webhook_url, full_report)

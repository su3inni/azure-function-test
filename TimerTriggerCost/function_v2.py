import logging
import os
import datetime
import requests
from collections import defaultdict
from azure.identity import ClientSecretCredential
import azure.functions as func

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

def parse_cost_data(subscription_id, rows):
    grouped_data = defaultdict(lambda: defaultdict(float))
    top_resource = {"resourceId": None, "cost": 0.0}

    for row in rows:
        logging.info(row)
        cost = row[0]
        resource_group = row[1]
        service_name = row[2]
        resource_id = row[3] if len(row) > 3 else None

        grouped_data[resource_group][service_name] += cost

        if resource_id and cost > top_resource["cost"]:
            top_resource = {"resourceId": resource_id, "cost": cost}

    msg = f"📦 **Subscription**: `{subscription_id}`\n"
    for rg, services in grouped_data.items():
        msg += f"  └ 📁 **Resource Group**: `{rg}`\n"
        for service, cost in services.items():
            msg += f"     └ 🔧 `{service}`: **${cost:.2f}**\n"

    msg += (
        f"\n💸 **Top Resource** in `{subscription_id}`:\n"
        f"   🔗 `{top_resource['resourceId']}`\n"
        f"   💰 Cost: **${top_resource['cost']:.2f}**\n"
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
    subscription_list = os.environ["SUBSCRIPTION_IDS"].split(",")
    webhook_url = os.environ["TEAMS_WEBHOOK_URL"]

    credential = ClientSecretCredential(tenant_id, client_id, client_secret)
    token = credential.get_token('https://management.azure.com/.default').token

    # 지난 7일간 비용
    today = datetime.date.today()
    week_ago = today - datetime.timedelta(days=6)
    start_date = week_ago.isoformat()
    end_date = today.isoformat()

    full_report = f"📊 **Azure 주간 비용 리포트 ({start_date} ~ {end_date})**\n\n"

    for sub_id in subscription_list:
        sub_id = sub_id.strip()
        rows = query_cost_data(sub_id, token, start_date, end_date)
        section = parse_cost_data(sub_id, rows)
        full_report += section + "\n"

    send_to_teams(webhook_url, full_report)

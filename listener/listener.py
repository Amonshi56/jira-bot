from flask import Flask, request
import asyncio
import aiosqlite
import requests

app = Flask(__name__)

TELEGRAM_BOT_TOKEN = ""
DB_PATH = ""
STATUS_MAP = {
    "To Do": "📝 К выполнению",
    "In Progress": "🚧 В работе",
    "In Review": "🔍 На проверке",
    "Done": "✅ Готово",
    "Blocked": "⛔ Заблокирована",
    "Reopened": "♻️ Переоткрыта",
    "Closed": "🔒 Закрыта",
    "Cancelled": "❌ Отменена",
    "Test": "🧪 На тестировании",
    "Ready for QA": "📦 Готово к QA",
    "Deployed": "🚀 Развернута",
}

def send_telegram_message(message, chat_id):
    telegram_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message
    }
    response = requests.post(telegram_url, data=payload)
    if response.status_code == 200:
        print("Сообщение отправлено в Telegram")
    else:
        print("Ошибка при отправке сообщения", response.text)

async def change_status(task_key, new_status):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE tasks SET state = ? WHERE task_key = ?",
            (new_status, task_key)
        )
        await db.commit()

async def get_chat_id_by_task_key(task_key: str, label_user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            SELECT user_id FROM tasks WHERE task_key = ?
        """, (task_key,))
        row = await cursor.fetchone()
        return row[0] if row else label_user_id        

@app.route('/jira-webhook', methods=['POST'])
def jira_webhook():
    data = request.json
    print('Received event:', data)

    issue_key = data['issue']['key']
    label = data['issue']['fields'].get('labels', [None])[0]
    label_user_id = label.split(":")[1] if label and label.startswith("user_id:") else None



    async def get_and_send_message():
        chat_id = await get_chat_id_by_task_key(issue_key, label_user_id)
        message = ""

        if 'comment' in data:
            comments = data['comment']['body']
            message = f"К задаче {issue_key} добавлен новый комментарий:\n {comments}"   
        elif 'changelog' in data:
            for item in data['changelog'].get('items', []):
                if item.get('field') == 'status':
                    from_status = item.get('fromString', 'неизвестно')
                    readable_from_status = STATUS_MAP.get(from_status, "📄 Неизвестный статус")
                    to_status = item.get('toString', 'неизвестно')
                    readable_to_status = STATUS_MAP.get(to_status, "📄 Неизвестный статус")
                    message = f"Статус задачи {issue_key} изменился: {readable_from_status} → {readable_to_status}"
                    await change_status(issue_key, readable_to_status)
                    break

        send_telegram_message(message, chat_id)
    
    asyncio.run(get_and_send_message())

    return "OK", 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=3000)

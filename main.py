import os
import json
import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from flask import Flask, request, abort
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import Configuration, ApiClient, MessagingApi, ReplyMessageRequest, TextMessage, QuickReply, QuickReplyItem, PostbackAction, PushMessageRequest
from linebot.v3.webhooks import MessageEvent, TextMessageContent, PostbackEvent
import google.generativeai as genai

app = Flask(__name__)

# --- 設定 ---
conf = Configuration(access_token=os.environ["LINE_CHANNEL_ACCESS_TOKEN"])
handler = WebhookHandler(os.environ["LINE_CHANNEL_SECRET"])
genai.configure(api_key=os.environ["GEMINI_API_KEY"])
model = genai.GenerativeModel('gemini-3.5-flash')

# 一時的な記憶（家族構成を一時的に保持）
user_temp_data = {}

def get_sheet():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds_dict = json.loads(os.environ["GOOGLE_CREDENTIALS_JSON"])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    return client.open_by_key(os.environ["SPREADSHEET_ID"]).sheet1

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    msg = event.message.text
    tk = event.reply_token
    user_id = event.source.user_id

    if msg in ["メニュー", "スタート", "設定変更"]:
        show_family_selection(tk)
    
    # 登録フローの途中（アレルギー入力待ち）か判定
    elif user_id in user_temp_data:
        # スプレッドシートに新規登録する
        register_new_user(event, msg)
        
    else:
        # 通常のレシピ検索
        try:
            sheet = get_sheet()
            cell = sheet.find(user_id)
            if not cell:
                send_reply(tk, "まずは「メニュー」と送って、登録をお願いします！")
            else:
                handle_ai_generation(event, sheet, cell.row)
        except Exception as e:
            print(f"Error: {e}")
            send_reply(tk, "通信エラーが起きました。スプレッドシートの共有設定やIDを確認してください。")

def show_family_selection(tk):
    quick_reply = QuickReply(items=[
        QuickReplyItem(action=PostbackAction(label="1人", data="step=dislike&family=1人")),
        QuickReplyItem(action=PostbackAction(label="2人", data="step=dislike&family=2人")),
        QuickReplyItem(action=PostbackAction(label="3人", data="step=dislike&family=3人")),
        QuickReplyItem(action=PostbackAction(label="4人以上", data="step=dislike&family=4人以上"))
    ])
    send_reply(tk, "何人分のごはんを作ることが多いですか？👪", quick_reply)

@handler.add(PostbackEvent)
def handle_postback(event):
    data = event.postback.data
    tk = event.reply_token
    user_id = event.source.user_id
    params = dict(item.split('=') for item in data.split('&'))
    
    if params.get('step') == "dislike":
        # 家族構成を一時的にメモリに保存
        user_temp_data[user_id] = params.get('family')
        send_reply(tk, f"{params.get('family')}分ですね！\n次に【苦手なものやアレルギー】を教えてください。\n（特になければ「なし」でOK！）")

def register_new_user(event, dislike_msg):
    user_id = event.source.user_id
    family = user_temp_data.pop(user_id) # 保存しておいた家族構成を取り出す
    today = datetime.date.today().strftime("%Y/%m/%d")
    
    try:
        sheet = get_sheet()
        # すでにいたら上書き、いなければ追加
        cell = sheet.find(user_id)
        if cell:
            sheet.update_cell(cell.row, 3, family)
            sheet.update_cell(cell.row, 4, dislike_msg)
        else:
            sheet.append_row([user_id, "ユーザー", family, dislike_msg, "Free", today])
        
        send_reply(event.reply_token, "登録が完了しました！✨\n次からは、使いたい食材を送るだけでレシピを提案しますよ。")
    except Exception as e:
        print(f"Register Error: {e}")
        send_reply(event.reply_token, "登録中にエラーが発生しました。設定（スプレッドシートの共有など）を確認してください。")

def handle_ai_generation(event, sheet, row_idx):
    user_id = event.source.user_id
    msg = event.message.text
    tk = event.reply_token
    
    row_data = sheet.row_values(row_idx)
    family = row_data[2] if len(row_data) > 2 else "不明"
    dislike = row_data[3] if len(row_data) > 3 else "特になし"

    send_reply(tk, "今からレシピを考えるので、少しお待ちくださいね。🍳")

    try:
        prompt = f"料理研究家として提案してください。食材「{msg}」を使い、{family}分で、{dislike}を避けた実在するレシピをURL付きで教えて。家事のコツも添えて。"
        response = model.generate_content(prompt)
        
        with ApiClient(conf) as api_client:
            line_api = MessagingApi(api_client)
            line_api.push_message(PushMessageRequest(
                to=user_id, messages=[TextMessage(text=response.text)]
            ))
    except Exception as e:
        print(f"AI Error: {e}")

def send_reply(tk, text, quick_reply=None):
    with ApiClient(conf) as api_client:
        line_api = MessagingApi(api_client)
        line_api.reply_message(ReplyMessageRequest(
            reply_token=tk, messages=[TextMessage(text=text, quick_reply=quick_reply)]
        ))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

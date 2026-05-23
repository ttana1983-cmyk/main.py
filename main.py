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
user_temp_data = {}

# --- 設定 ---
conf = Configuration(access_token=os.environ["LINE_CHANNEL_ACCESS_TOKEN"])
handler = WebhookHandler(os.environ["LINE_CHANNEL_SECRET"])
genai.configure(api_key=os.environ["GEMINI_API_KEY"])
model = genai.GenerativeModel('gemini-3.5-flash')

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
    elif user_id in user_temp_data:
        register_new_user(event, msg)
    else:
        try:
            sheet = get_sheet()
            cell = sheet.find(user_id)
            if not cell:
                send_reply(tk, "まずは「メニュー」と送って登録してくださいね！")
            else:
                # 直前の食材を一時保存（再提案用）
                user_temp_data[f"{user_id}_last_food"] = msg
                handle_ai_generation(event, sheet, cell.row, "指定なし", msg)
        except Exception as e:
            send_reply(tk, "エラーが発生しました。設定を確認してください。")

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
        user_temp_data[user_id] = params.get('family')
        send_reply(tk, f"{params.get('family')}分ですね！\n次に【苦手なものやアレルギー】を教えてください。")
    
    elif params.get('meal'):
        meal_type = {"morning": "朝ごはん", "lunch": "昼ごはん", "dinner": "夜ごはん"}.get(params.get('meal'))
        user_temp_data[f"{user_id}_meal"] = meal_type
        send_reply(tk, f"{meal_type}ですね！承知いたしました。\n\n今、使いたい食材（鶏肉、大根など）を教えてください🍳")

    # 「別のレシピ」ボタンが押された時
    elif params.get('step') == "retry":
        try:
            sheet = get_sheet()
            cell = sheet.find(user_id)
            last_food = user_temp_data.get(f"{user_id}_last_food", "あるもの")
            meal_type = user_temp_data.get(f"{user_id}_meal", "指定なし")
            handle_ai_generation(event, sheet, cell.row, meal_type, last_food, is_retry=True)
        except:
            send_reply(tk, "すみません、もう一度食材を教えていただけますか？")

def register_new_user(event, dislike_msg):
    user_id = event.source.user_id
    family = user_temp_data.pop(user_id, "不明")
    try:
        sheet = get_sheet()
        cell = sheet.find(user_id)
        if cell:
            sheet.update_cell(cell.row, 3, family); sheet.update_cell(cell.row, 4, dislike_msg)
        else:
            sheet.append_row([user_id, "ユーザー", family, dislike_msg, "Free", datetime.date.today().strftime("%Y/%m/%d")])
        
        quick_reply = QuickReply(items=[
            QuickReplyItem(action=PostbackAction(label="朝ごはん ☀️", data="meal=morning")),
            QuickReplyItem(action=PostbackAction(label="昼ごはん 🕛", data="meal=lunch")),
            QuickReplyItem(action=PostbackAction(label="夜ごはん 🌙", data="meal=dinner"))
        ])
        send_reply(event.reply_token, f"登録完了！{family}分の献立はお任せください。\n\nさて、今日のごはんは何にしましょうか？", quick_reply)
    except:
        send_reply(event.reply_token, "登録エラーです。")

def handle_ai_generation(event, sheet, row_idx, meal_context, food_msg, is_retry=False):
    tk = event.reply_token
    user_id = event.source.user_id
    row_data = sheet.row_values(row_idx)
    family = row_data[2] if len(row_data) > 2 else "不明"
    dislike = row_data[3] if len(row_data) > 3 else "なし"

    retry_text = "別の切り口で" if is_retry else ""
    send_reply(tk, f"{retry_text}レシピを考えています。少々お待ちを！🍳")

    try:
        prompt = f"""
        プロの料理研究家として、{family}向けの{meal_context}を提案してください。
        食材: {food_msg}
        禁止食材: {dislike}
        {'※先ほどとは別の料理を提案してください。' if is_retry else ''}
        
        【条件】
        - 実在するレシピURLを必ず1つ。
        - 時短テクを1つ。
        - ダジャレや遊び心は不要。真面目に冷蔵庫の食材を活かす提案をしてください。
        """
        response = model.generate_content(prompt)
        
        # 提案の後に「別のレシピ」ボタンを出す
        quick_reply = QuickReply(items=[
            QuickReplyItem(action=PostbackAction(label="他のレシピも見る", data="step=retry")),
            QuickReplyItem(action=PostbackAction(label="別の食材にする", data="meal=dinner")) # 再度時間選択から
        ])
        
        with ApiClient(conf) as api_client:
            line_api = MessagingApi(api_client)
            line_api.push_message(PushMessageRequest(
                to=user_id, 
                messages=[TextMessage(text=response.text, quick_reply=quick_reply)]
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

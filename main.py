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

    if msg in ["メニュー", "スタート"]:
        try:
            sheet = get_sheet()
            if sheet.find(user_id):
                show_meal_selection(tk)
            else:
                start_registration(user_id, tk)
        except:
            start_registration(user_id, tk)
    elif msg == "設定変更":
        start_registration(user_id, tk)
    elif user_id in user_temp_data and "pending_dislike" in user_temp_data[user_id]:
        register_new_user(event, msg)
    else:
        try:
            sheet = get_sheet()
            cell = sheet.find(user_id)
            if not cell:
                send_reply(tk, "まずは「メニュー」と送って登録してくださいね！")
            else:
                user_temp_data[f"{user_id}_last_food"] = msg
                handle_ai_generation(event, sheet, cell.row)
        except:
            send_reply(tk, "エラーが発生しました。設定を確認してください。")

def start_registration(user_id, tk):
    user_temp_data[user_id] = {"counts": {"男性": 0, "女性": 0, "お子様": 0, "ご年配": 0}}
    show_member_selector(tk, "男性")

def show_member_selector(tk, member_type):
    quick_reply = QuickReply(items=[
        QuickReplyItem(action=PostbackAction(label="0人", data=f"type={member_type}&num=0")),
        QuickReplyItem(action=PostbackAction(label="1人", data=f"type={member_type}&num=1")),
        QuickReplyItem(action=PostbackAction(label="2人", data=f"type={member_type}&num=2")),
        QuickReplyItem(action=PostbackAction(label="3人以上", data=f"type={member_type}&num=3"))
    ])
    send_reply(tk, f"【{member_type}】は何人いますか？", quick_reply)

@handler.add(PostbackEvent)
def handle_postback(event):
    data = event.postback.data
    tk = event.reply_token
    user_id = event.source.user_id
    params = dict(item.split('=') for item in data.split('&'))
    
    if "type" in params:
        m_type = params.get('type')
        num = params.get('num')
        if user_id not in user_temp_data: user_temp_data[user_id] = {"counts": {}}
        user_temp_data[user_id]["counts"][m_type] = num
        
        next_type = {"男性": "女性", "女性": "お子様", "お子様": "ご年配", "ご年配": "FIN"}.get(m_type)
        if next_type == "FIN":
            counts = user_temp_data[user_id]["counts"]
            summary = f"男性{counts['男性']}人、女性{counts['女性']}人、子{counts['お子様']}人、年配{counts['ご年配']}人"
            user_temp_data[user_id]["family_summary"] = summary
            user_temp_data[user_id]["pending_dislike"] = True
            send_reply(tk, f"構成：{summary}\n\n次に【アレルギーや苦手なもの】を教えてください。")
        else:
            show_member_selector(tk, next_type)

    elif params.get('step') == "reset_meal":
        show_meal_selection(tk)
    elif params.get('meal'):
        meal_type = {"morning": "朝ごはん", "lunch": "昼ごはん", "dinner": "夜ごはん"}.get(params.get('meal'))
        user_temp_data[f"{user_id}_meal"] = meal_type
        show_genre_selection(tk, meal_type)
    elif params.get('genre'):
        user_temp_data[f"{user_id}_genre"] = params.get('genre')
        quick_reply = QuickReply(items=[QuickReplyItem(action=PostbackAction(label="ジャンルを選び直す", data="meal_retry_step=1"))])
        send_reply(tk, f"{params.get('genre')}ですね！食材を教えてください🍳", quick_reply)
    elif params.get('meal_retry_step'):
        show_genre_selection(tk, user_temp_data.get(f"{user_id}_meal", "夜ごはん"))
    elif params.get('step') == "retry":
        try:
            sheet = get_sheet()
            cell = sheet.find(user_id)
            handle_ai_generation(event, sheet, cell.row, is_retry=True)
        except:
            send_reply(tk, "食材を教えてください！")

def show_meal_selection(tk):
    quick_reply = QuickReply(items=[
        QuickReplyItem(action=PostbackAction(label="朝ごはん ☀️", data="meal=morning")),
        QuickReplyItem(action=PostbackAction(label="昼ごはん 🕛", data="meal=lunch")),
        QuickReplyItem(action=PostbackAction(label="夜ごはん 🌙", data="meal=dinner"))
    ])
    send_reply(tk, "今日のごはんは何にしましょうか？✨", quick_reply)

def show_genre_selection(tk, meal_type):
    quick_reply = QuickReply(items=[
        QuickReplyItem(action=PostbackAction(label="和風 🍱", data="genre=和風")),
        QuickReplyItem(action=PostbackAction(label="洋風 🍝", data="genre=洋風")),
        QuickReplyItem(action=PostbackAction(label="中華・韓国 🥟", data="genre=中華")),
        QuickReplyItem(action=PostbackAction(label="お任せ 🤝", data="genre=お任せ")),
        QuickReplyItem(action=PostbackAction(label="←戻る", data="step=reset_meal"))
    ])
    send_reply(tk, f"{meal_type}ですね！ジャンルはどうしますか？", quick_reply)

def register_new_user(event, dislike_msg):
    user_id = event.source.user_id
    summary = user_temp_data[user_id]["family_summary"]
    user_temp_data.pop(user_id)
    try:
        sheet = get_sheet()
        cell = sheet.find(user_id)
        if cell:
            sheet.update_cell(cell.row, 3, summary); sheet.update_cell(cell.row, 4, dislike_msg)
        else:
            sheet.append_row([user_id, "ユーザー", summary, dislike_msg, "Free", datetime.date.today().strftime("%Y/%m/%d")])
        show_meal_selection(event.reply_token)
    except:
        send_reply(event.reply_token, "登録エラーです。")

def handle_ai_generation(event, sheet, row_idx, is_retry=False):
    tk = event.reply_token
    user_id = event.source.user_id
    row_data = sheet.row_values(row_idx)
    family = row_data[2] if len(row_data) > 2 else "不明"
    dislike = row_data[3] if len(row_data) > 3 else "なし"
    food_msg = user_temp_data.get(f"{user_id}_last_food", "あるもの")
    meal_type = user_temp_data.get(f"{user_id}_meal", "夜ごはん")
    genre = user_temp_data.get(f"{user_id}_genre", "お任せ")

    send_reply(tk, f"【{family}】向けのレシピを考えています🍳")

    try:
        prompt = f"""
        あなたは家族の健康を守る料理研究家です。以下の条件で献立を提案してください。
        構成: {family} / 時間: {meal_type} / ジャンル: {genre} / 食材: {food_msg}
        アレルギー・苦手: {dislike}
        {'※前回とは別の料理で。' if is_retry else ''}

        【必須項目】
        1. メイン献立名と簡単な手順
        2. 実在する大手レシピサイト(クックパッド等)のURLを1つ
        3. 時短テクニック
        
        【店長こだわり配慮（超重要）】
        - アレルギー食材(特に牛乳、卵、小麦等)が使えない場合：
          必ず「牛乳を豆乳に」「小麦粉を米粉に」といった、料理研究家ならではの具体的な【代用食材とそのコツ】を分かりやすく提案してください。
        - お子様がいる場合：
          同じ食材で野菜が苦手な子も食べられる工夫（刻む、味付けを変える等）を添えてください。
        - 年配の方がいる場合：
          喉越しの良さや柔らかく仕上げる工夫を添えてください。
        """
        response = model.generate_content(prompt)
        quick_reply = QuickReply(items=[
            QuickReplyItem(action=PostbackAction(label="別のレシピを見る", data="step=retry")),
            QuickReplyItem(action=PostbackAction(label="最初からやり直す", data="step=reset_meal"))
        ])
        with ApiClient(conf) as api_client:
            line_api = MessagingApi(api_client)
            line_api.push_message(PushMessageRequest(to=user_id, messages=[TextMessage(text=response.text, quick_reply=quick_reply)]))
    except Exception as e:
        print(f"AI Error: {e}")

def send_reply(tk, text, quick_reply=None):
    with ApiClient(conf) as api_client:
        line_api = MessagingApi(api_client)
        line_api.reply_message(ReplyMessageRequest(reply_token=tk, messages=[TextMessage(text=text, quick_reply=quick_reply)]))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

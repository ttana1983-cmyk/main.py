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
    msg, tk, u_id = event.message.text, event.reply_token, event.source.user_id

    if msg in ["メニュー", "スタート"]:
        try:
            sheet = get_sheet()
            if sheet.find(u_id): show_meal_selection(tk)
            else: start_registration(u_id, tk)
        except: start_registration(u_id, tk)
    elif msg == "設定変更":
        start_registration(u_id, tk, is_edit=True)
    elif u_id in user_temp_data and user_temp_data[u_id].get("step") == "waiting_allergy":
        user_temp_data[u_id].update({"allergy": msg, "step": "waiting_dislike"})
        send_reply(tk, "次に【苦手なもの】を教えてください。")
    elif u_id in user_temp_data and user_temp_data[u_id].get("step") == "waiting_dislike":
        register_new_user(event, msg)
    else:
        handle_free_consultation(event)

def start_registration(u_id, tk, is_edit=False):
    user_temp_data[u_id] = {"counts": {"男性": 0, "女性": 0, "お子様": 0, "ご年配": 0}, "is_edit": is_edit}
    show_member_selector(tk, "男性", is_edit)

def show_member_selector(tk, member_type, is_edit=False):
    items = [QuickReplyItem(action=PostbackAction(label=f"{i}人", data=f"type={member_type}&num={i}")) for i in range(4)]
    if is_edit: items.append(QuickReplyItem(action=PostbackAction(label="中止 ✖", data="step=reset_meal")))
    send_reply(tk, f"【{member_type}】は何人いますか？", QuickReply(items=items))

@handler.add(PostbackEvent)
def handle_postback(event):
    data, tk, u_id = event.postback.data, event.reply_token, event.source.user_id
    params = dict(item.split('=') for item in data.split('&'))
    
    if "type" in params:
        m_type, num = params.get('type'), params.get('num')
        if u_id not in user_temp_data: user_temp_data[u_id] = {"counts": {}}
        user_temp_data[u_id]["counts"][m_type] = num
        next_type = {"男性": "女性", "女性": "お子様", "お子様": "ご年配", "ご年配": "FIN"}.get(m_type)
        if next_type == "FIN":
            c = user_temp_data[u_id]["counts"]
            summary = f"男性{c['男性']}人、女性{c['女性']}人、子{c['お子様']}人、年配{c['ご年配']}人"
            user_temp_data[u_id].update({"family_summary": summary, "step": "waiting_allergy"})
            send_reply(tk, f"構成：{summary}\n次に【アレルギー食材】を教えてください。")
        else:
            show_member_selector(tk, next_type, user_temp_data[u_id].get("is_edit"))
    elif params.get('step') == "reset_meal":
        user_temp_data.pop(u_id, None)
        show_meal_selection(tk)
    elif params.get('step') == "edit_force":
        start_registration(u_id, tk, is_edit=True)
    elif params.get('step') == "ask_question":
        send_reply(tk, "レシピの不明点や、代わりの食材など何でも聞いてくださいね！そのままメッセージを送ってください💬")
    elif params.get('meal'):
        user_temp_data[f"{u_id}_meal"] = {"morning": "朝ごはん", "lunch": "昼ごはん", "dinner": "夜ごはん"}.get(params.get('meal'))
        show_genre_selection(tk, user_temp_data[f"{u_id}_meal"])
    elif params.get('genre'):
        user_temp_data[f"{u_id}_genre"] = params.get('genre')
        send_reply(tk, f"{params.get('genre')}ですね！食材を教えてください🍳")
    elif params.get('step') == "retry":
        try:
            sheet = get_sheet(); cell = sheet.find(u_id); handle_ai_generation(event, sheet, cell.row, is_retry=True)
        except: send_reply(tk, "食材を教えてください！")

def show_meal_selection(tk):
    qr = QuickReply(items=[
        QuickReplyItem(action=PostbackAction(label="朝ごはん ☀️", data="meal=morning")),
        QuickReplyItem(action=PostbackAction(label="昼ごはん 🕛", data="meal=lunch")),
        QuickReplyItem(action=PostbackAction(label="夜ごはん 🌙", data="meal=dinner")),
        QuickReplyItem(action=PostbackAction(label="登録内容変更 ⚙️", data="step=edit_force"))
    ])
    send_reply(tk, "今日のごはんは何にしましょうか？✨\n（食材や質問を送ってもOK！）", qr)

def show_genre_selection(tk, meal_type):
    qr = QuickReply(items=[
        QuickReplyItem(action=PostbackAction(label="和風 🍱", data="genre=和風")),
        QuickReplyItem(action=PostbackAction(label="洋風 🍝", data="genre=洋風")),
        QuickReplyItem(action=PostbackAction(label="中華 🥟", data="genre=中華")),
        QuickReplyItem(action=PostbackAction(label="お任せ 🤝", data="genre=お任せ")),
        QuickReplyItem(action=PostbackAction(label="←戻る", data="step=reset_meal"))
    ])
    send_reply(tk, f"{meal_type}ですね！気分を教えてください。", qr)

def register_new_user(event, dislike_msg):
    u_id = event.source.user_id
    summary, allergy = user_temp_data[u_id]["family_summary"], user_temp_data[u_id]["allergy"]
    user_temp_data.pop(u_id)
    try:
        sheet = get_sheet(); cell = sheet.find(u_id)
        if cell:
            sheet.update_cell(cell.row, 3, summary); sheet.update_cell(cell.row, 4, allergy); sheet.update_cell(cell.row, 5, dislike_msg)
            msg = "設定を更新しました！"
        else:
            sheet.append_row([u_id, "ユーザー", summary, allergy, dislike_msg, "Free", datetime.date.today().strftime("%Y/%m/%d")])
            msg = "ご登録ありがとうございます！"
        send_reply(event.reply_token, f"{msg}\n構成：{summary}"); show_meal_selection(event.reply_token)
    except: send_reply(event.reply_token, "通信エラーが発生しました。")

def handle_free_consultation(event):
    msg, u_id, tk = event.message.text, event.source.user_id, event.reply_token
    judge_prompt = f"「食材名(A)」か「質問・会話(B)」か判断してAかBを回答：{msg}"
    judgement = model.generate_content(judge_prompt).text.strip()
    try:
        sheet = get_sheet(); cell = sheet.find(u_id)
        if "A" in judgement:
            user_temp_data[f"{u_id}_last_food"] = msg
            handle_ai_generation(event, sheet, cell.row)
        else:
            send_reply(tk, "プロのアドバイザーがお答えします...📝")
            row = sheet.row_values(cell.row)
            fam = row[2] if len(row) > 2 else "不明"
            res = model.generate_content(f"あなたは家事のプロ「カジラク知恵袋」です。家族構成{fam}。回答して：{msg}")
            qr = QuickReply(items=[QuickReplyItem(action=PostbackAction(label="献立を考える 🍳", data="step=reset_meal"))])
            with ApiClient(conf) as c:
                MessagingApi(c).push_message(PushMessageRequest(to=u_id, messages=[TextMessage(text=res.text, quick_reply=qr)]))
    except: send_reply(tk, "もう一度お願いします。")

def handle_ai_generation(event, sheet, row_idx, is_retry=False):
    tk, u_id = event.reply_token, event.source.user_id
    row = sheet.row_values(row_idx)
    fam, alg, dsl = row[2], row[3], row[4]
    food = user_temp_data.get(f"{u_id}_last_food", "あるもの")
    meal, gen = user_temp_data.get(f"{u_id}_meal", "夜ごはん"), user_temp_data.get(f"{u_id}_genre", "お任せ")
    send_reply(tk, f"【{fam}】向けのレシピを考え中...🍳")
    try:
        prompt = f"""料理研究家として、家族構成{fam}向けに{meal}({gen})を提案。食材:{food}、アレルギー:{alg}、苦手:{dsl}。
        【絶対ルール】
        1. 手順の中で、お子様やご年配向けの「取り分け・味付け変更」のタイミングを具体的に組み込むこと（例：味付け前に子供分を取り出す等）。
        2. 手順の途中で「ここで子供用を取り分けて、大人は生姜を入れます」のように書くこと。最後に書くのはNG。
        3. 他のお肉代用案、実在URL、時短テクも親身な口調で。"""
        res = model.generate_content(prompt)
        qr = QuickReply(items=[
            QuickReplyItem(action=PostbackAction(label="このレシピに質問！ 🙋", data="step=ask_question")),
            QuickReplyItem(action=PostbackAction(label="別のレシピ", data="step=retry")),
            QuickReplyItem(action=PostbackAction(label="最初から", data="step=reset_meal"))
        ])
        with ApiClient(conf) as c:
            MessagingApi(c).push_message(PushMessageRequest(to=u_id, messages=[TextMessage(text=res.text, quick_reply=qr)]))
    except Exception as e: print(f"AI Error: {e}")

def send_reply(tk, text, quick_reply=None):
    with ApiClient(conf) as c:
        MessagingApi(c).reply_message(ReplyMessageRequest(reply_token=tk, messages=[TextMessage(text=text, quick_reply=quick_reply)]))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

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
model = genai.GenerativeModel('gemini-1.5-flash') # 最新モデル推奨

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
            sheet = get_sheet(); cell = sheet.find(u_id)
            if cell: show_meal_selection(tk)
            else: start_registration(u_id, tk)
        except: start_registration(u_id, tk)
    elif msg == "設定変更":
        start_registration(u_id, tk, is_edit=True)
    elif u_id in user_temp_data and user_temp_data[u_id].get("step") == "waiting_free_input":
        # 自由入力が必要な場合の処理（予備）
        register_new_user(event, msg)
    else:
        handle_free_consultation(event)

# --- 登録フロー (やり取りを最小限にするロジック) ---
def start_registration(u_id, tk, is_edit=False):
    # 初期値はすべて0。選ばれなければそのまま。
    user_temp_data[u_id] = {
        "counts": {"男性": 0, "女性": 0, "お子様": 0, "ご年配": 0},
        "child_detail": "",
        "ng_items": [],
        "is_edit": is_edit,
        "step": "member_select"
    }
    show_main_category_selector(tk)

def show_main_category_selector(tk):
    items = [
        QuickReplyItem(action=PostbackAction(label="男性 👨", data="select=男性")),
        QuickReplyItem(action=PostbackAction(label="女性 👩", data="select=女性")),
        QuickReplyItem(action=PostbackAction(label="お子様 👶", data="select=お子様")),
        QuickReplyItem(action=PostbackAction(label="ご年配 👵", data="select=ご年配")),
        QuickReplyItem(action=PostbackAction(label="選択完了 ✅", data="select=DONE"))
    ]
    send_reply(tk, "家族構成を選んでください（いない人はスルーでOK）", QuickReply(items=items))

@handler.add(PostbackEvent)
def handle_postback(event):
    data, tk, u_id = event.postback.data, event.reply_token, event.source.user_id
    params = dict(item.split('=') for item in data.split('&'))
    
    if u_id not in user_temp_data and "select" in params:
        user_temp_data[u_id] = {"counts": {"男性": 0, "女性": 0, "お子様": 0, "ご年配": 0}, "ng_items": []}

    # 1. 家族構成の深掘り
    if "select" in params:
        sel = params.get("select")
        if sel == "DONE":
            show_ng_selector(tk)
        elif sel == "お子様":
            items = [QuickReplyItem(action=PostbackAction(label=f"{i}人", data=f"child_num={i}")) for i in range(1, 4)]
            send_reply(tk, "お子様は何名ですか？", QuickReply(items=items))
        else:
            items = [QuickReplyItem(action=PostbackAction(label=f"{i}人", data=f"m_type={sel}&num={i}")) for i in range(1, 4)]
            send_reply(tk, f"{sel}は何名ですか？", QuickReply(items=items))

    elif "m_type" in params:
        user_temp_data[u_id]["counts"][params['m_type']] = params['num']
        show_main_category_selector(tk)

    elif "child_num" in params:
        user_temp_data[u_id]["counts"]["お子様"] = params['child_num']
        items = [
            QuickReplyItem(action=PostbackAction(label="離乳食", data="c_age=離乳食")),
            QuickReplyItem(action=PostbackAction(label="幼児食", data="c_age=幼児食")),
            QuickReplyItem(action=PostbackAction(label="小学生以上", data="c_age=小学生以上"))
        ]
        send_reply(tk, "お子様の成長段階は？", QuickReply(items=items))

    elif "c_age" in params:
        user_temp_data[u_id]["child_detail"] = params['c_age']
        show_main_category_selector(tk)

    # 2. NG食材・こだわりの設定
    elif "ng" in params:
        ng_type = params.get("ng")
        if ng_type == "DONE":
            register_new_user(event, "特になし")
        elif ng_type == "生もの":
            items = [
                QuickReplyItem(action=PostbackAction(label="マグロならOK", data="exc=マグロ")),
                QuickReplyItem(action=PostbackAction(label="サーモンならOK", data="exc=サーモン")),
                QuickReplyItem(action=PostbackAction(label="全てNG", data="exc=全てNG"))
            ]
            send_reply(tk, "生ものNGですね。例外はありますか？", QuickReply(items=items))
        else:
            user_temp_data[u_id]["ng_items"].append(ng_type)
            show_ng_selector(tk)

    elif "exc" in params:
        if params['exc'] != "全てNG":
            user_profile = f"生ものNG(例外:{params['exc']})"
        else:
            user_profile = "生もの完全NG"
        user_temp_data[u_id]["ng_items"].append(user_profile)
        show_ng_selector(tk)

    # 3. 献立・その他
    elif params.get('step') == "reset_meal":
        user_temp_data.pop(u_id, None); show_meal_selection(tk)
    elif params.get('meal'):
        user_temp_data[f"{u_id}_meal"] = {"morning": "朝ごはん", "lunch": "昼ごはん", "dinner": "夜ごはん"}.get(params.get('meal'))
        show_genre_selection(tk, user_temp_data[f"{u_id}_meal"])
    elif params.get('genre'):
        user_temp_data[f"{u_id}_genre"] = params.get('genre')
        send_reply(tk, f"{params.get('genre')}ですね！使いたい食材を教えてください🍳")
    elif params.get('step') == "retry":
        try:
            sheet = get_sheet(); cell = sheet.find(u_id); handle_ai_generation(event, sheet, cell.row, is_retry=True)
        except: send_reply(tk, "もう一度、使いたい食材を教えてください！")

def show_ng_selector(tk):
    items = [
        QuickReplyItem(action=PostbackAction(label="生もの(刺身等)NG", data="ng=生もの")),
        QuickReplyItem(action=PostbackAction(label="スパイス(八角等)NG", data="ng=スパイス")),
        QuickReplyItem(action=PostbackAction(label="強い酸味NG", data="ng=酸味")),
        QuickReplyItem(action=PostbackAction(label="アレルギー・その他", data="ng=OTHER")),
        QuickReplyItem(action=PostbackAction(label="登録完了 ✅", data="ng=DONE"))
    ]
    send_reply(tk, "苦手なものやアレルギーはありますか？（2段で表示中）", QuickReply(items=items))

def show_meal_selection(tk):
    qr = QuickReply(items=[
        QuickReplyItem(action=PostbackAction(label="朝ごはん ☀️", data="meal=morning")),
        QuickReplyItem(action=PostbackAction(label="昼ごはん 🕛", data="meal=lunch")),
        QuickReplyItem(action=PostbackAction(label="夜ごはん 🌙", data="meal=dinner")),
        QuickReplyItem(action=PostbackAction(label="設定変更 ⚙️", data="step=edit_force"))
    ])
    send_reply(tk, "今日のごはんは何にしましょうか？✨\n（1日5回までご利用いただけます）", qr)

def show_genre_selection(tk, meal_type):
    qr = QuickReply(items=[
        QuickReplyItem(action=PostbackAction(label="和風 🍱", data="genre=和風")),
        QuickReplyItem(action=PostbackAction(label="洋風 🍝", data="genre=洋風")),
        QuickReplyItem(action=PostbackAction(label="中華 🥟", data="genre=中華")),
        QuickReplyItem(action=PostbackAction(label="お任せ 🤝", data="genre=お任せ"))
    ])
    send_reply(tk, f"{meal_type}ですね！気分はどうですか？", qr)

def register_new_user(event, other_msg):
    u_id = event.source.user_id; data = user_temp_data[u_id]
    c = data["counts"]
    summary = f"男{c['男性']}女{c['女性']}子{c['お子様']}({data['child_detail']})年{c['ご年配']}"
    ng_list = ",".join(data["ng_items"]) + f" その他:{other_msg}"
    user_temp_data.pop(u_id)
    try:
        sheet = get_sheet(); cell = sheet.find(u_id)
        if cell:
            sheet.update_cell(cell.row, 3, summary); sheet.update_cell(cell.row, 4, ng_list)
        else:
            sheet.append_row([u_id, "ユーザー", summary, ng_list, "", "Free", datetime.date.today().strftime("%Y/%m/%d")])
        send_reply(event.reply_token, f"登録完了しました！\n構成：{summary}\n制限：{ng_list}"); show_meal_selection(event.reply_token)
    except: send_reply(event.reply_token, "通信エラーです。")

def handle_ai_generation(event, sheet, row_idx, is_retry=False):
    tk, u_id = event.reply_token, event.source.user_id
    row = sheet.row_values(row_idx); fam, ng_all = row[2], row[3]
    food = user_temp_data.get(f"{u_id}_last_food", "あるもの")
    meal = user_temp_data.get(f"{u_id}_meal", "夜ごはん")
    gen = user_temp_data.get(f"{u_id}_genre", "お任せ")
    
    send_reply(tk, f"【{fam}】向けのレシピを考え中...🍳")
    
    try:
        prompt = f"""料理研究家「カジラク知恵袋」として提案。
        構成:{fam} / 時間:{meal} / ジャンル:{gen} / 食材:{food} / 制限:{ng_all}。

        【重要ルール】
        1. 調理前に「包丁・まな板・トング・食器」を煮沸やアルコールで必ず【殺菌】するよう冒頭で伝えて。
        2. 低温調理を出す際は「63度で30分以上」など具体的な数値を文字化け（LaTeX等）させずプレーンテキストで書いて。
        3. 法律で生食が禁じられている食材（豚レバー等）は絶対に生で提案しないこと。
        4. 「生ものNG」でも【煮魚・焼き魚】は生ではないので提案してOK。
        5. スパイスや酸味NG設定がある場合、八角や花椒、強い酢を避け和風等にアレンジして。
        6. 再提案時は、同じメイン食材で違う調理法（例：低温調理→完全加熱）にして。
        7. URLは載せず、このメッセージだけで手順を完結させて。"""
        
        res = model.generate_content(prompt); footer = "\n\n※自己責任で安全に調理してください。"
        qr = QuickReply(items=[
            QuickReplyItem(action=PostbackAction(label="別のレシピ(同じ食材)", data="step=retry")),
            QuickReplyItem(action=PostbackAction(label="最初から", data="step=reset_meal"))
        ])
        with ApiClient(conf) as c: MessagingApi(c).push_message(PushMessageRequest(to=u_id, messages=[TextMessage(text=res.text + footer, quick_reply=qr)]))
    except Exception as e: print(f"AI Error: {e}")

def send_reply(tk, text, quick_reply=None):
    with ApiClient(conf) as c: MessagingApi(c).reply_message(ReplyMessageRequest(reply_token=tk, messages=[TextMessage(text=text, quick_reply=quick_reply)]))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

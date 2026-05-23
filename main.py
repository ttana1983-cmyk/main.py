import os
import json
import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from flask import Flask, request, abort
from linebot.v3 import WebhookHandler
from linebot.v3.messaging import Configuration, ApiClient, MessagingApi, ReplyMessageRequest, TextMessage, QuickReply, QuickReplyItem, PostbackAction, PushMessageRequest
from linebot.v3.webhooks import MessageEvent, TextMessageContent, PostbackEvent
import google.generativeai as genai

app = Flask(__name__)

# --- 設定 ---
conf = Configuration(access_token=os.environ["LINE_CHANNEL_ACCESS_TOKEN"])
handler = WebhookHandler(os.environ["LINE_CHANNEL_SECRET"])
genai.configure(api_key=os.environ["GEMINI_API_KEY"])
model = genai.GenerativeModel('gemini-3.5-flash')

# Google Sheets 連携
def get_sheet():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds_dict = json.loads(os.environ["GOOGLE_CREDENTIALS_JSON"])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    return client.open_by_key(os.environ["SPREADSHEET_ID"]).sheet1

# --- 1. メッセージ受付 ---
@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    msg = event.message.text
    tk = event.reply_token
    user_id = event.source.user_id

    if msg in ["メニュー", "スタート", "設定変更"]:
        show_family_selection(tk)
    else:
        # 食材入力。まずシートにユーザーがいるか確認
        try:
            sheet = get_sheet()
            cell = sheet.find(user_id)
            if not cell:
                # 未登録なら登録へ誘導
                send_reply(tk, "まずは「メニュー」と送って、家族構成などを教えてくださいね！")
            else:
                # 登録済みならレシピ生成へ
                handle_ai_generation(event, sheet, cell.row)
        except Exception as e:
            send_reply(tk, "ごめんなさい、ちょっと調子が悪いみたいです。後でもう一度試してみてね！")

# 家族構成選択
def show_family_selection(tk):
    quick_reply = QuickReply(items=[
        QuickReplyItem(action=PostbackAction(label="1人暮らし", data="step=dislike&family=1人")),
        QuickReplyItem(action=PostbackAction(label="2人", data="step=dislike&family=2人")),
        QuickReplyItem(action=PostbackAction(label="3人", data="step=dislike&family=3人")),
        QuickReplyItem(action=PostbackAction(label="4人以上", data="step=dislike&family=4人以上"))
    ])
    send_reply(tk, "何人分のごはんを作ることが多いですか？👪", quick_reply)

# --- 2. 顧客情報の保存（アレルギー入力） ---
@handler.add(PostbackEvent)
def handle_postback(event):
    data = event.postback.data
    tk = event.reply_token
    params = dict(item.split('=') for item in data.split('&'))
    
    if params.get('step') == "dislike":
        # 簡易的に、次に「アレルギー：卵」のように打ってもらう形にします
        # ※本来は入力待ち状態を作りますが、今回は流れを優先
        send_reply(tk, f"{params.get('family')}分ですね！\n\n最後に【苦手なもの・アレルギー】を教えてください。\n例：「なし」「卵とピーマン」など\n\n※この入力が終わると、次から食材を送るだけでOKになります！")

# --- 3. AI生成（シートの情報をプロンプトに注入） ---
def handle_ai_generation(event, sheet, row_idx):
    user_id = event.source.user_id
    msg = event.message.text
    tk = event.reply_token

    # シートから情報を取得 (A:ID, B:名前, C:家族, D:苦手, E:ランク)
    row_data = sheet.row_values(row_idx)
    family = row_data[2] if len(row_data) > 2 else "不明"
    dislike = row_data[3] if len(row_data) > 3 else "特になし"

    send_reply(tk, "情報を確認しました！ピッタリのレシピを考えてくるので、少しお待ちください。🍳")

    try:
        prompt = f"""
        あなたはプロの料理研究家です。以下の顧客データを踏まえて回答してください。
        
        【顧客データ】
        - 家族構成: {family}
        - 苦手・アレルギー: {dislike}
        
        【今回のリクエスト】
        食材: {msg}
        
        【指示】
        - {family}に適した分量で。
        - {dislike}は絶対に使用しない。
        - 実在するレシピURLを必ず1つ。
        - 家事を楽にするコツを1つ。
        """
        response = model.generate_content(prompt)
        
        with ApiClient(conf) as api_client:
            line_api = MessagingApi(api_client)
            line_api.push_message(PushMessageRequest(
                to=user_id, messages=[TextMessage(text=response.text)]
            ))
    except Exception as e:
        print(f"Error: {e}")

def send_reply(tk, text, quick_reply=None):
    with ApiClient(conf) as api_client:
        line_api = MessagingApi(api_client)
        line_api.reply_message(ReplyMessageRequest(
            reply_token=tk, messages=[TextMessage(text=text, quick_reply=quick_reply)]
        ))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

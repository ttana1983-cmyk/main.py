import os
import sys
import json
import google.genai as genai
from flask import Flask, request, abort, render_template, jsonify
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi, ReplyMessageRequest,
    TextMessage, QuickReply, QuickReplyItem, URIAction
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent

app = Flask(__name__)

# --- 環境設定 ---
channel_secret = os.getenv('LINE_CHANNEL_SECRET')
channel_access_token = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
gemini_api_key = os.getenv('GEMINI_API_KEY')

# Geminiの初期設定 (新しいSDK版)
client = genai.Client(api_key=gemini_api_key)
model_id = 'gemini-1.5-flash'

configuration = Configuration(access_token=channel_access_token)
handler = WebhookHandler(channel_secret)

# --- 1. LIFF表示用 ---
@app.route("/")
def index():
    return render_template("index.html")

# --- 2. AIレシピ生成 (LIFF側から呼び出される) ---
@app.route("/api/generate-recipe")
def generate_recipe():
    query = request.args.get('query', 'おまかせ')
    
    prompt = f"""
    あなたは家事の負担を減らす「カジラク・コンシェルジュ」です。
    ユーザーの要望: 「{query}」に基づき、15分以内の節約レシピを提案してください。
    回答は必ず以下のJSON形式のみとし、他の文章は一切含めないでください。
    {{
      "name": "料理名",
      "time": "〇分",
      "cost": "約〇円",
      "main": "食材",
      "tip": "時短コツ",
      "ingredients": [{{"name": "食材1", "amount": "分量"}}],
      "steps": ["1. 〇〇する", "2. 〇〇する"]
    }}
    """

    try:
        response = client.models.generate_content(model=model_id, contents=prompt)
        clean_text = response.text.replace('```json', '').replace('```', '').strip()
        return jsonify(json.loads(clean_text))
    except Exception as e:
        print(f"AI Error: {e}")
        return jsonify({"name": "エラー", "steps": ["もう一度お試しください"]})

# --- 3. LINE Webhookの入り口 ---
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['x-line-signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

# --- 4. LINEメッセージ受信（ここが改善ポイント！） ---
@handler.add(MessageEvent, content_type=TextMessageContent)
def handle_message(event):
    tk = event.reply_token
    # 重たい処理はせず、即座に誘導ボタンを返す（これで期限切れを防ぐ）
    handle_recipe_induction(event, tk)

# --- 5. 即レス・LIFF誘導ロジック ---
def handle_recipe_induction(event, tk):
    # 店長のLIFF URL
    base_url = "https://liff.line.me/2010225388-rXh2LiOR"
    target_url = f"{base_url}?query={event.message.text}"
    
    msg = "カジラク・コンシェルジュが献立を考えています。\n準備ができたら、下のボタンからレシピを確認してくださいね！"
    
    # 確実に踏んでもらうための「URIAction」
    quick_reply = QuickReply(items=[
        QuickReplyItem(
            action=URIAction(label="🍳 レシピを確認する", uri=target_url)
        )
    ])
    
    send_reply(tk, msg, quick_reply=quick_reply)

# --- 6. 返信用共通関数 ---
def send_reply(tk, text, quick_reply=None):
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(ReplyMessageRequest(
            reply_token=tk,
            messages=[TextMessage(text=text, quick_reply=quick_reply)]
        ))

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)

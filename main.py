import os
import sys
from flask import Flask, request, abort

# 最新のLINE SDK v3系を想定した書き方に微調整
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi, 
    ReplyMessageRequest, TextMessage, ImageMessage
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent

import google.generativeai as genai

app = Flask(__name__)

# --- 設定 ---
# Renderの環境変数から取得
access_token = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
channel_secret = os.environ["LINE_CHANNEL_SECRET"]

configuration = Configuration(access_token=access_token)
handler = WebhookHandler(channel_secret)

genai.configure(api_key=os.environ["GEMINI_API_KEY"])
model = genai.GenerativeModel("gemini-2.5-flash")

GIF_URL = "https://raw.githubusercontent.com/ttana1983-cmyk/main.py/main/chef.gif"

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
    
    # 挨拶系はスルーして、食材の時だけ動く
    if msg not in ["メニュー", "最初から", "⚙️再設定"]:
        try:
            # プロンプト（トリプルクォート維持）
            prompt = f"""
あなたは元ラーメン店長の献立アドバイザーです。
食材「{msg}」を使った、プロ直伝の献立を1つ提案してください。

【厳格なルール】
1. 実在するレシピURL（クックパッド等）を特定して載せること。
2. 300文字以内で、職人気質な口調で。
"""
            response = model.generate_content(prompt)
            recipe_text = response.text

            # メッセージを最新の形式で組み立て
            with ApiClient(configuration) as api_client:
                line_bot_api = MessagingApi(api_client)
                
                # 3通のメッセージを配列にする
                line_bot_api.reply_message_with_http_info(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[
                            TextMessage(text="オーダー入りました！ねこシェフ調理中...🐾"),
                            ImageMessage(original_content_url=GIF_URL, preview_image_url=GIF_URL),
                            TextMessage(text=f"完成だ！✨\n\n{recipe_text}")
                        ]
                    )
                )
        except Exception as e:
            print(f"Error: {e}")
            # エラー時も返信を試みる
            with ApiClient(configuration) as api_client:
                line_bot_api = MessagingApi(api_client)
                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=f"わりぃ、エラーだ：{str(e)[:50]}")]
                    )
                )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

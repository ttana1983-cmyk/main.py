import os
from flask import Flask, request, abort
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi, 
    ReplyMessageRequest, TextMessage, ImageMessage
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent
from google import genai

app = Flask(__name__)

# 設定
access_token = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
channel_secret = os.environ["LINE_CHANNEL_SECRET"]
configuration = Configuration(access_token=access_token)
handler = WebhookHandler(channel_secret)

# 最新AIクライアント
client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

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
    tk = event.reply_token

    # フィルタリング
    if msg in ["メニュー", "最初から", "⚙️再設定"]:
        return

    try:
        # 指示を「正確性」と「URL」のみに絞り込み
        prompt = f"""
食材「{msg}」を使った献立を1つ提案してください。

【制約条件】
・300文字以内。
・箇条書きなどで簡潔に説明すること。
・最後に必ず、その料理の実在するレシピURL（クックパッド等）を載せること。
・URLが有効であることを確認してください。
"""
        # 最新かつ高速な2.0-flashを使用
        response = client.models.generate_content(
            model="gemini-2.5-flash", 
            contents=prompt
        )
        
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=tk,
                    messages=[
                        TextMessage(text="献立を作成しています..."),
                        ImageMessage(original_content_url=GIF_URL, preview_image_url=GIF_URL),
                        TextMessage(text=f"【提案】\n\n{response.text}")
                    ]
                )
            )
    except Exception as e:
        # エラーが発生した場合は詳細をLINEに送信して特定しやすくする
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=tk,
                    messages=[TextMessage(text=f"システムエラー: {str(e)}")]
                )
            )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

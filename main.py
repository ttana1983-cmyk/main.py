import os
import traceback
from flask import Flask, request, abort
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import Configuration, ApiClient, MessagingApi, ReplyMessageRequest, TextMessage
from linebot.v3.webhooks import MessageEvent, TextMessageContent
import google.generativeai as genai

app = Flask(__name__)

# --- 設定：環境変数から読み込み ---
conf = Configuration(access_token=os.environ["LINE_CHANNEL_ACCESS_TOKEN"])
handler = WebhookHandler(os.environ["LINE_CHANNEL_SECRET"])

# --- Gemini設定：ここを1.5-flashに完全固定 ---
genai.configure(api_key=os.environ["GEMINI_API_KEY"])
# 'gemini-1.5-flash' とだけ書くのが、今の安定版ライブラリで最も確実な指定方法です
model = genai.GenerativeModel('gemini-1.5-flash')

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

    try:
        # AIで献立を生成
        # モデル名を含めず、設定済みの model オブジェクトから生成します
        response = model.generate_content(f"食材「{msg}」の献立とURLを1つ教えて")
        ai_text = response.text

        with ApiClient(conf) as api_client:
            line_api = MessagingApi(api_client)
            line_api.reply_message(
                ReplyMessageRequest(
                    reply_token=tk,
                    messages=[TextMessage(text=ai_text)]
                )
            )
            
    except Exception as e:
        # エラーが起きたらログに出す
        print("--- ERROR LOG START ---")
        print(traceback.format_exc())
        print("--- ERROR LOG END ---")
        
        with ApiClient(conf) as api_client:
            line_api = MessagingApi(api_client)
            line_api.reply_message(
                ReplyMessageRequest(
                    reply_token=tk,
                    messages=[TextMessage(text="ただいま献立を考え中です。もう一度食材を送ってみてください。")]
                )
            )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

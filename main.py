import os
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage, ImageSendMessage
)
import google.generativeai as genai

app = Flask(__name__)

# --- 設定 ---
line_bot_api = LineBotApi(os.environ["LINE_CHANNEL_ACCESS_TOKEN"])
handler = WebhookHandler(os.environ["LINE_CHANNEL_SECRET"])
genai.configure(api_key=os.environ["GEMINI_API_KEY"])

# Takashiさん指定の2.5モデル
model = genai.GenerativeModel("gemini-2.5-flash")

# 画像URL（一旦今のものをセットしますが、ダメならここを空にするか別のURLに変えればOK）
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

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    msg = event.message.text
    uid = event.source.user_id

    # 挨拶や再設定以外の「食材入力」の時だけレシピを作る
    if msg not in ["メニュー", "最初から", "⚙️再設定"]:
        # 1. まずは「受け付けた」ことを即座に伝える
        line_bot_api.push_message(uid, TextSendMessage(text="オーダー入りました！ねこシェフ調理中...🐾"))
        
        # 2. 画像送信（失敗しても無視して次に進む設定）
        try:
            line_bot_api.push_message(uid, ImageSendMessage(
                original_content_url=GIF_URL,
                preview_image_url=GIF_URL
            ))
        except Exception as e:
            print(f"Image Error: {e}") # ログには出すが、LINE側ではエラーにしない

        # 3. AIレシピ生成（ここが本番）
        try:
            prompt = (
                f"あなたは元ラーメン店長です。食材（{msg}）を使った献立を1つ提案してください。\n\n"
                "【重要】回答の最後に、その料理の作り方がわかる『実在する』レシピサイト（クックパッド等）のURLを必ず1つ添えてください。\n"
                "※嘘のリンクは絶対に載せないでください。350文字以内。"
            )
            response = model.generate_content(prompt)
            
            # 通知とレシピを送信
            line_bot_api.push_message(uid, TextSendMessage(text="🔔 ピーッ！＼ チン！ ／"))
            line_bot_api.push_message(uid, TextSendMessage(text=f"特製メニュー完成です！✨\n\n{response.text}"))
        except Exception as e:
            # AI側のエラー（制限など）が出た場合
            line_bot_api.push_message(uid, TextSendMessage(text=f"店長エラー: 休憩中かな？もう一度送ってみて！\n({str(e)[:30]})"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

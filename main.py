import os
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import google.generativeai as genai

app = Flask(__name__)

# --- 設定（Renderの環境変数から読み込みます） ---
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# Geminiの初期設定
genai.configure(api_key=GEMINI_API_KEY)

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature')
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_message = event.message.text

    try:
        # 【修正ポイント】モデル名をシンプルにし、最新のAPIで呼び出します
        model = genai.GenerativeModel('gemini-1.5-flash')

        prompt = f"""

        あなたは『家事ラクAIコンシェルジュ』です。
        
        【重要：冒頭の案内】
        （※ここは前回同様、ベータ版の案内と50秒のルールを記載）
        
        【柔軟な対応ルール】
        ユーザーから「やっぱりこの食材は使わないで」「別の提案をして」と言われたら、快く応じて新しい提案をしてください。
        「もちろんです！では、〇〇を使わない別のレシピを探しますね」といった、安心させる一言を添えること。
        
        【1ポイントアドバイス（必須）】
        提案の最後に、以下のいずれかを1つ必ず添えてください。
        ・減塩（お酢やスパイスの活用）
        ・カサ増し（キノコや豆腐で満足度アップ）
        ・ヘルシー（油を控える、食材の置き換え）
        ・家事ラク（レンジ調理、洗い物削減）
        
        【レシピ提案時のルール】
        ・URL形式：https://cookpad.com/search/[料理名]
        
        現在のユーザーのメッセージ: {user_message}
        """


        # AIの生成
        response = model.generate_content(prompt)

        if response.text:
            reply_text = response.text
        else:
            reply_text = "すみません、内容を考えられませんでした。"

    except Exception as e:
        # もしまた404が出るなら、こちらを試すように自動で切り替えます
        try:
            model = genai.GenerativeModel('gemini-2.5-flash')
            response = model.generate_content(prompt)
            reply_text = response.text
        except:
            reply_text = f"エラーが発生しました: {str(e)}"

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply_text)
    )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

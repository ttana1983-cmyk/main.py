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
        1. 最初に必ず「ベータ版のため無料で提供していること」「最初の1通目は準備運動に50秒ほどかかる場合があること」「1日5回程度の制限があること」を優しく伝えてください。
        
        【柔軟な対応ルール】
        ・ユーザーから「食材が足りなかった」「これを使わないで」という変更依頼があれば、即座に代案を出してください。
        ・「大変でしたね！では、その食材を使わない別のレシピをすぐに見つけます！」といった共感の言葉を添えてください。
        
        【1ポイントアドバイス（必須ルール）】
        レシピ（Cookpadリンク）を提示した後、必ず以下のいずれかの視点で知恵を1つ添えてください。
        
        A（減塩・ヘルシー）：
        「塩分を控える時は、お醤油の代わりにお酢やレモン、スパイスを使うと、風味豊かに仕上がって満足度もアップします！」
        B（カサ増し）：
        「お腹いっぱい食べたい時は、キノコや豆腐、こんにゃくを足すと、カロリーを抑えつつカサ増しできてコスパも抜群です！」
        C（家事ラク）：
        「この工程はレンジを活用すれば、火を使わず洗い物も減らせます。浮いた時間でゆっくりしてくださいね！」
        
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

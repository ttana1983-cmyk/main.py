import os, json, google.genai as genai
from flask import Flask, request, abort, render_template, jsonify
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi, ReplyMessageRequest,
    TextMessage, QuickReply, QuickReplyItem, MessageAction, URIAction
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent

app = Flask(__name__)

# 環境設定
conf = Configuration(access_token=os.getenv('LINE_CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.getenv('LINE_CHANNEL_SECRET'))
client = genai.Client(api_key=os.getenv('GEMINI_API_KEY'))

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/callback", methods=['POST'])
def callback():
    sig = request.headers.get('x-line-signature')
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, sig)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    txt = event.message.text
    tk = event.reply_token

    # 1. 時間帯の選択
    if txt in ["メニュー提案", "献立", "スタート"]:
        send(tk, "いつのご飯を作りましょうか？", ["朝ごはん", "昼ごはん", "夜ごはん"])

    # 2. ジャンルの選択
    elif txt in ["朝ごはん", "昼ごはん", "夜ごはん"]:
        send(tk, f"{txt}ですね！ジャンルはどうしますか？", 
             [f"{txt}/和風", f"{txt}/洋風", f"{txt}/中華", f"{txt}/お任せ"])

    # 3. 食材の入力（自由入力）
    elif "/" in txt:
        send(tk, f"【{txt}】で承りました。\n優先して使いたい食材を入力してください。\n（例：鶏肉、キャベツ、特になし）", None)

    # 4. 最終誘導
    else:
        # 食材名を受け取ってLIFFへ
        liff_url = f"https://liff.line.me/2010225388-rXh2LiOR?query={txt}"
        qr = QuickReply(items=[QuickReplyItem(action=URIAction(label="🍳 レシピを表示", uri=liff_url))])
        send(tk, f"「{txt}」を優先した特製レシピをご用意しました！\n下のボタンから確認して、画像を保存してくださいね。", None, qr)

def send(tk, msg, opts, qr=None):
    if opts:
        items = [QuickReplyItem(action=MessageAction(label=o.split('/')[-1], text=o)) for o in opts]
        qr = QuickReply(items=items)
    with ApiClient(conf) as api:
        line_api = MessagingApi(api)
        line_api.reply_message(ReplyMessageRequest(
            reply_token=tk,
            messages=[TextMessage(text=msg, quick_reply=qr)]
        ))

@app.route("/api/generate-recipe")
def generate():
    q = request.args.get('query', 'おまかせ')
    p = f"要望:{q}。15分節約レシピをJSONのみで。他の文章は不要。{{'name':'','time':'','cost':'','tip':'','ingredients':[{{'name':'','amount':''}}],'steps':[]}}"
    try:
        res = client.models.generate_content(model='gemini-1.5-flash', contents=p)
        clean = res.text.replace('```json', '').replace('```', '').strip()
        return jsonify(json.loads(clean))
    except:
        return jsonify({"name": "エラー", "steps": ["再試行してください"]})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))

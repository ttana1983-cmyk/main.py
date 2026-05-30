import os, json, threading, requests, google.genai as genai
from flask import Flask, request, abort, render_template, jsonify
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi, ReplyMessageRequest,
    TextMessage, QuickReply, QuickReplyItem, MessageAction, URIAction
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent

# --- 🚀 修正ポイント：templatesの場所を絶対に外さない設定 ---
# main.pyファイルがある場所を基準に templates フォルダを探すように強制します
base_dir = os.path.dirname(os.path.abspath(__file__))
template_dir = os.path.join(base_dir, 'templates')
app = Flask(__name__, template_folder=template_dir)

# 環境設定
conf = Configuration(access_token=os.getenv('LINE_CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.getenv('LINE_CHANNEL_SECRET'))
client = genai.Client(api_key=os.getenv('GEMINI_API_KEY'))

# Renderのスリープ対策（自分自身を叩く）
def wake_up_render():
    try:
        requests.get(f"https://{request.host}/", timeout=1)
    except:
        pass

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/callback", methods=['POST'])
def callback():
    sig = request.headers.get('x-line-signature')
    body = request.get_data(as_text=True)
    # ユーザーが接触した瞬間にスレッドでRenderを起こす
    threading.Thread(target=wake_up_render).start()
    try:
        handler.handle(body, sig)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    txt = event.message.text
    tk = event.reply_token

    # 1. 入り口
    if txt == "今日のレシピ提案":
        send_quick(tk, "カジラク・コンシェルジュです🍳\\nいつのご飯を考えましょうか？", ["朝ごはん", "昼ごはん", "夜ごはん"])

    # 2. 時間帯選択
    elif txt in ["朝ごはん", "昼ごはん", "夜ごはん"]:
        send_quick(tk, f"{txt}ですね！ジャンルはどうしますか？", 
                   [f"{txt}/和風", f"{txt}/洋風", f"{txt}/中華", f"{txt}/お任せ"])

    # 3. ジャンル選択 -> 食材ヒアリング
    elif "/" in txt and "優先" not in txt:
        msg = f"【{txt}】で承りました。\\n優先的に使いたい食材を入力してください。\\n（例：鶏肉、キャベツ、特になし）"
        send_reply(tk, msg)

    # 4. 最終誘導（LIFFへ）
    else:
        liff_url = f"https://liff.line.me/2010225388-rXh2LiOR?query={txt}"
        qr = QuickReply(items=[QuickReplyItem(action=URIAction(label="🍳 レシピを表示", uri=liff_url))])
        msg = f"「{txt}」を優先したレシピを考えました！\\n下のボタンから確認して、画像を保存してくださいね。"
        send_reply(tk, msg, qr)

def send_quick(tk, msg, opts):
    items = [QuickReplyItem(action=MessageAction(label=o.split('/')[-1], text=o)) for o in opts]
    send_reply(tk, msg, QuickReply(items=items))

def send_reply(tk, msg, qr=None):
    with ApiClient(conf) as api_client:
        line_api = MessagingApi(api_client)
        line_api.reply_message(ReplyMessageRequest(
            reply_token=tk,
            messages=[TextMessage(text=msg, quick_reply=qr)]
        ))

# --- レシピ生成API（Gemini 3.5 Flash） ---
@app.route("/api/generate-recipe")
def generate():
    query = request.args.get('query', 'おまかせ')
    p = f"要望:{query}。15分節約レシピをJSONのみで。{{'name':'','time':'','cost':'','tip':'','ingredients':[{{'name':'','amount':''}}],'steps':[]}}"
    try:
        # 指定の 3.5-flash
        res = client.models.generate_content(model='gemini-3.5-flash', contents=p)
        clean = res.text.replace('```json', '').replace('```', '').strip()
        return jsonify(json.loads(clean))
    except Exception as e:
        return jsonify({"name": "エラー", "steps": ["もう一度お試しください"]})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))

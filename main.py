import os, json, threading, requests, google.genai as genai
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

# --- Renderを叩き起こすための関数 ---
def wake_up_render():
    try:
        # 自分のURLを叩いてスリープを解除する
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
    
    # ユーザーから信号が来たら、別スレッドで裏側でRenderを起こす（返信を遅らせない）
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
        send_quick(tk, "カジラク・コンシェルジュです🍳\nいつのご飯を考えましょうか？", ["朝ごはん", "昼ごはん", "夜ごはん"])

    # 2. 時間帯選択（ここでジャンルを聞く）
    elif txt in ["朝ごはん", "昼ごはん", "夜ごはん"]:
        send_quick(tk, f"{txt}ですね！ジャンルはどうしますか？", 
                   [f"{txt}/和風", f"{txt}/洋風", f"{txt}/中華", f"{txt}/お任せ"])

    # 3. ジャンル選択（ここで食材を聞く ＋ 裏でAIに先行情報を送る）
    elif "/" in txt and "優先" not in txt:
        # ★店長のアイデア：ここで裏側でGeminiに「準備」をさせても良いですが、
        # 現状はシンプルに次の入力を促し、Renderの覚醒を維持します。
        msg = f"【{txt}】で承りました。\n次に、優先的に使いたい食材を入力してください。\n（例：鶏肉、キャベツ、特になし）"
        send_reply(tk, msg)

    # 4. 食材入力完了 -> LIFFへ誘導
    else:
        liff_url = f"https://liff.line.me/2010225388-rXh2LiOR?query={txt}"
        qr = QuickReply(items=[QuickReplyItem(action=URIAction(label="🍳 レシピを表示", uri=liff_url))])
        msg = f"「{txt}」を優先したレシピを考えました！\n下のボタンから確認して、画像を保存してくださいね。"
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

# --- レシピ生成（Gemini 3.5 Flash） ---
@app.route("/api/generate-recipe")
def generate():
    query = request.args.get('query', 'おまかせ')
    p = f"要望:{query}。15分節約レシピをJSON形式で提案して。{{'name':'','time':'','cost':'','tip':'','ingredients':[{{'name':'','amount':''}}],'steps':[]}}"
    try:
        # ここで店長指定の 3.5-flash
        res = client.models.generate_content(model='gemini-3.5-flash', contents=p)
        clean = res.text.replace('```json', '').replace('```', '').strip()
        return jsonify(json.loads(clean))
    except Exception as e:
        return jsonify({"name": "エラー", "steps": ["もう一度お試しください"]})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))

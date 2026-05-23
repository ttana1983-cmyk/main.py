import os
import traceback
from flask import Flask, request, abort
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import Configuration, ApiClient, MessagingApi, ReplyMessageRequest, TextMessage, QuickReply, QuickReplyItem, PostbackAction
from linebot.v3.webhooks import MessageEvent, TextMessageContent, PostbackEvent
import google.generativeai as genai

app = Flask(__name__)

# --- 設定 ---
conf = Configuration(access_token=os.environ["LINE_CHANNEL_ACCESS_TOKEN"])
handler = WebhookHandler(os.environ["LINE_CHANNEL_SECRET"])
genai.configure(api_key=os.environ["GEMINI_API_KEY"])
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

# --- 1. 最初の入り口 ---
@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    tk = event.reply_token
    quick_reply = QuickReply(items=[
        QuickReplyItem(action=PostbackAction(label="朝ごはん", data="step=mood&time=朝", display_text="朝ごはん")),
        QuickReplyItem(action=PostbackAction(label="昼ごはん", data="step=mood&time=昼", display_text="昼ごはん")),
        QuickReplyItem(action=PostbackAction(label="夜ごはん", data="step=mood&time=夜", display_text="夜ごはん"))
    ])
    with ApiClient(conf) as api_client:
        line_api = MessagingApi(api_client)
        line_api.reply_message(ReplyMessageRequest(
            reply_token=tk,
            messages=[TextMessage(text="いつのごはんにしますか？", quick_reply=quick_reply)]
        ))

# --- 2. 選択・対話処理 ---
@handler.add(PostbackEvent)
def handle_postback(event):
    data = event.postback.data
    tk = event.reply_token
    params = dict(item.split('=') for item in data.split('&'))
    step = params.get('step')

    if step == "mood":
        moods = ["ヘルシー", "コッテリ", "ガッツリ", "さっぱり", "時短", "和食", "中華", "洋食", "お菓子", "お任せ"]
        items = [QuickReplyItem(action=PostbackAction(label=m, data=f"step=ask_fridge&{data}&mood={m}", display_text=m)) for m in moods]
        items.append(QuickReplyItem(action=PostbackAction(label="最初から", data="step=start", display_text="最初に戻る")))
        
        with ApiClient(conf) as api_client:
            line_api = MessagingApi(api_client)
            line_api.reply_message(ReplyMessageRequest(
                reply_token=tk,
                messages=[TextMessage(text="今の気分やジャンルを教えてください！", quick_reply=QuickReply(items=items))]
            ))

    elif step == "ask_fridge":
        with ApiClient(conf) as api_client:
            line_api = MessagingApi(api_client)
            line_api.reply_message(ReplyMessageRequest(
                reply_token=tk,
                messages=[TextMessage(text=f"【{params.get('time')}/{params.get('mood')}】ですね！\n\n冷蔵庫の食材は何がありますか？\n賞味期限が近いものや優先的に使って欲しいものはありますか？\n(例：鶏肉、卵、しなびた小松菜)")]
            ))

# --- 3. 食材入力からの検索・生成 ---
@handler.add(MessageEvent, message=TextMessageContent)
def handle_final_input(event):
    msg = event.message.text
    tk = event.reply_token

    try:
        # 【プロンプトの工夫】実在するURLを検索して提示するように強く指示
        prompt = f"""
        あなたはプロの料理研究家です。ユーザーの冷蔵庫にある食材で最高の献立を提案してください。
        
        【ユーザーの食材/状況】
        {msg}

        【指示】
        1. この食材を使ったレシピを1つ提案してください。
        2. レシピ名、材料、簡単な作り方を書いてください。
        3. 最後に、クックパッド、クラシル、デリッシュキッチンなどの実在する大手レシピサイトから、この料理に該当する正確なレシピURLを必ず1つ検索して載せてください。
        4. 嘘のURL（リンク切れ）は絶対に載せないでください。
        """
        
        # 安全設定（BLOCK_NONE）を適用
        response = model.generate_content(
            prompt,
            safety_settings=[{"category": c, "threshold": "BLOCK_NONE"} for c in ["HARM_CATEGORY_HARASSMENT", "HARM_CATEGORY_HATE_SPEECH", "HARM_CATEGORY_SEXUALLY_EXPLICIT", "HARM_CATEGORY_DANGEROUS_CONTENT"]]
        )
        
        with ApiClient(conf) as api_client:
            line_api = MessagingApi(api_client)
            line_api.reply_message(ReplyMessageRequest(
                reply_token=tk,
                messages=[TextMessage(text=response.text)]
            ))
    except Exception as e:
        print(f"Error: {e}")
        # 万が一のエラー時は丁寧に案内
        with ApiClient(conf) as api_client:
            line_api = MessagingApi(api_client)
            line_api.reply_message(ReplyMessageRequest(
                reply_token=tk,
                messages=[TextMessage(text="すみません、うまくレシピを探せませんでした。食材を少し変えてもう一度送ってみてください。")]
            ))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

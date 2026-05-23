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

# --- 1. 時間帯の選択 ---
@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    tk = event.reply_token
    # メッセージの内容が「最初から」や特定のキーワードでない場合の初期応答
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

# --- 2. 気分・ジャンルの選択 ---
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
                messages=[TextMessage(text=f"【{params.get('time')}/{params.get('mood')}】ですね！\n\n冷蔵庫の食材や、優先して使いたいものを教えてください。")]
            ))

# --- 3. 食材入力から最新情報を検索して回答 ---
@handler.add(MessageEvent, message=TextMessageContent)
def handle_final_input(event):
    msg = event.message.text
    tk = event.reply_token

    # ユーザーが「朝ごはん」などの初期フロー以外のテキストを送った時に献立生成
    try:
        prompt = f"""
        あなたはプロの料理研究家です。最新のレシピ情報を元に提案してください。
        
        【条件】
        食材・状況: {msg}

        【指示】
        1. 指定された食材に最適なレシピを1つ提案してください。
        2. 実在するレシピを検索し、以下のサイトの中から現在アクセス可能な有効なURLを必ず1つ載せてください。
           (クックパッド、クラシル、デリッシュキッチン、Nadia、レタスクラブ、キッコーマン)
        3. ページが存在しないリンクは絶対に載せないでください。もし特定のURLが見つからない場合は、検索キーワードを添えて「〇〇で検索してみてください」と案内してください。
        4. レシピ名、材料、時短・節約のコツも添えてください。
        """
        
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

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

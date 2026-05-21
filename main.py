import os
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage, FollowEvent,
    QuickReply, QuickReplyButton, MessageAction, 
    ShowLoadingAnimationRequest
)
import google.generativeai as genai

app = Flask(__name__)

# --- 環境設定 ---
line_bot_api = LineBotApi(os.environ["LINE_CHANNEL_ACCESS_TOKEN"])
handler = WebhookHandler(os.environ["LINE_CHANNEL_SECRET"])
genai.configure(api_key=os.environ["GOOGLE_API_KEY"])
model = genai.GenerativeModel("models/gemini-2.0-flash")

# --- 便利関数：ボタン（クイックリプライ）作成 ---
def create_qr(options):
    return QuickReply(items=[QuickReplyButton(action=MessageAction(label=opt, text=opt)) for opt in options])

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

# --- 友だち追加された時 ---
@handler.add(FollowEvent)
def handle_follow(event):
    line_bot_api.reply_message(event.reply_token, TextSendMessage(
        text="友だち追加ありがとうございます！Takashiです😊\n献立作りのサポートのため、まずは【男性の人数】を教えてください👇",
        quick_reply=create_qr(["男性0人", "男性1人", "男性2人", "男性3人以上"])
    ))

# --- メッセージ受信時のメインロジック ---
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_message = event.message.text
    user_id = event.source.user_id

    # 【新設】「メニュー」や「戻る」が来たら最初の選択肢を出す
    if user_message in ["メニュー", "最初から", "戻る", "↩️戻る"]:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(
            text="こんにちは！今からどんなご飯にしますか？😊",
            quick_reply=create_qr(["☀️朝ごはん", "🍱お昼ご飯", "🌙晩ご飯", "⚙️再設定"])
        ))
        return

    # 1. 家族構成ヒアリング：男性
    if "男性" in user_message:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(
            text="ありがとうございます！次は【女性の人数】を教えてください✨",
            quick_reply=create_qr(["女性0人", "女性1人", "女性2人", "女性3人以上"])
        ))
        return

    # 2. 家族構成ヒアリング：女性
    elif "女性" in user_message:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(
            text="お子さん（中学生以下）はいらっしゃいますか？👶",
            quick_reply=create_qr(["いない", "乳幼児", "幼児", "小学生", "中学生"])
        ))
        return

    # 3. 家族構成ヒアリング：子供
    elif user_message in ["いない", "乳幼児", "幼児", "小学生", "中学生"]:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(
            text="最後にご年配の方（65歳以上）はいらっしゃいますか？👵",
            quick_reply=create_qr(["ご年配あり", "ご年配なし"])
        ))
        return

    # 4. 家族構成完了 ➔ 最初の食事選択へ誘導
    elif "ご年配" in user_message:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(
            text="登録完了です！バッチリ把握しました😊\nさっそく、今からどんなご飯にしますか？👇",
            quick_reply=create_qr(["☀️朝ごはん", "🍱お昼ご飯", "🌙晩ご飯"])
        ))
        return

    # 5. タイミング選択 ➔ ジャンル選択へ
    elif user_message in ["☀️朝ごはん", "🍱お昼ご飯", "🌙晩ご飯"]:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(
            text="料理のジャンルは何がよろしいですか？🇯🇵🇨🇳🇫🇷",
            quick_reply=create_qr(["和食", "洋食", "中華", "フレンチ", "イタリアン", "お任せ"])
        ))
        return

    # 6. ジャンル選択 ➔ 気分選択へ
    elif user_message in ["和食", "洋食", "中華", "フレンチ", "イタリアン", "お任せ"]:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(
            text="今の気分はどれに近いですか？🍳",
            quick_reply=create_qr(["🥗ヘルシー", "🧀コッテリ", "🍖ガッツリ", "🍵あっさり", "↩️戻る"])
        ))
        return

    # 7. 気分選択 ➔ AIによる献立生成
    elif user_message in ["🥗ヘルシー", "🧀コッテリ", "🍖ガッツリ", "🍵あっさり"]:
        line_bot_api.show_loading_animation(ShowLoadingAnimationRequest(chat_id=user_id, loading_seconds=60))
        
        # ユーザーに安心感を与えるメッセージ（push_messageを使用）
        line_bot_api.push_message(user_id, TextSendMessage(text="承知しました！元ラーメン店長の経験を活かして、最高の献立を考えています...50秒ほどお待ちください🍳"))
        
        # プロンプトの構築（ユーザーの最新の選択を反映）
        prompt = f"家族構成と、今日の気分（{user_message}）に合わせて、元プロの視点から栄養バランスも考慮した、家庭で再現可能な「最高に旨い献立」を1つ提案してください。作り方のコツも一言添えて。"
        
        response = model.generate_content(prompt)
        line_bot_api.push_message(user_id, TextSendMessage(text=response.text))
        return

    # 8. 再設定処理
    elif user_message == "⚙️再設定":
        line_bot_api.reply_message(event.reply_token, TextSendMessage(
            text="家族構成を再登録しますね。まずは【男性の人数】を教えてください👇",
            quick_reply=create_qr(["男性0人", "男性1人", "男性2人", "男性3人以上"])
        ))
        return

if __name__ == "__main__":
    app.run()

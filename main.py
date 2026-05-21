import os
import time
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage, FollowEvent,
    QuickReply, QuickReplyButton, MessageAction
)
# アニメーション機能の読み込み
try:
    from linebot.models.responses import ShowLoadingAnimationRequest
except ImportError:
    ShowLoadingAnimationRequest = None

import google.generativeai as genai

app = Flask(__name__)

# --- 環境設定 ---
line_bot_api = LineBotApi(os.environ["LINE_CHANNEL_ACCESS_TOKEN"])
handler = WebhookHandler(os.environ["LINE_CHANNEL_SECRET"])
genai.configure(api_key=os.environ["GEMINI_API_KEY"]) # GEMINI_API_KEYに合わせました
model = genai.GenerativeModel("models/gemini-2.0-flash")

# --- 便利関数：ボタン作成 ---
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

# --- 友だち追加時 ---
@handler.add(FollowEvent)
def handle_follow(event):
    line_bot_api.reply_message(event.reply_token, TextSendMessage(
        text="友だち追加ありがとうございます！Takashiです😊\n献立作りのサポートのため、まずは【男性の人数】を教えてください👇",
        quick_reply=create_qr(["男性0人", "男性1人", "男性2人", "男性3人以上"])
    ))


# --- (前略：インポートや初期設定はそのまま) ---

# --- メッセージ受信ロジック ---
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_message = event.message.text
    user_id = event.source.user_id

    # メニュー呼び出し / 戻る
    if user_message in ["メニュー", "最初から", "戻る", "↩️戻る"]:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(
            text="こんにちは！今からどんなご飯にしますか？😊",
            quick_reply=create_qr(["☀️朝ごはん", "🍱お昼ご飯", "🌙晩ご飯", "⚙️再設定"])
        ))
        return

    # --- 家族構成ヒアリング（省略：既存のロジックを維持） ---
    # ※「ご年配」の回答後の誘導を「タイミング選択」に変更済み

    # タイミング選択 ➔ ジャンル選択
    elif user_message in ["☀️朝ごはん", "🍱お昼ご飯", "🌙晩ご飯"]:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(
            text="料理のジャンルを選んでください🇯🇵🇨🇳",
            quick_reply=create_qr(["和食", "洋食", "中華", "イタリアン", "お任せ"])
        ))
        return

    # ジャンル選択 ➔ 気分選択
    elif user_message in ["和食", "洋食", "中華", "イタリアン", "お任せ"]:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(
            text="今の気分は？🍳",
            quick_reply=create_qr(["🥗ヘルシー", "🧀コッテリ", "🍖ガッツリ", "🍵あっさり"])
        ))
        return

    # 【復活】気分選択 ➔ 冷蔵庫の中身ヒアリング
    elif user_message in ["🥗ヘルシー", "🧀コッテリ", "🍖ガッツリ", "🍵あっさり"]:
        # ユーザーの選択を一時的に保持する代わりに、次のメッセージでまとめて送ってもらうよう促す
        line_bot_api.reply_message(event.reply_token, TextSendMessage(
            text=f"【{user_message}】ですね！\n最後に、冷蔵庫にある「使いたい食材」を教えてください。（例：鶏肉、玉ねぎ、キャベツ）\n特に無ければ「お任せ」と入力してください😊"
        ))
        return

    # --- 最終ステップ：食材入力 ➔ AI生成（ここを高速化！） ---
    # どの選択肢にも当てはまらない自由入力（食材）が来たらAI起動
    else:
        # アニメーション開始
        if ShowLoadingAnimationRequest:
            try:
                line_bot_api.show_loading_animation(ShowLoadingAnimationRequest(chat_id=user_id, loading_seconds=60))
            except: pass
        
        # 即レス
        line_bot_api.push_message(user_id, TextSendMessage(text="プロの知恵を絞って献立を作成中です！30秒ほどお待ちください...👨‍🍳"))

        # 高速化プロンプト（出力を簡潔に指定）
        prompt = f"""
        あなたは元ラーメン店長の料理コンシェルジュです。
        【条件】: {user_message} (食材など) を使用
        【ターゲット】: 登録された家族構成
        上記に合わせ、1分以内で作れるような解説付き献立を1つ提案してください。
        回答は以下の構成で、簡潔に（300文字以内）出力してください。
        1. メニュー名
        2. 材料と工程（要点のみ）
        3. 元店長のワンポイントアドバイス
        """
        
        # 生成速度を上げるため、max_output_tokensを制限するのも手
        response = model.generate_content(prompt)
        line_bot_api.push_message(user_id, TextSendMessage(text=response.text))
        return

# --- (後略：再設定やメイン関数) ---


    # 再設定
    elif user_message == "⚙️再設定":
        line_bot_api.reply_message(event.reply_token, TextSendMessage(
            text="家族構成を再登録しますね。まずは【男性の人数】を教えてください👇",
            quick_reply=create_qr(["男性0人", "男性1人", "男性2人", "男性3人以上"])
        ))
        return

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

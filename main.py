@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    msg = event.message.text
    # reply_token を使うのがLINE Botの鉄則です
    token = event.reply_token 

    if msg not in ["メニュー", "最初から", "⚙️再設定"]:
        try:
            # プロンプトをより明確に
            prompt = f"""
あなたは元ラーメン店長の献立アドバイザーです。
食材「{msg}」を使ったプロ直伝の献立を1つ提案してください。

【制約条件】
・350文字以内
・語尾は少し職人気質で親しみやすく
・最後に必ず実在するクックパッド等のレシピURLを1つ載せること（404は厳禁）
"""
            response = model.generate_content(prompt)
            recipe_text = response.text

            # 複数のメッセージを「1回の返信」としてまとめて送る（これで制限に強い！）
            messages = [
                TextSendMessage(text="オーダー入りました！ねこシェフ調理中...🐾"),
                ImageSendMessage(original_content_url=GIF_URL, preview_image_url=GIF_URL),
                TextSendMessage(text=f"🔔 ピーッ！＼ チン！ ／\n\n{recipe_text}")
            ]
            
            line_bot_api.reply_message(token, messages)

        except Exception as e:
            # エラー時も「返信」で伝える
            line_bot_api.reply_message(token, TextSendMessage(text=f"店長、ちょっと今手が離せねえ！\n(Error: {str(e)[:20]})"))

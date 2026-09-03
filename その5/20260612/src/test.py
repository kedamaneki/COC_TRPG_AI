from concurrent.futures import thread
import requests
import json
import time
import threading

url = "http://localhost:11434/api/chat"


# 1. 会話履歴のリストを定義
history = [
    {"role": "system", "content": "あなたは親切なAIです。"}
]

print("チャットを開始します（'exit' と入力すると終了します）")
print("-" * 50)
look_at_screen = False

def chat():
    
    while True:
        # ユーザーからの入力を受け取る
        user_input = input("\n[USER]: ")
        
        # 'exit' と入力されたらループを抜けて終了する
        if user_input.strip().lower() == "exit":
            print("チャットを終了します。")
            break
            
        # 入力が空の場合はスキップ
        if not user_input.strip():
            continue

        # ユーザーのメッセージを履歴に追加
        history.append({"role": "user", "content": user_input})
    # 2. APIへ送信
        payload = {
            "model": "gemma3:4b",
            "messages": history,
            "stream": False
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        try:

            response = requests.post(url, json=payload)
            response_data = response.json()
            ai_message = response_data.get("message")

            if ai_message:
                # AIの回答をそのまま履歴に追加（これで短期記憶が保持される）
                history.append(ai_message)
                
                # AIの回答を画面に表示
                print(f"[ASSISTANT]: {ai_message['content']}")
                
        except requests.exceptions.RequestException as e:
            print(f"\n[エラー]: Ollamaとの通信に失敗しました。{e}")
            # エラーが起きた場合は直前に追加したユーザーのメッセージを消去してやり直す
            history.pop()

def timer_roop():
    count = 0
    while True:
        time.sleep(1)
        count += 1
        if count == 180:
            print("3分経過")
            count = 0
            look_at_screen = True


            

thread1=threading.Thread(target=chat)
thread2=threading.Thread(target=timer_roop,daemon=True)

thread1.start()
thread2.start()
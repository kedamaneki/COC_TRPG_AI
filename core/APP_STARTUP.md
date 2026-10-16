# このPCでのアプリ起動

`start-app.cmd` をダブルクリックすると起動します。
ブラウザで http://127.0.0.1:8501 を開いてください。停止は起動したターミナルで Ctrl+C。

PowerShellからの起動:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "F:\制作物\その3\start-app.ps1"
```

使用環境は `.venv-app`（Python 3.14.3）。`src`を作業ディレクトリとして実行し、既存の `.streamlit/secrets.toml` を読み込みます。PL/KP/Judge はローカルOllamaの `qwen2.5:14b` を使用します。

スタートメニューでシナリオを選び、「初めからプレイ」または既存セーブのロードを選択します。「悪霊の家」は選択可能です。ゲーム開始後は通常の保存処理が既存のオートセーブを更新するため、残したいセーブは事前にコピーしてください。

別PCへの展開では仮想環境を再作成します。プロジェクトのソース、シナリオ、src/datasets、必要なセーブ、ローカル設定を配置し、プロジェクト直下で次を実行します。

```powershell
py -m venv .venv-app
.\.venv-app\Scripts\python.exe -m pip install -r requirements.txt
ollama pull qwen2.5:14b
```

Ollamaが停止していればOllamaアプリを起動してください。`ollama list`でモデルを確認できます。

この画面用環境は旧評価チェックポイントのPython 3.12再開環境とは別です。起動スクリプトは評価Runの再開を行いません。

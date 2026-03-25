# Teams 会議翻訳システム

リモート Teams 参加者の英語音声をリアルタイム日本語翻訳・録音・サマリー生成するツールです。

---

## 構成

```
Windows側 (capture.py)
  → WebSocket → WSL2 FastAPI サーバー → ブラウザ (index.html)
```

- **Tab 1**: リアルタイム字幕（英語 → 日本語）
- **Tab 2**: 録音した会議の文字起こし・翻訳・サマリー

---

## セットアップ手順

### WSL2側（サーバー）

#### 1. リポジトリ準備

```bash
cd ~/teams-translator
```

#### 2. 仮想環境と依存パッケージのインストール

```bash
uv venv .venv
uv pip install -r pyproject.toml
# または
uv pip install fastapi "uvicorn[standard]" websockets anthropic faster-whisper numpy aiosqlite python-multipart python-dotenv pydantic-settings
```

#### 3. 環境変数の設定

```bash
cp .env.example .env
# .env を編集して ANTHROPIC_API_KEY を設定
nano .env
```

`.env` の内容:
```
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxxxxxx
WHISPER_REALTIME_MODEL=base
WHISPER_BATCH_MODEL=large-v3
```

#### 4. サーバー起動

```bash
source .venv/bin/activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

ブラウザで `http://localhost:8000` にアクセスします。

---

### Windows側セットアップ

#### 1. Python インストール

Python 3.10 以上が必要です。[python.org](https://python.org) からインストールしてください。

#### 2. 依存パッケージのインストール

```cmd
cd %USERPROFILE%\teams-translator\windows_capture
pip install -r requirements.txt
```

> `pyaudiowpatch` は WASAPI ループバック（システム音声のキャプチャ）に使用します。
> インストール時にエラーが出る場合は Visual C++ ランタイムが必要な場合があります。

#### 3. WSL2のIPアドレス確認

WSL2内で以下を実行してIPアドレスを確認します：

```bash
ip addr show eth0 | grep 'inet '
# 例: inet 172.28.0.1/20
```

---

## 使い方

### リアルタイム翻訳

Teams会議でリモート参加者の英語音声をリアルタイムで日本語字幕に変換します。

```cmd
python capture.py --mode realtime --server ws://172.28.0.1:8000
```

ブラウザの **Tab 1（リアルタイム翻訳）** に字幕が表示されます。

### 会議録音

1. ブラウザの **Tab 2（会議録音・振り返り）** を開く
2. 「＋ 新規会議」ボタンで会議を作成し、表示された ID を確認
3. Windows側でキャプチャ開始:

```cmd
python capture.py --mode record --meeting-id 1 --server ws://172.28.0.1:8000
```

または curl でAPIから会議を作成:

```cmd
curl -X POST http://172.28.0.1:8000/api/meetings ^
  -H "Content-Type: application/json" ^
  -d "{\"name\": \"週次定例会議\"}"
```

4. 会議終了後、Ctrl+C でキャプチャ停止
5. ブラウザで「処理開始」ボタンをクリック（文字起こし・翻訳・サマリー生成）

---

## API エンドポイント

| メソッド | パス | 説明 |
|---------|------|------|
| GET | `/api/meetings` | 会議一覧 |
| POST | `/api/meetings` | 会議作成 |
| GET | `/api/meetings/{id}` | 会議詳細（文字起こし・サマリー含む） |
| POST | `/api/meetings/{id}/process` | バッチ処理開始 |
| GET | `/api/meetings/{id}/status` | ステータス確認 |
| DELETE | `/api/meetings/{id}` | 会議削除 |
| WS | `/ws/capture` | Windows側音声ストリーム受信 |
| WS | `/ws/display` | ブラウザへのリアルタイム翻訳配信 |

---

## 注意事項

- **Whisper モデルの初回ダウンロード**: `base` モデルは約145MB、`large-v3` は約3GBです。初回使用時に自動ダウンロードされます。
- **CPU使用率**: Whisperは処理負荷が高いため、`large-v3` モデルのバッチ処理は時間がかかります（1時間の会議で15〜30分程度）。
- **ANTHROPIC_API_KEY**: Anthropic のAPIキーが必要です。[console.anthropic.com](https://console.anthropic.com) で取得してください。
- **WSL2のポート**: Windows側からWSL2に接続する場合、WSL2のIPアドレス（172.x.x.x）を使用してください。`localhost` では接続できない場合があります。
- **システム音声キャプチャ**: `pyaudiowpatch` はWindows専用です。Teamsのシステム音声（リモート参加者の声）をキャプチャします。
- **録音ファイル**: `recordings/` ディレクトリに WAV 形式で保存されます（16kHz, モノラル, 16bit）。

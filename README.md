# TFT Strategy & Meta Advisor

普遍的な立ち回り理論（ナレッジベース/RAG）と最新パッチの構成・統計（Riot API集計/静的サンプル）を
組み合わせて、TFT(Teamfight Tactics)プレイヤーの意図に応じたアドバイスを提供するStreamlitアプリ。

## セットアップ

### 1. 依存パッケージのインストール

```
pip install -r requirements.txt
```

### 2. `.env` の作成

`.env.example` をコピーして `.env` を作成し、必要な値を設定してください。

```
copy .env.example .env
```

#### LLM APIキー（いずれか一方は必須）

- **OpenAI**: `LLM_PROVIDER=openai` に設定し、`OPENAI_API_KEY` を
  [platform.openai.com/api-keys](https://platform.openai.com/api-keys) で発行して設定します。
- **Google Gemini**: `LLM_PROVIDER=gemini` に設定し、`GOOGLE_API_KEY` を
  [aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey) で発行して設定します。

#### Riot Games API（任意）

未設定でもアプリは静的サンプルデータ（`data/patch_xx/meta_snapshot.json`）で動作します。
実データを集計したい場合のみ設定してください。

1. [developer.riotgames.com](https://developer.riotgames.com/) にRiotアカウントでログイン。
2. 「個人用APIキー(Development API Key)」を発行し、`.env` の `RIOT_API_KEY` に設定。
   - **個人用キーは24時間で失効します**。継続利用する場合は都度再発行が必要です。
   - 大規模・継続的な利用には本番用キー（審査あり）の申請が別途必要です。
3. `RIOT_PLATFORM_REGION`（例: `jp1`, `na1`, `kr`）と `RIOT_REGIONAL_ROUTE`
   （例: `asia`, `americas`, `europe`）を自分のリージョンに合わせて設定。

### 3. ナレッジベースの準備

`knowledge_base/` フォルダにMarkdownノート（`.md`）を配置してください。
サンプルノートが3本入っているので、そのままでも動作確認できます。
独自ノートを追加・更新した場合は以下を実行してベクトルDBを再構築してください。

```
python scripts/build_vector_db.py
```

（`streamlit run app.py` のサイドバーからも再構築できます）

### 4. 最新メタ統計の取得（任意・RIOT_API_KEY設定時のみ）

```
python scripts/build_meta_stats.py
```

`data/patch_xx/meta_cache.json` が生成され、以降はこのキャッシュが優先的に使用されます
（未生成・取得失敗時は自動的に `meta_snapshot.json` にフォールバックします）。

### 5. パッチの切り替え

`data/current_patch.txt` に既定パッチ（例: `14.8`）を記載しています。
`data/patch_14.9/` のように新しいパッチ用ディレクトリを追加すれば、
Streamlitサイドバーのドロップダウンから参照先を切り替えられます。

## 起動方法

### CLIでの動作確認（Phase 1相当）

```
python scripts/cli_demo.py
```

3分岐（曖昧/理論/メタ）の分類とチェーン応答をターミナルで確認できます。

### Streamlit UI

```
streamlit run app.py
```

## ディレクトリ構成

```
app.py                 Streamlitエントリポイント
config.py               設定値（.env読込）
knowledge_base/         RAG用Markdownノート
data/patch_xx/          パッチ別のメタ統計データ（静的サンプル/Riot API集計キャッシュ）
src/llm/                LLMプロバイダー抽象化
src/schemas/            Pydanticスキーマ（構造化出力）
src/rag/                ナレッジベースの取り込み・検索
src/meta/               Riot API集計・統計フィルタ・パッチ切替
src/chains/             3分岐ルーター・理論/メタ回答チェーン
src/ui/                 カードUI（HTML/CSS）
scripts/                CLIユーティリティ（DB構築・統計収集・動作検証）
```

## 統計データの信頼性ルール

- 通常アイテムBiSは「試行回数が上位10%以内」かつ「最低100件以上」の母集団から選出。
- サンプル数に応じて信頼度ランクを付与（HIGH: 1000件以上 / MEDIUM: 300〜999件 / LOW: 100〜299件）。
- アーティファクト/紋章などの特殊アイテムは通常アイテムと母集団を分け、特殊枠数が一致する
  グループ内で集計。通常BiSを明確に上回る場合のみ `special_synergy_builds` として紹介。

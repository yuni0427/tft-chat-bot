# 🎯 TFT Strategy & Meta Advisor

普遍的な立ち回り理論（ナレッジベース/RAG）と、Riot公式実戦マッチ統計、および TFTAcademy（Dishsoap & Frodan 等のトッププロ監修）の推奨ガイドをリアルタイムに統合し、プレイヤーの質問意図に応じた最適なアドバイスを提供するAIアドバイザーアプリ。

---

## ⚡ 実行コマンドと簡単な説明

### 1. 日常運用・高速同期（推奨）
Riot API の重い試合収集（レート制限待ち）をスキップし、CDragon からの駒/シナジー抽出、ローカルキャッシュからの RAG 再構築、Git デプロイのみを数秒で完了させます。
```bash
python scripts/update_all_meta.py --skip-riot
```

### 2. 全自動フル同期（新パッチ適用時など）
最新パッチ検出、Riot API 統計収集、TFTAcademy 取得、駒/シナジー辞書生成、RAG 再構築、GitHub プッシュまで全工程を一括実行します。
```bash
python scripts/update_all_meta.py
```
このコマンドは、`README.md` があるプロジェクトルート
（`1-tft-strategy-meta`）で実行してください。今回のスクリプトは自身でプロジェクトルートを import パスへ追加するため、プロジェクトルート以外から実行しても動作します。

`ModuleNotFoundError: No module named 'src'` が表示される場合は、古いファイルを実行している可能性があります。プロジェクトルートで次を実行して状態を確認してください。
```powershell
Get-Location
python scripts/update_all_meta.py --help
```
`Get-Location` の末尾が `1-tft-strategy-meta` であり、`--help` が表示されれば import は解決しています。

Riot API の統計更新で `401 Unknown apikey` が表示された場合は、Riot Developer Portal で有効なAPIキーを再発行し、`.env` の `RIOT_API_KEY` を更新してください。キーが無効な状態では、CDragon・TFTAcademy・パッチノートは更新されても、`data/patch_xx/meta_cache.json` のRiot統計は更新されません。更新後は次で確認できます。
```powershell
python scripts/build_meta_stats.py --patch 18.2b
```
`meta_cache.json` の `updated_at` が実行時刻に更新され、構成データに `first_place_rate` が追加されていれば統計更新成功です。

### 3. パッチバージョンを指定して実行する場合
```bash
python scripts/update_all_meta.py --skip-riot --patch 16.18
```

### 4. 立ち回り理論ノート（RAG）のみの即時更新
`knowledge_base/*.md` の理論ノートを加筆・修正した際、ベクトルDB（ChromaDB）のみを即時再構築して GitHub へプッシュします。
```bash
python scripts/update_knowledge.py
```

### 5. 駒・シナジー辞書の単体抽出
CDragon から最新セット（Set 18）の `champions.json` と `traits.json` のみを即座に抽出・最新化します。
```bash
python -c "from pathlib import Path; from src.meta.champion_extractor import sync_champion_data; sync_champion_data('16.18', Path('data/patch_16.18'))"
```

### 6. ローカル Web UI の起動
Streamlit のチャット・分析ダッシュボードを立ち上げます。
```bash
streamlit run app.py
```

---

## 📖 その他の仕様・詳細情報

### 会話履歴・タブ・ログインの要件定義

#### Supabase保存の準備

SQLiteからSupabaseへ切り替える場合は、まず [supabase/history_schema.sql](supabase/history_schema.sql) をSupabase SQL Editorで実行し、キーをソースコードへ書かずに設定します。

```env
HISTORY_BACKEND=supabase
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=your-anon-key
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
ADMIN_EMAILS=admin@example.com
```

現在のアダプターはSupabase REST APIの型を用意した段階です。`SUPABASE_ANON_KEY` と匿名IDだけで本番運用すると他人の履歴分離を保証できないため、実運用ではSupabase AuthのJWTと `auth.uid()` ベースのRLSポリシーを追加してから有効化してください。`service_role` キーをブラウザやGitHubへ公開してはいけません。

管理画面のSupabase全件取得には `SUPABASE_SERVICE_ROLE_KEY` を使います。このキーはStreamlitサーバーのSecretsまたは環境変数だけに設定し、ブラウザ、GitHubリポジトリ、通常のanon設定には置かないでください。

#### 機能要件

- 会話を複数の相談タブとして作成し、タブ単位で質問と回答を表示する。
- 会話履歴はSQLiteへ保存し、Streamlitの再読込やブラウザ再接続後も再開できるようにする。
- `AUTH_ENABLED=false`（既定）は匿名セッション単位で保存する。ブラウザやセッションをまたいだ本人確認はできない。
- `AUTH_ENABLED=true` かつ `AUTH_REQUIRED=false` ではGoogleログインを任意にし、未ログインでも匿名IDで利用できる。匿名IDはURLに付くため、同じリンクを再訪すると履歴を復元できる。
- `AUTH_REQUIRED=true` の場合のみ、Googleログインを必須にする。
- `ADMIN_EMAILS` に登録したGoogleアカウントだけが管理画面を開ける。管理画面では全ユーザーの会話、質問、回答を確認できる。
- `AUTH_ENABLED=true` はStreamlitのOAuthログインを使い、ログインユーザーの識別子ごとに履歴を分離する。
- 同一会話は `MAX_CONTEXT_TURNS`（既定10）ターンでLLM文脈世代をリセットする。保存済み履歴は削除しない。
- LLMへ過去履歴を自動投入する仕様にはしていないため、現状のリセットは会話状態の境界管理であり、過去履歴を再送することによるトークン増加は発生しない。

#### 非機能要件・運用上の注意

- SQLiteファイルは `data/history.sqlite3` に作成される。複数インスタンス・Streamlit Cloudの再デプロイで共有する場合は、PostgreSQL等の外部DBへ置き換える。
- ログインを有効にする場合、`.streamlit/secrets.toml` に `[auth]` のOAuth設定を行い、`AUTH_ENABLED=true` を指定する。OAuthのredirect URI、Cookie設定、秘密情報はデプロイ環境に合わせて管理する。
- 履歴削除、タイトル変更、保持期間、個人情報の削除依頼への対応は次段階の要件とする。
- 認証なし匿名モードを本番公開しない。匿名IDはCookieやセッションが消えると復元できず、他ユーザーとの厳密な分離を保証しない。

#### 現時点の改善課題

- 認証済みユーザーのメールアドレス等を履歴の所有者キーに使うため、将来はOAuthの不変なsubject IDを優先する。
- SQLiteのバックアップ、暗号化、削除API、アクセスログを追加する。
- 長い会話をLLMへ渡す機能を追加する場合は、直近数ターン＋要約を使い、上限トークンとリセット境界を明示する。
- Gemini API呼び出しは意図分類と回答生成で複数回になる場合があるため、分類結果のキャッシュ、リトライ・指数バックオフ、利用量監視を追加する。

### 1. 主な特徴・機能
- **統計 × プロ推奨のクロスチェック**: Riot API のマッチ統計（平均順位・勝率）と TFTAcademy のプロティア表を照合し、根拠のあるメタ構成・最適アイテム（BiS）を提案。
- **ガイド直結 & チームコード出力**: 各構成の解説直下に「TFTAcademy 詳細ガイドリンク」およびゲーム内のチームプランナーに直接インポートできる「チームコード（Copy Team Code）」を自動出力。
- **公式日本語辞書・デバフ判定との完全同期**: CommunityDragon から最新セット（Set 18）のチャンピオン、特性（ブレークポイント・効果）、スキル詳細を自動抽出。**負傷（重症・炎上）、細断、分解、スタン、マナリーヴ** などのユーティリティを辞書化して AI/RAG に提供。
- **完全自動同期パイプライン**: パッチ自動検知、統計収集、プロガイドキャッシュ、ナレッジ再構築を毎日 15:00 (JST) に GitHub Actions（`.github/workflows/sync_meta.yml`）で自動実行（手動メンテ不要）。

### 2. セットアップ & 環境変数

#### 依存パッケージのインストール
```bash
python -m pip install -r requirements.txt
```

同期スクリプトを実行する前に、依存関係をインストールしてください。特にパッチノート取得には `beautifulsoup4` が必要です。

#### 環境変数の設定 (`.env` または `.streamlit/secrets.toml`)
`.env.example` をコピーして `.env` を作成します。
```bash
copy .env.example .env
```
- **LLM APIキー（必須）**:
  - `LLM_PROVIDER=gemini` / `GOOGLE_API_KEY`（または `GEMINI_API_KEY`）
  - `LLM_PROVIDER=openai` / `OPENAI_API_KEY`
- **Riot Games APIキー（実戦統計収集時）**:
  - `RIOT_API_KEY`: [Riot Developer Portal](https://developer.riotgames.com/) で発行したキー
  - `RIOT_PLATFORM_REGION=jp1` / `RIOT_REGIONAL_ROUTE=asia`

### 3. ディレクトリ構成
```text
app.py                         Streamlit アプリケーション本体
config.py                      設定値管理（.env 読込）
knowledge_base/                立ち回り理論 Markdown ノート群
data/
  ├── current_patch.txt        現在適用中のパッチ番号（自動更新）
  ├── tft_lexicon_ja.json      Riot公式 日本語翻訳辞書
  └── patch_xx/                パッチ別の抽出データ & 統計キャッシュ
      ├── champions.json       Set 18 チャンピオン（コスト、スキル、ユーティリティ）
      ├── traits.json          Set 18 シナジー一覧、効果、ブレークポイント
      ├── meta_cache.json      Riot API 上位帯マッチ集計データ
      └── vector_db/           RAG 検索用ベクトルストア（ChromaDB）
src/
  ├── chains/
  │    ├── intent_router.py    意図分類ルーター（理論 / メタ / 曖昧）
  │    ├── meta_chain.py       統計 + TFTAcademy照合回答チェーン
  │    └── theory_chain.py     RAG（理論ノート検索）回答チェーン
  ├── llm/                     LLMプロバイダー抽象化モジュール
  ├── meta/                    CDragon抽出・Riot API集計・翻訳・TFTAcademyクライアント
  ├── rag/                     ナレッジ取り込み・ベクトルストア
  └── ui/                      カードスタイル・CSS
scripts/
  ├── build_meta_stats.py      Riot API マッチ統計集計コアスクリプト
  ├── build_vector_db.py       RAG ベクトルDB構築コアスクリプト
  ├── update_all_meta.py       【全自動】メタ・統計・ナレッジ一括更新スクリプト
  ├── update_knowledge.py      【高速】理論ノート（RAG）単体更新スクリプト
  └── update_lexicon.py        【新セット用】公式日本語辞書更新スクリプト
.github/workflows/
  └── sync_meta.yml            毎日15:00 (JST) 定期実行ワークフロー
```

### 4. 統計データの信頼性ルール
- 通常アイテム BiS は「試行回数が上位10%以内」かつ「最低100件以上」の母集団から選出。
- サンプル数に応じて信頼度ランクを付与（HIGH: 1000件以上 / MEDIUM: 300〜999件 / LOW: 100〜299件）。
- アーティファクト/紋章などの特殊アイテムは通常アイテムと母集団を分離し、通常BiSを上回る組み合わせのみを提示。
- プロティアリスト（TFTAcademy）と実戦マッチ統計で推奨が分かれた場合、両方の根拠を併記して柔軟な選択肢を提示。
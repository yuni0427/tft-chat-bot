# TFT Strategy & Meta Advisor

普遍的な立ち回り理論（ナレッジベース/RAG）と、Riot公式実戦マッチ統計、および TFTAcademy（Dishsoap & Frodan 等のトッププロ監修）の推奨ガイドをリアルタイムに統合し、プレイヤーの質問意図に応じた最適なアドバイスを提供するAIアドバイザーアプリ。

---

## 主な特徴

- **統計 × プロ推奨のクロスチェック**: Riot API のマッチ統計（平均順位・勝率）と TFTAcademy のプロティア表を照合し、根拠のあるメタ構成・最適アイテム（BiS）を提案。
- **ガイド直結 & チームコード出力**: 各構成の解説直下に「TFTAcademy 詳細ガイドリンク」およびゲーム内のチームプランナーに直接インポートできる「チームコード（Copy Team Code）」を自動出力。
- **公式日本語辞書との完全同期**: Riot/CommunityDragon の最新辞書を参照し、チャンピオン名、アイテム名、オーグメント名を正確に日本語化。
- **完全自動同期パイプライン**: パッチ自動検知、統計収集、プロガイドキャッシュ、ナレッジ再構築を毎日 15:00 (JST) に GitHub Actions で完全自動実行。

---

## セットアップ

### 1. 依存パッケージのインストール

```bash
pip install -r requirements.txt
```

### 2. `.env` の作成

`.env.example` をコピーして `.env` を作成し、必要なAPIキーを設定してください。

```bash
copy .env.example .env
```

#### LLM APIキー（必須）

- **Google Gemini（推奨）**: `LLM_PROVIDER=gemini` に設定し、`GOOGLE_API_KEY` を [Google AI Studio](https://aistudio.google.com/app/apikey) で発行して設定します。
- **OpenAI**: `LLM_PROVIDER=openai` に設定し、`OPENAI_API_KEY` を [OpenAI Platform](https://platform.openai.com/api-keys) で発行して設定します。

#### Riot Games API（実戦統計収集時）

未設定でもアプリは静的サンプルデータ（`data/patch_xx/meta_snapshot.json`）やキャッシュデータで動作します。ローカルで実戦マッチデータを収集する場合に設定してください。

1. [developer.riotgames.com](https://developer.riotgames.com/) にログインし、APIキーを取得して `RIOT_API_KEY` に設定。
2. リージョン設定: `RIOT_PLATFORM_REGION=jp1` / `RIOT_REGIONAL_ROUTE=asia`（日本サーバーの場合）。

---

## 起動方法

```bash
streamlit run app.py
```

---

## データ更新・運用ガイド

更新する対象データに応じて、最適なスクリプトを使い分ける設計になっています。

### 1. 毎日の定期自動更新（GitHub Actions）
**管理者の手動作業は不要です。**
GitHub Actions（`.github/workflows/sync_meta.yml`）により、**毎日 15:00 (JST)** に以下が自動実行され、リポジトリへ自動コミット＆プッシュされます（Streamlit Cloud にも即時反映）。

1. Riot Data Dragon から最新パッチ番号を検出・保存（`data/current_patch.txt`）
2. Riot API による最新マッチ統計の収集・分析・集計（`build_meta_stats.py`）
3. TFTAcademy の最新ティア表・チームコードのキャッシュ取得
4. RAG ベクトルDBの再構築（`build_vector_db.py`）
5. GitHub への自動プッシュ

---

### 2. 立ち回り理論ノート（RAG）のみを更新した場合
`knowledge_base/*.md` の理論ノートを加筆・修正した際は、Riot API の重い処理をスキップして**数秒でベクトルDBのみを再構築・デプロイ**できます。

```bash
python scripts/update_knowledge.py
```
> **実行内容:** ベクトルDB（ChromaDB）を即時再構築し、`data/` の変更分のみを GitHub へ自動プッシュします。

---

### 3. 手動で全メタデータを即時更新したい場合
パッチ直後など、15時の定期更新を待たずに今すぐ全データを最新化したい場合に実行します。

```bash
python scripts/update_all_meta.py
```
> **実行内容:** 最新パッチ検出、Riot API 統計収集、TFTAcademy 取得、ベクトルDB再構築、GitHub プッシュを一括実行します。

---

### 4. 新セット開幕時の日本語辞書更新（Set切り替わり時のみ）
新セット（Set 14, 15など）がリリースされ、新しいチャンピオンやアイテムが登場した際のみ単発で実行します。

```bash
python scripts/update_lexicon.py
```
> **実行内容:** CommunityDragon から最新の日本語データを取得し、接頭辞の正規化処理を行って `data/tft_lexicon_ja.json` を再生成・GitHub へプッシュします。

---

## ディレクトリ構成

```text
app.py                         Streamlit アプリケーション本体
config.py                      設定値管理（.env 読込）
knowledge_base/                立ち回り理論 Markdown ノート群
data/
  ├── current_patch.txt        現在適用中のパッチ番号（自動更新）
  ├── tft_lexicon_ja.json      Riot公式 日本語翻訳辞書
  └── patch_xx/                パッチ別の統計キャッシュ（meta_cache.json / meta_snapshot.json）
src/
  ├── chains/
  │     ├── intent_router.py   意図分類ルーター（理論 / メタ / 曖昧）
  │     ├── meta_chain.py      統計 + TFTAcademy照合回答チェーン
  │     └── theory_chain.py    RAG（理論ノート検索）回答チェーン
  ├── llm/                     LLMプロバイダー抽象化モジュール
  ├── meta/                    Riot API集計・翻訳・TFTAcademyクライアント
  ├── rag/                     ナレッジ取り込み・ベクトルストア（ChromaDB）
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

---

## 統計データの信頼性ルール

- 通常アイテム BiS は「試行回数が上位10%以内」かつ「最低100件以上」の母集団から選出。
- サンプル数に応じて信頼度ランクを付与（HIGH: 1000件以上 / MEDIUM: 300〜999件 / LOW: 100〜299件）。
- アーティファクト/紋章などの特殊アイテムは通常アイテムと母集団を分離し、通常BiSを上回る組み合わせのみを提示。
- プロティアリスト（TFTAcademy）と実戦マッチ統計で推奨が分かれた場合、両方の根拠を併記して柔軟な選択肢を提示。
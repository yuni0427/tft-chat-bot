"""
ユーザー入力を3分岐（曖昧/理論/メタ）に分類するルーター。
LangChainの構造化出力(.with_structured_output)を用いてIntentClassificationを取得する。
"""
from src.llm.factory import get_chat_model
from src.schemas.router import IntentClassification

_SYSTEM_PROMPT = """あなたはTFT(Teamfight Tactics)に関するユーザーの質問を3つに分類するルーターです。

以下のcategoryのいずれかに分類してください:
- "ambiguous": 方向性が定まらない曖昧な質問（例:「どうやったら勝てますか？」「強くなりたい」）
- "theory": 普遍的な立ち回り理論・基礎知識に関する質問（例:「ファスト8の手順」「利子管理」「ポジショニングの基本」）
- "meta": 最新パッチの構成・アイテム・統計に関する質問

category="meta" の場合は meta_subtype も判定してください:
- "item_build": 特定チャンピオンの装備・アイテムビルドについての質問（例:「アッシュの装備は？」）
- "comp_from_item_or_emblem": 手持ちのアイテムや紋章から、おすすめの構成を逆引きしたい質問
  （例:「スナイパーの紋章が出た」「BFソードとグローブが余っている」）
- "general": Tier表など全体的なメタ傾向に関する質問

category="ambiguous" の場合は、質問内容に応じた具体的な2択の聞き返しを作成してください。
- clarification_message: 聞き返しの一言（例:「どちらの観点でお答えしましょうか？」）
- clarification_options: 2つの選択肢。それぞれ以下を設定する
  - label: ユーザーに表示する文言
  - route_to: "theory"（基礎理論）, "meta_item"（アイテムビルド）, "meta_comp"（構成の話）のいずれか
  - prefill_query: 選択後にそのままチェーンへ渡す具体的な質問文（元の質問を踏まえて具体化する）

例えば「どうやったら勝てますか？」の場合:
- 選択肢1: label="現パッチで今すぐ勝つ強構成を知りたい", route_to="meta_comp",
  prefill_query="現パッチの強い構成を教えてください"
- 選択肢2: label="地力をつける基礎の立ち回り理論を知りたい", route_to="theory",
  prefill_query="TFTで安定して勝つための基礎的な立ち回りを教えてください"
"""


def classify(user_input: str) -> IntentClassification:
    llm = get_chat_model(temperature=0.0)
    structured_llm = llm.with_structured_output(IntentClassification)
    return structured_llm.invoke(
        [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_input},
        ]
    )

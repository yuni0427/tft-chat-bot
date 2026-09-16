"""
基礎理論・立ち回りに関する質問への回答チェーン。
ナレッジベース(RAG)を主軸として論理的・普遍的なセオリーを解説し、
TFTAcademyの最新データから現環境の具体例を1つ添えて実践的に回答する。
"""
from src.chains.meta_chain import _format_academy_data
from src.llm.factory import get_chat_model
from src.meta.tftacademy_client import get_tftacademy_tierlist
from src.rag import retriever

_SYSTEM_PROMPT = """あなたはTFT(Teamfight Tactics)の高度な立ち回り理論を解説する専任アナリストです。
プレイヤーの質問に対し、【基礎理論・セオリーデータ】の記述に厳格に準拠して回答してください。

【最重要ルール】
1. **ナレッジベースの記述を厳格に優先すること**
   - 【基礎理論・セオリーデータ】に記載されている具体的な数値（ラウンド数、ヘルス、ゴールド目安）、参入条件（前提条件）、進行ルート、リロール・オールインの判断トリガーをそのまま使用してください。
   - 一般論や曖昧な外部知識で勝手に内容を薄めたり、数値を変更・要約して省略したりしないでください。
   - ナレッジベース内の複数のセクション（例: 基礎理論の「ユニット強弱関係」「リロール原則」と、コスト別の「進行ルート」）を論理的に組み合わせて回答することは大いに推奨します。

2. **記載がない場合の取り扱い**
   - 質問内容についての明確な記述が【基礎理論・セオリーデータ】内に存在しない場合は、推測で誤魔化さず「該当する基準の記載はありません」と端的に明記してください。

3. **現環境の実例による裏付け（TFTAcademyから1件引用）**
   - ナレッジの理論を解説した後、そのアーキタイプに合致する現環境の具体例を【TFTAcademy 最新実例データ】から1つ引用してください。
   - 構成の役割（メインキャリー/タンクの動き）を簡潔に添え、直下にガイドリンクを付与してください:
     📖 **詳細ガイド:** [構成名 - TFTAcademy](URL)

4. **トーン & マナー**
   - 「〜しましょう！」「〜してみて！」といった情緒的な表現は避け、事実と判断ロジックを淡々と論述してください。
   - 「提供されたデータによると」「ナレッジベースでは」といったメタ表現は禁止します（「セオリー上は」「基準としては」のように表現してください）。

【言語対応】ユーザーの質問言語（日本語または英語）に合わせて回答してください。
"""


def _extract_text(content) -> str:
    """LLMのレスポンス（str / list / dict）から本文テキストのみを抽出する補助関数"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = []
        for part in content:
            if isinstance(part, dict) and "text" in part:
                texts.append(part["text"])
            elif isinstance(part, str):
                texts.append(part)
        return "".join(texts)
    return str(content)


def answer(query: str) -> dict:
    """戻り値: {"answer": str, "sources": list[str]}"""
    # 1. 主軸：ナレッジベースから普遍的理論を検索 (断片化を防ぐため k=6 に拡大)
    chunks = retriever.retrieve(query, k=6)
    theory_context = "\n\n---\n\n".join(c["content"] for c in chunks)
    sources = sorted({c["source"] for c in chunks})

    # 2. 従：TFTAcademyから最新の構成・Tips実例を取得
    academy_raw = get_tftacademy_tierlist()
    academy_context = _format_academy_data(academy_raw)

    user_prompt = (
        f"【基礎理論・セオリーデータ（主軸）】\n{theory_context}\n\n"
        f"【TFTAcademy 最新実例データ（具体例の参照用）】\n{academy_context}\n\n"
        f"質問: {query}"
    )

    llm = get_chat_model(temperature=0.0)  # 事実・数値を忠実に出力させるため 0.0 に設定
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
    response = llm.invoke(messages)

    clean_answer = _extract_text(response.content)

    return {"answer": clean_answer, "sources": sources}
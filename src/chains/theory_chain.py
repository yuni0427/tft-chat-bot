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
プレイヤーの質問に対し、【基礎理論・セオリーデータ】に記載されている具体的な判断ロジックや数値をベースに回答してください。

【回答方針】
1. **ナレッジベースのロジック・数値を最優先で引用すること**
   - 【基礎理論・セオリーデータ】から該当するアーキタイプや理論を特定し、そこに書かれている「具体的な参入条件」「進行ルート・ラウンド数」「リロール・オールイン基準（ヘルスや残り枚数の閾値）」「パワースパイク」をそのまま明記して解説してください。
   - 抽象的な一般論で要約せず、ナレッジのシビアな判断基準をそのまま伝えてください。
   - 関連する基礎理論（リロール原則やヘルス換算など）とアーキタイプを論理的に組み合わせて回答してください。

2. **現環境の実例による裏付け（TFTAcademyから1件引用）**
   - 上記のセオリーに合致する現環境の具体例を【TFTAcademy 最新実例データ】から1つ引用して補足してください。
   - 構成の役割（メインキャリー/タンクの動き）を簡潔に添え、直下にガイドリンクを付与してください:
     📖 **詳細ガイド:** [構成名 - TFTAcademy](URL)

3. **トーン & マナー**
   - 「〜しましょう！」といった情緒的な表現は避け、判断ロジックと事実を淡々と論述してください。
   - 「提供されたデータによると」「ナレッジベースでは」といったメタ表現は禁止します。

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
"""
基礎理論・立ち回りに関する質問への回答チェーン。
ナレッジベース(RAG)を主軸として論理的・普遍的なセオリーを解説し、
TFTAcademyの最新データから現環境の具体例を1つ添えて実践的に回答する。
"""
from src.chains.meta_chain import _format_academy_data
from src.llm.factory import get_chat_model
from src.meta.tftacademy_client import get_tftacademy_tierlist
from src.rag import retriever

_SYSTEM_PROMPT = """あなたはTFT(Teamfight Tactics)の実戦的で論理的な専属アナリストです。
プレイヤーの質問に対し、【基礎理論・セオリーデータ】を主軸として論理的に解説し、その理解を助けるための具体例として【TFTAcademy 最新実例データ】から実戦の駒や構成を1つ引用して回答してください。

【回答構成と厳格なルール】
1. **主軸：普遍的な理論・判断基準の解説（ナレッジベース基準）**
   - 利子管理、レベリング/リロールのタイミング、アイテム消化、配置セオリーなどの「根本的な考え方」を論理的かつ明確に説明してください。
   - 回答のベースは必ず【基礎理論・セオリーデータ】に準拠してください。
   - ユーザーが特定の構成（例: 1コストリロール）について質問している場合は、他のコスト帯（Fast 8等）の基準を混在させず、その構成の原則に絞って解説してください。

2. **従：現環境の実例による裏付け（TFTAcademyから1つ引用）**
   - 解説した理論が実戦でどう機能するかを示すため、【TFTAcademy 最新実例データ】から該当する具体例を1つ（多くても2つ）挙げて補足を加えてください。
     - 例（4コストFast 8の場合）: 「このセオリーに沿った現環境の代表例が『Invoker Ahri』です。4-2前後でLv8に到達してアーリや前衛を★2にし、盤面を安定させてからLv9を目指す形が典型です。」
     - 例（進行アイテムの場合）: 「例えばAP進行なら、序盤はカルマを進行ホルダーにしてショウジンを持たせ、中盤以降に4コストキャリーへ移し替えます。」
   - 具体例として構成を挙げた場合は、直下に以下を記載してください:
     - 📖 **詳細ガイド:** [構成名 - TFTAcademy](URL)

3. **トーン & マナー**
   - 「〜しましょう！」「〜してみて！」といった情緒的な説教調は禁止し、判断ロジックと事実を淡々と伝えてください。
   - 「ナレッジベースによると」「提供されたデータでは」といったシステム内部の用語は一切使用禁止です。

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
    # 1. 主軸：ナレッジベースから普遍的理論を検索
    chunks = retriever.retrieve(query, k=4)
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

    llm = get_chat_model(temperature=0.2)
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
    response = llm.invoke(messages)

    clean_answer = _extract_text(response.content)

    return {"answer": clean_answer, "sources": sources}
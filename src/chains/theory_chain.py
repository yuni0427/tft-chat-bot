"""
基礎理論・立ち回りに関する質問への回答チェーン。
ナレッジベース(RAG)から類似チャンクを検索し、プロンプトへ注入した上で回答する。
必要に応じて現パッチの構成例を1つ添える。
"""
from src.llm.factory import get_chat_model
from src.meta import meta_service
from src.rag import retriever

_SYSTEM_PROMPT = """あなたはTFT(Teamfight Tactics)の立ち回り理論に詳しいコーチです。
以下の「ナレッジベース抜粋」の内容に基づいて、論理的かつ実践的に回答してください。
ナレッジベースに書かれていない内容を断定的に語らないよう注意してください。
ユーザーが特定の構成（例: 1コストリロール）について質問している場合は、他のコスト帯（Fast 8等）の基準を混在させず、その構成の原則に絞って解説してください。
可能であれば、回答の末尾に現パッチの構成例を1つ簡潔に添えてください（必須ではありません）。
"""


def _extract_text(content) -> str:
    """LLMのレスポンス（str / list / dict）から本文テキストのみを抽出する補助関数"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        # [{'type': 'text', 'text': '...'}, ...] の形式から text のみを結合
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
    chunks = retriever.retrieve(query, k=4)
    context = "\n\n---\n\n".join(c["content"] for c in chunks)
    sources = sorted({c["source"] for c in chunks})

    patch_example = meta_service.get_one_example_snippet()
    example_hint = (
        f"\n\n現パッチ例（参考、必要なら回答に添えてください）: {patch_example}"
        if patch_example
        else ""
    )

    llm = get_chat_model(temperature=0.4)
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"ナレッジベース抜粋:\n{context}{example_hint}\n\n質問: {query}",
        },
    ]
    response = llm.invoke(messages)

    # response.content から署名などのゴミを除去して文字列化
    clean_answer = _extract_text(response.content)

    return {"answer": clean_answer, "sources": sources}

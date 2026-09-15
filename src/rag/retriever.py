"""
ChromaDBに対する類似度検索（RAG Retriever）。
永続化済みのベクトルDBが無い場合は、初回アクセス時に自動でingestを実行する。
"""
from pathlib import Path

import config


_vectordb = None


def _get_vectordb():
    global _vectordb
    if _vectordb is not None:
        return _vectordb

    from langchain_chroma import Chroma
    from src.rag.ingest import _get_embedding_function, build_vector_db

    persist_dir = Path(config.CHROMA_PERSIST_DIR)
    if not persist_dir.exists() or not any(persist_dir.iterdir()):
        build_vector_db()

    _vectordb = Chroma(
        collection_name=config.CHROMA_COLLECTION_NAME,
        embedding_function=_get_embedding_function(),
        persist_directory=config.CHROMA_PERSIST_DIR,
    )
    return _vectordb


def retrieve(query: str, k: int = 4) -> list[dict]:
    """クエリに類似したナレッジベースのチャンクを返す。

    戻り値: [{"content": str, "source": str}, ...]
    """
    vectordb = _get_vectordb()
    results = vectordb.similarity_search(query, k=k)
    return [
        {"content": doc.page_content, "source": doc.metadata.get("source", "unknown")}
        for doc in results
    ]

"""
knowledge_base/ 配下のMarkdownノートを読み込み、見出し単位でチャンク分割して
ChromaDB（ローカル永続化・多言語埋め込み）へ格納するモジュール。
"""
from pathlib import Path

import config


def _get_embedding_function():
    from langchain_huggingface import HuggingFaceEmbeddings

    return HuggingFaceEmbeddings(model_name=config.EMBEDDING_MODEL_NAME)


def _load_markdown_documents():
    from langchain_core.documents import Document
    from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

    kb_dir = Path(config.KNOWLEDGE_BASE_DIR)
    md_files = sorted(kb_dir.glob("*.md"))
    md_files = [p for p in md_files if p.name.lower() != "readme.md"]

    # 1. 大枠の見出しで分割（h1, h2 を基準にし、見出しを本文に残す）
    header_splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=[
            ("#", "section_group"),
            ("##", "topic"),
        ],
        strip_headers=False,  # 本文に見出し（# や ##）を残して文脈を保持する
    )

    # 2. 巨大なチャンクがあった場合のセーフティネット（長すぎる場合のみ分割）
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=150,
    )

    documents: list[Document] = []
    for path in md_files:
        text = path.read_text(encoding="utf-8")
        
        # まず見出し単位で分割
        header_docs = header_splitter.split_text(text)
        
        # さらに長すぎるチャンクを適切に細分化
        final_docs = text_splitter.split_documents(header_docs)
        
        for doc in final_docs:
            doc.metadata["source"] = path.name
            # メタデータに見出し情報を結合して埋め込み精度を強化
            headers_context = " > ".join(
                [v for k, v in doc.metadata.items() if k in ("section_group", "topic")]
            )
            if headers_context:
                doc.metadata["header_path"] = headers_context
            documents.append(doc)

    return documents


def build_vector_db() -> int:
    """knowledge_base/*.md を読み込み、ChromaDBを（再）構築する。戻り値は格納したチャンク数。"""
    from langchain_chroma import Chroma

    documents = _load_markdown_documents()
    if not documents:
        raise RuntimeError(
            f"{config.KNOWLEDGE_BASE_DIR} にMarkdownノートが見つかりませんでした。"
            " ノートを配置してから再実行してください。"
        )

    embedding_function = _get_embedding_function()

    # 既存コレクションを破棄して再構築（ノート追加・編集を確実に反映するため）
    vectordb = Chroma(
        collection_name=config.CHROMA_COLLECTION_NAME,
        embedding_function=embedding_function,
        persist_directory=config.CHROMA_PERSIST_DIR,
    )
    try:
        vectordb.delete_collection()
    except Exception:
        pass

    vectordb = Chroma.from_documents(
        documents=documents,
        embedding=embedding_function,
        collection_name=config.CHROMA_COLLECTION_NAME,
        persist_directory=config.CHROMA_PERSIST_DIR,
    )
    return len(documents)

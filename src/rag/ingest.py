"""knowledge_base/ 配下のMarkdownノートおよび data/patch_*/ 配下のゲームデータ(JSON)を読み込み、

ChromaDB（ローカル永続化・多言語埋め込み）へ格納するモジュール。
"""

import json
from pathlib import Path

import config


def _get_embedding_function():
    from langchain_google_genai import GoogleGenerativeAIEmbeddings

    # 既存の環境変数から自動でAPIキーが読み込まれます
    return GoogleGenerativeAIEmbeddings(model="models/text-embedding-004")


def _load_markdown_documents():
    from langchain_core.documents import Document
    from langchain_text_splitters import (
        MarkdownHeaderTextSplitter,
        RecursiveCharacterTextSplitter,
    )

    kb_dir = Path(config.KNOWLEDGE_BASE_DIR)
    if not kb_dir.exists():
        return []

    md_files = sorted(kb_dir.glob("*.md"))
    md_files = [p for p in md_files if p.name.lower() != "readme.md"]

    header_splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=[
            ("#", "section_group"),
            ("##", "topic"),
        ],
        strip_headers=False,
    )

    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=150,
    )

    documents: list[Document] = []
    for path in md_files:
        text = path.read_text(encoding="utf-8")
        header_docs = header_splitter.split_text(text)
        final_docs = text_splitter.split_documents(header_docs)

        for doc in final_docs:
            doc.metadata["source"] = path.name
            headers_context = " > ".join(
                [
                    v
                    for k, v in doc.metadata.items()
                    if k in ("section_group", "topic")
                ]
            )
            if headers_context:
                doc.metadata["header_path"] = headers_context
            documents.append(doc)

    return documents


def _load_game_data_documents():
    """data/patch_* 配下の champions.json と traits.json を読み込んで Document 化"""
    from langchain_core.documents import Document

    data_dir = Path("data")
    if not data_dir.exists():
        return []

    # 最新パッチフォルダを特定（例: patch_16.18）
    patch_dirs = sorted(data_dir.glob("patch_*"), reverse=True)
    if not patch_dirs:
        return []

    target_patch_dir = patch_dirs[0]
    documents: list[Document] = []

    # 1. champions.json の読み込み
    champ_file = target_patch_dir / "champions.json"
    champs = {}
    if champ_file.exists():
        with open(champ_file, encoding="utf-8") as f:
            champs = json.load(f)

        for name, d in champs.items():
            cost = d.get("cost")
            traits = ", ".join(d.get("traits", []))
            ability_name = d.get("ability", {}).get("name", "")
            ability_desc = d.get("ability", {}).get("description", "")
            utilities = (
                ", ".join(d.get("utilities", []))
                if d.get("utilities")
                else "なし"
            )

            page_content = (
                f"# チャンピオン: {name} (コスト{cost})\n"
                f"- 特性・シナジー: {traits}\n"
                f"- 付与デバフ・効果: {utilities}\n"
                f"- スキル名: {ability_name}\n"
                f"- スキル詳細: {ability_desc}\n"
            )

            doc = Document(
                page_content=page_content,
                metadata={
                    "source": "champions.json",
                    "type": "champion",
                    "name": name,
                    "cost": cost,
                    "traits": traits,
                    "utilities": utilities,
                },
            )
            documents.append(doc)

    # 2. traits.json の読み込み（所属チャンピオンを逆引きして結合）
    trait_file = target_patch_dir / "traits.json"
    if trait_file.exists():
        with open(trait_file, encoding="utf-8") as f:
            traits_data = json.load(f)

        # champions.json から「特性 -> 所属駒リスト」の逆引きマップを作成
        trait_to_champions: dict[str, list[str]] = {}
        if champ_file.exists():
            for c_name, c_data in champs.items():
                cost = c_data.get("cost", "?")
                for t in c_data.get("traits", []):
                    trait_to_champions.setdefault(t, []).append(
                        f"{c_name}({cost}コスト)"
                    )

        for name, d in traits_data.items():
            desc = d.get("description", "")
            breakpoints = ", ".join(map(str, d.get("breakpoints", [])))
            # この特性を持つチャンピオン一覧
            member_champs = ", ".join(trait_to_champions.get(name, []))
            if not member_champs:
                member_champs = "該当なし"

            page_content = (
                f"# 特性・シナジー: {name}\n"
                f"- 発動ブレークポイント: {breakpoints}\n"
                f"- 所属チャンピオン: {member_champs}\n"
                f"- 効果詳細: {desc}\n"
            )

            doc = Document(
                page_content=page_content,
                metadata={
                    "source": "traits.json",
                    "type": "trait",
                    "name": name,
                },
            )
            documents.append(doc)

    return documents


def build_vector_db() -> int:
    """Markdownノート + ゲームデータJSONを統合して ChromaDB を再構築"""
    from langchain_chroma import Chroma

    md_docs = _load_markdown_documents()
    game_docs = _load_game_data_documents()
    all_documents = md_docs + game_docs

    if not all_documents:
        raise RuntimeError(
            f"{config.KNOWLEDGE_BASE_DIR} または data/patch_* にドキュメントが見つかりませんでした。"
        )

    print(
        f"📦 ドキュメント読み込み: Markdown {len(md_docs)}件 / ゲームデータ {len(game_docs)}件 (計 {len(all_documents)}件)"
    )

    embedding_function = _get_embedding_function()

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
        documents=all_documents,
        embedding=embedding_function,
        collection_name=config.CHROMA_COLLECTION_NAME,
        persist_directory=config.CHROMA_PERSIST_DIR,
    )
    return len(all_documents)
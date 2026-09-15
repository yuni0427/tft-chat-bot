"""
knowledge_base/*.md を読み込み、ChromaDB（ベクトルDB）を再構築するCLIスクリプト。

ノートを追加・編集した後に実行してください:
    python scripts/build_vector_db.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.rag.ingest import build_vector_db  # noqa: E402


def main() -> None:
    print("ナレッジベースからベクトルDBを構築しています...")
    count = build_vector_db()
    print(f"完了しました。{count}件のチャンクを格納しました。")


if __name__ == "__main__":
    main()

"""
Phase 1相当: 3分岐ルーターおよび各チェーンの動作をCLIで検証するためのデモスクリプト。
Streamlit UIを使わずに、ルーティングの分岐とチェーンの応答をターミナルで確認できる。

使い方:
    python scripts/cli_demo.py
    （引数なしで実行すると、内蔵の3パターンのサンプル質問を自動で試す）
    python scripts/cli_demo.py "自分の質問文"
    （引数を渡すと、その質問1件だけをルーティングして応答を表示する）
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.chains import intent_router, meta_chain, theory_chain  # noqa: E402

SAMPLE_QUESTIONS = [
    "なんの構成が強いですか？",
    "マルファイトの装備は何がいいですか？",
    "ニダリーの装備は何がいいですか？",
]


def run_one(query: str) -> None:
    print("=" * 60)
    print(f"入力: {query}")
    classification = intent_router.classify(query)
    print(f"分類結果: category={classification.category}, meta_subtype={classification.meta_subtype}")

    if classification.category == "ambiguous":
        print(f"聞き返し: {classification.clarification_message}")
        for opt in classification.clarification_options or []:
            print(f"  - [{opt.route_to}] {opt.label}  (prefill: {opt.prefill_query})")
        return

    if classification.category == "theory":
        result = theory_chain.answer(query)
        print("--- 回答 (theory_chain) ---")
        print(result["answer"])
        print(f"(参照ノート: {', '.join(result['sources'])})")
        return

    # category == "meta"
    result = meta_chain.handle_meta(query, classification.meta_subtype)
    print(f"--- 回答 (meta_chain: {result['type']}) ---")
    if result["type"] == "item_build":
        advice = result["data"]
        print(f"チャンピオン: {advice.champion}")
        print(f"BiS: {advice.bis_standard_build.items} (信頼度: {advice.bis_standard_build.confidence_level})")
    elif result["type"] == "comp_list":
        for comp in result["data"]:
            print(f"- {comp.comp_name} (Tier{comp.tier}, 平均順位{comp.avg_place})")
    else:
        print(result["data"])


def main() -> None:
    if len(sys.argv) > 1:
        run_one(" ".join(sys.argv[1:]))
        return
    for q in SAMPLE_QUESTIONS:
        run_one(q)


if __name__ == "__main__":
    main()

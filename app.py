"""
TFT Strategy & Meta Advisor - Streamlitアプリ本体。
立ち回り理論（RAG）と実戦マッチ統計・プロガイドを照合するAIチャットUI
"""
import streamlit as st

import config
from src.chains import intent_router, meta_chain, theory_chain
from src.llm.factory import is_llm_configured
from src.meta import meta_service
from src.ui import cards

st.set_page_config(page_title="TFT Strategy & Meta Advisor", page_icon="🧠", layout="wide")


# ---------------------------------------------------------------------------
# ヘルパー関数
# ---------------------------------------------------------------------------
def _respond_theory(query: str) -> None:
    try:
        result = theory_chain.answer(query)
    except Exception as exc:  # noqa: BLE001
        st.session_state.messages.append(
            {"role": "assistant", "content": f"回答生成中にエラーが発生しました: {exc}"}
        )
        return
    content = result["answer"]
    if result.get("sources"):
        content += f"\n\n---\n📚 **参照ノート:** {', '.join(result['sources'])}"
    st.session_state.messages.append({"role": "assistant", "content": content})


def _respond_meta(query: str, meta_subtype: str | None) -> None:
    patch = st.session_state.get("selected_patch")
    try:
        result = meta_chain.handle_meta(query, meta_subtype, patch)
    except Exception as exc:  # noqa: BLE001
        st.session_state.messages.append(
            {"role": "assistant", "content": f"回答生成中にエラーが発生しました: {exc}"}
        )
        return

    if result["type"] == "item_build":
        html = cards.render_item_build_card(result["data"])
        st.session_state.messages.append({"role": "assistant", "content": "", "html": html})
    elif result["type"] == "comp_list":
        html = "".join(cards.render_comp_card(c) for c in result["data"])
        st.session_state.messages.append({"role": "assistant", "content": "", "html": html})
    else:
        st.session_state.messages.append({"role": "assistant", "content": str(result["data"])})


def _classify_and_respond(query: str) -> None:
    if not is_llm_configured():
        st.session_state.messages.append(
            {
                "role": "assistant",
                "content": (
                    "LLM APIキーが未設定のため回答できません。Secrets または `.env` を確認して"
                    f" {config.LLM_PROVIDER} 用のAPIキーを設定してください。"
                ),
            }
        )
        return

    try:
        classification = intent_router.classify(query)
    except Exception as exc:  # noqa: BLE001
        st.session_state.messages.append(
            {"role": "assistant", "content": f"質問の分類中にエラーが発生しました: {exc}"}
        )
        return

    if classification.category == "ambiguous":
        st.session_state.pending_clarification = {
            "id": len(st.session_state.messages),
            "message": classification.clarification_message or "どちらの観点でお答えしましょうか？",
            "options": [
                {
                    "label": opt.label,
                    "route_to": opt.route_to,
                    "prefill_query": opt.prefill_query,
                }
                for opt in (classification.clarification_options or [])
            ],
        }
        return

    if classification.category == "theory":
        _respond_theory(query)
        return

    _respond_meta(query, classification.meta_subtype)


def _route_and_respond(query: str, route_to: str) -> None:
    st.session_state.messages.append({"role": "user", "content": query})
    if route_to == "theory":
        _respond_theory(query)
    elif route_to == "meta_item":
        _respond_meta(query, "item_build")
    elif route_to == "meta_comp":
        # 構成おすすめ・メタ比較へ正しくルーティング
        _respond_meta(query, "comp_recommendation")
    else:
        _classify_and_respond(query)


# ---------------------------------------------------------------------------
# 初期化
# ---------------------------------------------------------------------------
st.markdown(cards.get_base_css(), unsafe_allow_html=True)

if "messages" not in st.session_state:
    st.session_state.messages = []
if "pending_clarification" not in st.session_state:
    st.session_state.pending_clarification = None

# ---------------------------------------------------------------------------
# サイドバー
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("⚙️ 設定・ステータス")
    st.write(f"LLMプロバイダー: **{config.LLM_PROVIDER.upper()}**")
    if not is_llm_configured():
        st.warning("⚠️ APIキーが未設定です。Secrets / .env を確認してください。")

    try:
        patches = meta_service.list_available_patches()
    except Exception:  # noqa: BLE001
        patches = []
    current_patch = meta_service.get_current_patch()

    if patches:
        default_index = patches.index(current_patch) if current_patch in patches else 0
        selected_patch = st.selectbox("参照パッチ", patches, index=default_index)
        st.session_state.selected_patch = selected_patch
        try:
            data = meta_service.load_meta_data(selected_patch)
            st.caption(f"📊 Riot統計: {data.get('source', '不明')} / 更新: {data.get('updated_at', '不明')}")
        except Exception as exc:  # noqa: BLE001
            st.caption(f"データ読込エラー: {exc}")
    else:
        st.warning("パッチデータが見つかりません（data/patch_xx/ を確認してください）")
        st.session_state.selected_patch = None


# ---------------------------------------------------------------------------
# メイン画面
# ---------------------------------------------------------------------------
st.title("TFT Tactical Assistant")
st.caption("TFTのチャットアシスタント")

# 過去ログ表示
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        if msg.get("html"):
            st.markdown(msg["html"], unsafe_allow_html=True)
        if msg.get("content"):
            st.markdown(msg["content"])

# 曖昧時の選択肢ボタン
if st.session_state.pending_clarification:
    pending = st.session_state.pending_clarification
    with st.chat_message("assistant"):
        st.markdown(pending["message"])
        cols = st.columns(len(pending["options"]) or 1)
        for i, opt in enumerate(pending["options"]):
            if cols[i].button(opt["label"], key=f"clarify_{pending['id']}_{i}"):
                st.session_state.pending_clarification = None
                with st.spinner("アナリストが分析中..."):
                    _route_and_respond(opt["prefill_query"], opt["route_to"])
                st.rerun()

# 質問入力
query = st.chat_input(
    "TFTについて質問してください（例: ファスト8の手順 / アーリのビルド / 今の環境で強い構成は？）"
)
if query:
    # 1. 入力内容を即座に履歴へ追加 & 画面に描画
    st.session_state.messages.append({"role": "user", "content": query})
    with st.chat_message("user"):
        st.markdown(query)

    # 2. スピナーを表示しながら回答処理を実行
    with st.chat_message("assistant"):
        with st.spinner("回答を生成中..."):
            _classify_and_respond(query)

    st.rerun()
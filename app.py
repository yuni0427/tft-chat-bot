"""
TFT Strategy & Meta Advisor - Streamlitアプリ本体。

- タブ1: 3分岐ルーター（曖昧/理論/メタ）に基づくチャットUI
- タブ2: TFTAcademy 自動取得ティアリスト（プロ監修の最新メタ一覧）
"""
import streamlit as st

import config
from src.chains import intent_router, meta_chain, theory_chain
from src.llm.factory import is_llm_configured
from src.meta import meta_service
from src.meta.tftacademy_client import get_tftacademy_tierlist
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
        content += f"\n\n---\n参照ノート: {', '.join(result['sources'])}"
    st.session_state.messages.append({"role": "assistant", "content": content})


def _respond_meta(query: str, meta_subtype) -> None:
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
        st.session_state.messages.append({"role": "assistant", "content": result["data"]})


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
        _respond_meta(query, "comp_from_item_or_emblem")


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
    st.write("DEBUG google key exists:", bool(config.GOOGLE_API_KEY))
    st.write("DEBUG provider:", config.LLM_PROVIDER)
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
            st.caption(f"📊 Riotデータ: {data.get('source', '不明')} / 更新: {data.get('updated_at', '不明')}")
        except Exception as exc:  # noqa: BLE001
            st.caption(f"データ読込エラー: {exc}")
    else:
        st.warning("パッチデータが見つかりません（data/patch_xx/ を確認してください）")
        st.session_state.selected_patch = None

    st.divider()
    if st.button("ナレッジベースを再構築"):
        with st.spinner("再構築中..."):
            try:
                from src.rag.ingest import build_vector_db

                count = build_vector_db()
                st.success(f"{count}件のチャンクを再構築しました。")
            except Exception as exc:  # noqa: BLE001
                st.error(f"再構築に失敗しました: {exc}")

# ---------------------------------------------------------------------------
# メイン画面（タブ構造）
# ---------------------------------------------------------------------------
st.title("🧠 TFT Strategy & Meta Advisor")

tab_chat, tab_academy = st.tabs(["💬 戦略AIチャット", "🏆 TFTAcademy ティアリスト"])

# --- タブ1: AI チャット ---
with tab_chat:
    st.caption("立ち回り理論（RAG）と実戦マッチ統計を組み合わせてアドバイスします。")

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            if msg.get("html"):
                st.markdown(msg["html"], unsafe_allow_html=True)
            if msg.get("content"):
                st.markdown(msg["content"])

    if st.session_state.pending_clarification:
        pending = st.session_state.pending_clarification
        with st.chat_message("assistant"):
            st.markdown(pending["message"])
            cols = st.columns(len(pending["options"]) or 1)
            for i, opt in enumerate(pending["options"]):
                if cols[i].button(opt["label"], key=f"clarify_{pending['id']}_{i}"):
                    st.session_state.pending_clarification = None
                    _route_and_respond(opt["prefill_query"], opt["route_to"])
                    st.rerun()

    query = st.chat_input(
        "TFTについて質問してください（例: ファスト8の手順 / アッシュの装備 / スナイパーの紋章が出た）"
    )
    if query:
        st.session_state.messages.append({"role": "user", "content": query})
        _classify_and_respond(query)
        st.rerun()

# --- タブ2: TFTAcademy ティアリスト自動表示 ---
with tab_academy:
    st.subheader("🏆 TFTAcademy 最新メタ構成 (Auto-Synced)")
    st.caption("Dishsoap & Frodan 等のトッププロが推奨するティア表です（6時間ごとに自動更新）。")

    with st.spinner("TFTAcademy から最新データを取得中..."):
        tier_data = get_tftacademy_tierlist()

    if not tier_data:
        st.info("現在 TFTAcademy データを取得中、または一時的に取得できません。")
    elif isinstance(tier_data, dict):
        for tier_name, comps in tier_data.items():
            st.markdown(f"### Tier: {tier_name}")
            if isinstance(comps, list):
                for comp in comps:
                    if isinstance(comp, dict):
                        with st.expander(f"**{comp.get('name', '構成名')}** (難易度: {comp.get('difficulty', '普')})"):
                            st.write(f"**進行方針 / Level:** {comp.get('playstyle', 'Fast 8 / Standard')}")
                            carries = comp.get("carries", [])
                            st.write(f"**メインキャリー:** {', '.join(carries) if isinstance(carries, list) else carries}")
                            items = comp.get("items", [])
                            st.write(f"**推奨アイテム:** {', '.join(items) if isinstance(items, list) else items}")
                            if comp.get("notes"):
                                st.info(comp["notes"])
                    else:
                        st.write(f"- {comp}")
            else:
                st.write(str(comps))
    elif isinstance(tier_data, list):
        for item in tier_data:
            if isinstance(item, dict):
                tier_name = item.get("tier", "Unknown")
                comps = item.get("comps", [])
                st.markdown(f"### Tier: {tier_name}")
                if isinstance(comps, list):
                    for comp in comps:
                        if isinstance(comp, dict):
                            with st.expander(f"**{comp.get('name', '構成名')}**"):
                                st.write(f"**進行方針:** {comp.get('playstyle', '-')}")
                                carries = comp.get("carries", "-")
                                st.write(f"**メインキャリー:** {', '.join(carries) if isinstance(carries, list) else carries}")
                        else:
                            st.write(f"- {comp}")
                else:
                    st.write(str(comps))
            else:
                st.markdown(f"- {item}")
    else:
        st.write(tier_data)
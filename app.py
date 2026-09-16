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
    else:
        # guides リストを抽出
        guides = tier_data.get("guides", []) if isinstance(tier_data, dict) else tier_data

        if not guides:
            st.info("有効な構成データが見つかりませんでした。")
        else:
            # 名前のクレンジング関数 (例: DA_18_Ahri -> Ahri, DA_SpearOfShojin -> SpearOfShojin)
            def clean_name(api_name: str) -> str:
                if not api_name:
                    return "-"
                # プレフィックスの除去
                for prefix in ["DA_18_", "DA_", "TFT_"]:
                    if api_name.startswith(prefix):
                        api_name = api_name[len(prefix):]
                # 語尾のパッチ番号などの除去 (例: Karma18 -> Karma)
                if api_name.endswith("18"):
                    api_name = api_name[:-2]
                return api_name

            # Tierごとにグループ化
            grouped_comps = {}
            for comp in guides:
                if not isinstance(comp, dict):
                    continue
                tier = comp.get("tier", "Other").upper()
                grouped_comps.setdefault(tier, []).append(comp)

            # S, A, B, C, Other の優先順位でソート
            tier_order = ["S", "A", "B", "C", "OTHER"]
            sorted_tiers = sorted(grouped_comps.keys(), key=lambda x: tier_order.index(x) if x in tier_order else 99)

            for tier in sorted_tiers:
                st.markdown(f"### Tier: {tier}")
                for comp in grouped_comps[tier]:
                    title = comp.get("metaTitle") or comp.get("title", "構成名")
                    difficulty = comp.get("difficulty", "MEDIUM")
                    style = comp.get("style", "Standard")

                    # メインキャリーの取得
                    main_champ_info = comp.get("mainChampion", {})
                    main_champ_raw = main_champ_info.get("apiName", "") if isinstance(main_champ_info, dict) else ""
                    main_champ = clean_name(main_champ_raw)

                    # メインキャリーが finalComp で持っているアイテムを抽出
                    items = []
                    for board_unit in comp.get("finalComp", []):
                        if board_unit.get("apiName") == main_champ_raw:
                            items = [clean_name(it) for it in board_unit.get("items", [])]
                            break
                    items_str = ", ".join(items) if items else "状況に応じて配分"

                    with st.expander(f"**{title}** (難易度: {difficulty})"):
                        st.write(f"**進行方針 / Level:** {style}")
                        st.write(f"**メインキャリー:** {main_champ}")
                        st.write(f"**キャリー推奨アイテム:** {items_str}")

                        # 進行・立ち回りヒント
                        tips = comp.get("tips", [])
                        if tips and isinstance(tips, list):
                            st.write("**ステージ別立ち回り:**")
                            for tip_item in tips:
                                st.markdown(f"- **{tip_item.get('stage', '')}:** {tip_item.get('tip', '')}")

                        if comp.get("augmentsTip"):
                            st.info(f"💡 **運用Tips / オーグメント:** {comp['augmentsTip']}")
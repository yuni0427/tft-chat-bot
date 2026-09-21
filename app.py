"""
TFT Strategy & Meta Advisor - Streamlitアプリ本体。
立ち回り理論（RAG）と実戦マッチ統計・プロガイドを照合するAIチャットUI
"""
import uuid

import streamlit as st

import config
from src.chains import intent_router, meta_chain, theory_chain
from src.llm.factory import is_llm_configured
from src.meta import meta_service
from src.history import store as history_store
from src.ui import cards

st.set_page_config(
    page_title="TFT Tactical Assistant",
    page_icon="🦊",  # タブのファビコンをキツネに設定
    layout="wide",
)

# ---------------------------------------------------------------------------
# ヘルパー関数
# ---------------------------------------------------------------------------
def _respond_theory(query: str) -> None:
    try:
        result = theory_chain.answer(query)
    except Exception as exc:  # noqa: BLE001
        _append_message("assistant", f"回答生成中にエラーが発生しました: {exc}")
        return
    content = result["answer"]
    if result.get("sources"):
        content += f"\n\n---\n📚 **参照ノート:** {', '.join(result['sources'])}"
    _append_message("assistant", content)


def _respond_meta(query: str, meta_subtype: str | None) -> None:
    patch = st.session_state.get("selected_patch")
    try:
        result = meta_chain.handle_meta(query, meta_subtype, patch)
    except Exception as exc:  # noqa: BLE001
        _append_message("assistant", f"回答生成中にエラーが発生しました: {exc}")
        return

    res_data = result.get("data") if isinstance(result, dict) else result

    # None や空文字の場合は案内メッセージを表示
    if not res_data or str(res_data).strip().lower() in ("none", ""):
        content = (
            "申し訳ありません。該当するチャンピオンや構成のデータが見つかりませんでした。\n\n"
            "- チャンピオン名・構成名が正式名称や一般的な略称になっているか確認してください。\n"
            "- 実戦統計サンプルが極端に少ない駒の場合、データが生成されていない可能性があります。"
        )
    else:
        content = str(res_data)

    _append_message("assistant", content)


def _classify_and_respond(query: str) -> None:
    if not is_llm_configured():
        _append_message(
            "assistant",
            "LLM APIキーが未設定のため回答できません。Secrets または `.env` を確認して"
            f" {config.LLM_PROVIDER} 用のAPIキーを設定してください。",
        )
        return

    try:
        classification = intent_router.classify(query)
    except Exception as exc:  # noqa: BLE001
        _append_message("assistant", f"質問の分類中にエラーが発生しました: {exc}")
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
    _append_message("user", query)
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


def _get_owner_id() -> str | None:
    if config.AUTH_ENABLED:
        user = getattr(st, "user", None)
        if not user or not getattr(user, "is_logged_in", False):
            return None
        return getattr(user, "email", None) or getattr(user, "sub", None)
    if "anonymous_owner_id" not in st.session_state:
        st.session_state.anonymous_owner_id = f"anonymous:{uuid.uuid4()}"
    return st.session_state.anonymous_owner_id


def _append_message(role: str, content: str) -> None:
    st.session_state.messages.append({"role": role, "content": content})
    history_store.append_message(
        st.session_state.conversation_id,
        st.session_state.owner_id,
        role,
        content,
    )


def _prepare_conversation(conversation_id: str, owner_id: str) -> None:
    st.session_state.conversation_id = conversation_id
    st.session_state.owner_id = owner_id
    st.session_state.messages = history_store.load_messages(conversation_id, owner_id)


history_store.init_db()
owner_id = _get_owner_id()
if owner_id is None:
    st.title("TFT Tactical Assistant")
    st.info("ログインすると、会話タブと履歴をアカウントごとに保存できます。")
    if hasattr(st, "login"):
        st.login(config.AUTH_PROVIDER)
    else:
        st.error("Streamlitを更新するとログイン機能を利用できます。")
    st.stop()

st.session_state.owner_id = owner_id
conversations = history_store.list_conversations(owner_id)
if not conversations:
    history_store.create_conversation(owner_id)
    conversations = history_store.list_conversations(owner_id)

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
    if config.AUTH_ENABLED and hasattr(st, "logout"):
        st.button("ログアウト", on_click=st.logout)

    st.subheader("相談タブ")
    if st.button("＋ 新しいタブ", use_container_width=True):
        history_store.create_conversation(owner_id)
        st.rerun()
    st.caption(f"保存済み: {len(conversations)}件")
    selected_conversation_id = st.selectbox(
        "入力先のタブ",
        [conversation["id"] for conversation in conversations[:12]],
        format_func=lambda conversation_id: next(
            conversation["title"]
            for conversation in conversations
            if conversation["id"] == conversation_id
        ),
    )

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
# メイン画面: 会話ごとのタブ
# ---------------------------------------------------------------------------
st.title("TFT Tactical Assistant")
st.caption("TFTのチャットアシスタント")
tab_conversations = conversations[:12]
tabs = st.tabs([conversation["title"] for conversation in tab_conversations])

for tab, conversation in zip(tabs, tab_conversations):
    with tab:
        _prepare_conversation(conversation["id"], owner_id)
        st.caption(
            f"文脈世代 {conversation['context_epoch']} / "
            f"現在のターン {conversation['context_turns']} / "
            f"{config.MAX_CONTEXT_TURNS}ターンで文脈をリセット"
        )
        for msg in st.session_state.messages:
            if msg["role"] not in {"user", "assistant"}:
                continue
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

_prepare_conversation(selected_conversation_id, owner_id)
if st.session_state.pending_clarification:
    pending = st.session_state.pending_clarification
    with st.chat_message("assistant"):
        st.markdown(pending["message"])
        columns = st.columns(len(pending["options"]) or 1)
        for index, option in enumerate(pending["options"]):
            if columns[index].button(option["label"], key=f"clarify_{pending['id']}_{index}"):
                st.session_state.pending_clarification = None
                with st.spinner("アナリストが分析中..."):
                    _route_and_respond(option["prefill_query"], option["route_to"])
                st.rerun()

query = st.chat_input(
    "TFTについて質問してください（例: ファスト8の手順 / アーリのビルド）"
)
if query:
    _append_message("user", query)
    with st.chat_message("assistant"):
        with st.spinner("回答を生成中..."):
            _classify_and_respond(query)
    current = history_store.get_conversation(selected_conversation_id, owner_id)
    if current and current["context_turns"] >= config.MAX_CONTEXT_TURNS:
        history_store.reset_context(selected_conversation_id, owner_id)
        _append_message(
            "assistant",
            "一定ターン数に達したため、次の質問からLLMの会話文脈をリセットしました。保存済み履歴は残っています。",
        )
    st.rerun()
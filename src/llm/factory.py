"""
LLMプロバイダー（OpenAI / Gemini）を .env の設定に応じて切り替えるファクトリ。
LangChainのChatModel統一インターフェース(.invoke / .with_structured_output)を
利用するため、呼び出し側はプロバイダーの違いを意識しなくてよい。
"""
import config


def get_chat_model(temperature: float = 0.3):
    """設定されたLLM_PROVIDERに応じたLangChain ChatModelを返す。"""
    provider = config.LLM_PROVIDER

    if provider == "openai":
        if not config.OPENAI_API_KEY:
            raise RuntimeError(
                "OPENAI_API_KEY が設定されていません。.env を確認してください。"
            )
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=config.OPENAI_MODEL,
            api_key=config.OPENAI_API_KEY,
            temperature=temperature,
        )

    if provider == "gemini":
        if not config.GOOGLE_API_KEY:
            raise RuntimeError(
                "GOOGLE_API_KEY が設定されていません。.env を確認してください。"
            )
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(
            model=config.GEMINI_MODEL,
            google_api_key=config.GOOGLE_API_KEY,
            temperature=temperature,
        )

    raise ValueError(
        f"未対応の LLM_PROVIDER です: {provider!r}（'openai' または 'gemini' を指定してください）"
    )


def is_llm_configured() -> bool:
    """現在選択中のプロバイダーのAPIキーが設定済みかを返す（UIの警告表示用）。"""
    if config.LLM_PROVIDER == "openai":
        return bool(config.OPENAI_API_KEY)
    if config.LLM_PROVIDER == "gemini":
        return bool(config.GOOGLE_API_KEY)
    return False

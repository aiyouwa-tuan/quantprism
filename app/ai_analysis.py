"""
Goal-Driven Trading OS — AI Analysis
接入大模型进行智能分析（DeepSeek / Claude / Gemini / ChatGPT）
"""
import os
import json
import logging

logger = logging.getLogger(__name__)

# 支持的 AI 提供商
AI_PROVIDERS = {
    "deepseek": {
        "name": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "env_key": "DEEPSEEK_API_KEY",
    },
    "claude": {
        "name": "Claude (Anthropic)",
        "base_url": "https://api.anthropic.com/v1",
        "model": "claude-sonnet-4-20250514",
        "env_key": "ANTHROPIC_API_KEY",
    },
    "gemini": {
        "name": "Google Gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
        "model": "gemini-2.0-flash",
        "env_key": "GEMINI_API_KEY",
    },
    "openai": {
        "name": "ChatGPT (OpenAI)",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o",
        "env_key": "OPENAI_API_KEY",
    },
    "xai": {
        "name": "XAI (Grok)",
        "base_url": "https://api.x.ai/v1",
        "model": "grok-3",
        "env_key": "XAI_API_KEY",
    },
}


def get_active_provider() -> str:
    """检测哪个 AI 提供商有 API key 可用"""
    preferred = os.getenv("AI_PROVIDER", "deepseek")
    if preferred in AI_PROVIDERS:
        key = os.getenv(AI_PROVIDERS[preferred]["env_key"])
        if key:
            return preferred

    # Fallback: 试所有提供商
    for name, config in AI_PROVIDERS.items():
        if os.getenv(config["env_key"]):
            return name

    return None


# ---------------------------------------------------------------------------
# Multi-LLM routing: select best available model for given complexity
# ---------------------------------------------------------------------------
# Complexity tiers and preferred provider order
_ROUTING = {
    "cheap": ["gemini", "deepseek", "openai", "claude"],      # sentiment, news summary
    "standard": ["deepseek", "openai", "gemini", "claude"],   # technical, fundamental analysis
    "strong": ["claude", "openai", "deepseek", "gemini"],     # debate, verdict, risk review
}


def select_model(complexity: str) -> tuple[str, str]:
    """
    Route to best available model for the given complexity tier.
    如果用户在设置页指定了 AI_PROVIDER，该 provider 始终排在最前面。

    Args:
        complexity: "cheap" | "standard" | "strong"

    Returns:
        (provider_name, model_id) tuple, or raises RuntimeError if no key found.
    """
    order = list(_ROUTING.get(complexity, _ROUTING["standard"]))

    # 用户指定的 preferred provider 优先排第一
    preferred = os.getenv("AI_PROVIDER", "").strip()
    if preferred and preferred in AI_PROVIDERS:
        order = [preferred] + [p for p in order if p != preferred]

    for provider_name in order:
        config = AI_PROVIDERS.get(provider_name, {})
        if os.getenv(config.get("env_key", "")):
            return provider_name, config["model"]

    # Last resort: any available provider
    fallback = get_active_provider()
    if fallback:
        return fallback, AI_PROVIDERS[fallback]["model"]

    raise RuntimeError("未配置任何 AI API Key，无法运行多智能体分析")


def call_ai(prompt: str, complexity: str = "standard", system: str = None, max_tokens: int = 800) -> str:
    """
    Unified AI call with model routing and automatic provider fallback.
    """
    order = list(_ROUTING.get(complexity, _ROUTING["standard"]))
    preferred = os.getenv("AI_PROVIDER", "").strip()
    if preferred and preferred in AI_PROVIDERS:
        order = [preferred] + [p for p in order if p != preferred]

    last_error = None
    for provider in order:
        config = AI_PROVIDERS.get(provider, {})
        api_key = os.getenv(config.get("env_key", ""))
        if not api_key:
            continue
        model = config["model"]
        try:
            if provider in ("deepseek", "openai"):
                result = _call_openai_compatible(config["base_url"], api_key, model, prompt, provider,
                                                 system=system, max_tokens=max_tokens)
            elif provider == "claude":
                result = _call_claude(api_key, model, prompt, system=system, max_tokens=max_tokens)
            elif provider == "gemini":
                result = _call_gemini(api_key, model, prompt, max_tokens=max_tokens)
            else:
                continue
            if result.get("analysis"):
                return result["analysis"]
            last_error = result.get("error", "empty response")
        except Exception as e:
            last_error = str(e)
            logger.warning(f"call_ai: {provider} failed ({e}), trying next provider")
            continue

    raise RuntimeError(last_error or "所有 AI provider 均不可用")


def analyze_stock(symbol: str, diagnosis: dict, context: str = "") -> dict:
    """
    用 AI 分析一只标的

    Returns: {analysis, provider, model, error}
    """
    provider = get_active_provider()
    if not provider:
        return {"analysis": None, "error": "未配置 AI API Key。请在设置中配置 DeepSeek/Claude/Gemini/ChatGPT 的 API Key。"}

    config = AI_PROVIDERS[provider]
    api_key = os.getenv(config["env_key"])

    prompt = f"""分析以下股票的交易机会，用中文简洁回答：

标的: {symbol}
当前价格: ${diagnosis.get('current_price', 0):.2f}
趋势: {diagnosis.get('trend', 'unknown')}
RSI: {diagnosis.get('rsi', 0):.0f}
支撑位: ${diagnosis.get('support_level', 0):.2f}
安全边际: {diagnosis.get('safety_margin', 0)*100:.1f}%
评分: {diagnosis.get('score', 0)}/100

{context}

请回答：
1. 当前适合什么策略？（买正股/买Call/Sell Put/Covered Call/观望）
2. 如果做 Sell Put，建议什么行权价和到期日？
3. 主要风险是什么？
4. 一句话总结"""

    try:
        if provider == "deepseek" or provider == "openai":
            return _call_openai_compatible(config["base_url"], api_key, config["model"], prompt, provider)
        elif provider == "claude":
            return _call_claude(api_key, config["model"], prompt)
        elif provider == "gemini":
            return _call_gemini(api_key, config["model"], prompt)
        else:
            return {"analysis": None, "error": f"Unknown provider: {provider}"}
    except Exception as e:
        return {"analysis": None, "error": str(e), "provider": provider}


def _ai_timeout(max_tokens: int) -> int:
    """根据 max_tokens 动态计算超时（秒）：基础 20s + 每 100 token 约 4s，最少 30s"""
    return max(30, 20 + (max_tokens // 100) * 4)


def _call_openai_compatible(base_url: str, api_key: str, model: str, prompt: str, provider: str,
                            system: str = None, max_tokens: int = 500) -> dict:
    """调用 OpenAI 兼容 API (DeepSeek, ChatGPT)"""
    import httpx
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    with httpx.Client(trust_env=True, timeout=_ai_timeout(max_tokens)) as client:
        resp = client.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": 0.3},
        )
    data = resp.json()
    if "choices" in data:
        return {"analysis": data["choices"][0]["message"]["content"], "provider": provider, "model": model}
    return {"analysis": None, "error": data.get("error", {}).get("message", "Unknown error"), "provider": provider}


def _call_claude(api_key: str, model: str, prompt: str, system: str = None, max_tokens: int = 500) -> dict:
    """调用 Claude API"""
    import httpx
    payload = {"model": model, "max_tokens": max_tokens, "messages": [{"role": "user", "content": prompt}]}
    if system:
        payload["system"] = system
    with httpx.Client(trust_env=True, timeout=_ai_timeout(max_tokens)) as client:
        resp = client.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"},
            json=payload,
        )
    data = resp.json()
    if "content" in data:
        return {"analysis": data["content"][0]["text"], "provider": "claude", "model": model}
    return {"analysis": None, "error": data.get("error", {}).get("message", "Unknown error"), "provider": "claude"}


def _call_gemini(api_key: str, model: str, prompt: str, max_tokens: int = 500) -> dict:
    """调用 Gemini API"""
    import httpx
    with httpx.Client(trust_env=True, timeout=_ai_timeout(max_tokens)) as client:
        resp = client.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}",
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"maxOutputTokens": max_tokens},
            },
        )
    data = resp.json()
    if "candidates" in data:
        return {"analysis": data["candidates"][0]["content"]["parts"][0]["text"], "provider": "gemini", "model": model}
    return {"analysis": None, "error": str(data), "provider": "gemini"}

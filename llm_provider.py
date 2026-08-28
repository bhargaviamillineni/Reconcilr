"""
LLM provider abstraction layer.
Supports OpenAI, Gemini, and Groq. Configure via LLM_PROVIDER in .env.
API keys are loaded from environment variables only.
"""

import os
from dotenv import load_dotenv

load_dotenv()

PROVIDER = os.getenv("LLM_PROVIDER", "openai").lower()
REQUEST_TIMEOUT_SECONDS = 30


def check_provider_ready() -> tuple:
    """Checks if the configured provider has required package and API key.
    Returns (ready: bool, message: str)."""
    if PROVIDER == "groq":
        try:
            import openai  # Groq uses OpenAI SDK
        except ImportError:
            return False, "openai package not installed. Run: pip install openai"
        if not os.getenv("GROQ_API_KEY") or os.getenv("GROQ_API_KEY") == "your_groq_key_here":
            return False, "GROQ_API_KEY not set in .env"
        return True, "Groq provider ready"
    
    elif PROVIDER == "gemini":
        try:
            import google.generativeai  # noqa: F401
        except ImportError:
            return False, "google-generativeai package not installed. Run: pip install google-generativeai"
        if not os.getenv("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY") == "your_gemini_key_here":
            return False, "GEMINI_API_KEY not set in .env"
        return True, "Gemini provider ready"

    elif PROVIDER == "openai":
        try:
            import openai  # noqa: F401
        except ImportError:
            return False, "openai package not installed. Run: pip install openai"
        if not os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY") == "your_openai_key_here":
            return False, "OPENAI_API_KEY not set in .env"
        return True, "OpenAI provider ready"

    else:
        return False, f"Unknown LLM_PROVIDER '{PROVIDER}' -- use 'openai', 'gemini', or 'groq'"


def call_llm(prompt: str) -> str:
    """Sends prompt to configured provider, returns raw text response."""
    if PROVIDER == "groq":
        return _call_groq(prompt)
    elif PROVIDER == "gemini":
        return _call_gemini(prompt)
    elif PROVIDER == "openai":
        return _call_openai(prompt)
    else:
        raise ValueError(f"Unknown LLM_PROVIDER '{PROVIDER}' -- use 'openai', 'gemini', or 'groq'")


def _call_openai(prompt: str) -> str:
    from openai import OpenAI

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set in .env")

    client = OpenAI(api_key=api_key, timeout=REQUEST_TIMEOUT_SECONDS)
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )
    return response.choices[0].message.content.strip()


def _call_groq(prompt: str) -> str:
    """Calls Groq API using OpenAI SDK."""
    from openai import OpenAI

    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY not set in .env")

    client = OpenAI(
        api_key=api_key,
        base_url="https://api.groq.com/openai/v1",
        timeout=REQUEST_TIMEOUT_SECONDS
    )
    model = os.getenv("GROQ_MODEL", "llama-3.1-70b-versatile")

    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )
    return response.choices[0].message.content.strip()


def _call_gemini(prompt: str) -> str:
    import google.generativeai as genai

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set in .env")

    genai.configure(api_key=api_key)
    model_name = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
    if model_name.startswith("models/"):
        model_name = model_name.replace("models/", "")
    model = genai.GenerativeModel(model_name)

    response = model.generate_content(
        prompt,
        generation_config={"temperature": 0},
        request_options={"timeout": REQUEST_TIMEOUT_SECONDS},
    )
    return response.text.strip()

import streamlit as st
import requests
import time


def model_status_banner(api_base_url: str, headers: dict) -> dict:
    """
    Poll /health/models and display per-model status cards.

    Returns a dict with:
        all_ready (bool): True if all models are ready
        embedder_ready (bool): True if embedder is ready
        llm_ready (bool): True if LLM is ready
        cross_encoder_ready (bool): True if cross-encoder is ready
        dspy_lm_ready (bool): True if DSPy LM is ready
        models_data (dict): The full /health/models response dict
    """
    # Default return when bailing out early
    _default_models = {
        "cross_encoder": {"status": "unknown"},
        "llm": {"status": "unknown"},
        "embedder": {"status": "unknown"},
        "dspy_lm": {"status": "unknown"},
    }

    # Initialize session state keys if missing
    if "models_ready" not in st.session_state:
        st.session_state.models_ready = False
    if "models_permanent_error" not in st.session_state:
        st.session_state.models_permanent_error = False
    if "models_poll_count" not in st.session_state:
        st.session_state.models_poll_count = 0

    # Early exit: all models already known to be ready
    if st.session_state.models_ready:
        return {
            "all_ready": True,
            "embedder_ready": True,
            "llm_ready": True,
            "cross_encoder_ready": True,
            "dspy_lm_ready": True,
            "models_data": st.session_state.get("models_data", _default_models),
        }

    # Early exit: permanent error already detected
    if st.session_state.models_permanent_error:
        models_data = st.session_state.get("models_data", _default_models)
        return {
            "all_ready": False,
            "embedder_ready": models_data.get("embedder", {}).get("status") == "ready",
            "llm_ready": models_data.get("llm", {}).get("status") == "ready",
            "cross_encoder_ready": models_data.get("cross_encoder", {}).get("status") == "ready",
            "dspy_lm_ready": models_data.get("dspy_lm", {}).get("status") == "ready",
            "models_data": models_data,
        }

    models_placeholder = st.empty()

    try:
        health_resp = requests.get(f"{api_base_url}/health/models", timeout=2, headers=headers)
        if health_resp.status_code == 200:
            model_data = health_resp.json()

            # Cache in session state for downstream callers
            st.session_state.models_data = model_data

            all_ready = True
            any_permanent_error = False
            any_loading = False

            model_display = [
                ("cross_encoder", "Cross-Encoder Reranker"),
                ("llm", "Language Model (MLX)"),
                ("embedder", "Embedding Model"),
                ("dspy_lm", "DSPy LM Adapter"),
            ]

            with models_placeholder.container():
                st.markdown("### 🤖 Loading AI Models...")

                for model_key, display_name in model_display:
                    model_info = model_data.get(model_key, {})
                    status = model_info.get("status", "loading")
                    progress = model_info.get("progress", 0)
                    error = model_info.get("error")
                    message = model_info.get("message", "")
                    model_name = model_info.get("model", "")

                    if status == "ready":
                        icon = "✅"
                        all_ready = all_ready and True
                    elif status == "permanent_error":
                        icon = "❌"
                        all_ready = False
                        any_permanent_error = True
                    elif status == "error":
                        icon = "⚠️"
                        all_ready = False
                        any_loading = True
                    else:
                        icon = "🔄"
                        all_ready = False
                        any_loading = True

                    # Progress bar
                    st.markdown(f"**{icon} {display_name}**")
                    st.progress(int(progress) if progress else 0)

                    # Status message
                    if status == "ready":
                        st.caption(f"✅ {message or 'Ready'}")
                    elif status == "permanent_error":
                        st.caption(f"❌ {error or 'Failed — please restart the server'}")
                    elif status == "error":
                        retry_msg = message or "Error — retrying..."
                        st.caption(f"⚠️ {retry_msg}")
                    else:
                        loading_msg = message or "Loading..."
                        st.caption(f"🔄 {loading_msg}")

                if any_permanent_error:
                    st.error(
                        "⚠️ A model has permanently failed. Please restart the server or contact support. "
                        "The application may not function correctly."
                    )
                    st.session_state.models_permanent_error = True

            if all_ready:
                st.session_state.models_ready = True
                models_placeholder.empty()
                return {
                    "all_ready": True,
                    "embedder_ready": True,
                    "llm_ready": True,
                    "cross_encoder_ready": True,
                    "dspy_lm_ready": True,
                    "models_data": model_data,
                }
            else:
                st.session_state.models_poll_count = st.session_state.get("models_poll_count", 0) + 1
                if st.session_state.models_poll_count >= 50:
                    st.session_state.models_permanent_error = True
                    models_placeholder.empty()
                    st.error(
                        "⚠️ Models are taking too long to load. The application may not function correctly. "
                        "Please try restarting the server."
                    )
                else:
                    time.sleep(1.0)
                    st.rerun()

    except requests.RequestException:
        st.session_state.models_poll_count = st.session_state.get("models_poll_count", 0) + 1
        if st.session_state.models_poll_count >= 50:
            st.session_state.models_permanent_error = True
            models_placeholder.empty()
            st.error(
                "⚠️ Unable to connect to model service after multiple retries. "
                "The application may not function correctly."
            )
        else:
            time.sleep(1.0)
            st.rerun()

    # Fallback return (should only be reached during permanent_error early-exit path)
    models_data = st.session_state.get("models_data", _default_models)
    return {
        "all_ready": st.session_state.get("models_ready", False),
        "embedder_ready": models_data.get("embedder", {}).get("status") == "ready" or st.session_state.get("models_ready", False),
        "llm_ready": models_data.get("llm", {}).get("status") == "ready" or st.session_state.get("models_ready", False),
        "cross_encoder_ready": models_data.get("cross_encoder", {}).get("status") == "ready" or st.session_state.get("models_ready", False),
        "dspy_lm_ready": models_data.get("dspy_lm", {}).get("status") == "ready" or st.session_state.get("models_ready", False),
        "models_data": models_data,
    }

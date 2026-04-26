import streamlit as st


def render_message(role: str, content: str, sources: list = None):
    if role == "user":
        with st.chat_message("user"):
            st.markdown(content)
    else:
        with st.chat_message("assistant"):
            st.markdown(content)
            
            if sources:
                with st.expander("📚 Sources"):
                    for i, source in enumerate(sources, 1):
                        st.markdown(f"**Source {i}:**")
                        st.caption(source.get("content", "")[:300] + "..." if len(source.get("content", "")) > 300 else source.get("content", ""))
                        st.divider()

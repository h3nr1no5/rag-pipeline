import streamlit as st
from PIL import Image, ImageDraw


def create_colored_avatar(hex_color: str, emoji: str = "🤖", size: int = 50) -> Image.Image:
    """Create a colored circle avatar with emoji text."""
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # Parse hex color
    hex_color = hex_color.lstrip('#')
    rgb = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
    
    # Draw filled circle
    draw.ellipse([2, 2, size - 2, size - 2], fill=(*rgb, 255))
    
    return img


def render_message(role: str, content: str, sources: list = None, avatar_img: Image.Image = None):
    if role == "user":
        with st.chat_message("user"):
            st.markdown(content)
    else:
        if avatar_img:
            with st.chat_message("assistant", avatar=avatar_img):
                st.markdown(content)
        else:
            with st.chat_message("assistant"):
                st.markdown(content)
            
        if sources:
            with st.expander("📚 Sources"):
                for i, source in enumerate(sources, 1):
                    st.markdown(f"**Source {i}:**")
                    content_text = source.get("content", "")
                    st.caption(content_text[:300] + "..." if len(content_text) > 300 else content_text)
                    if i < len(sources):
                        st.divider()

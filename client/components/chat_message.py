import re
import streamlit as st
from PIL import Image, ImageDraw


def strip_markdown_formatting(content: str) -> str:
    """Remove Markdown formatting from text to prevent rendering issues.
    
    Strips headers, bold, italic, strikethrough, and horizontal rules
    while preserving bullet list markers.
    """
    # Remove # markers at the start of lines (and their trailing space)
    content = re.sub(r'^#+\s+', '', content, flags=re.MULTILINE)
    # Remove horizontal rules on their own line
    content = re.sub(r'^[\s]*[-*_]{3,}[\s]*$', '', content, flags=re.MULTILINE)
    # Remove bold (**text**)
    content = re.sub(r'\*\*(.+?)\*\*', r'\1', content)
    # Remove bold (__text__)
    content = re.sub(r'__(.+?)__', r'\1', content)
    # Remove italic (*text*) but not **
    content = re.sub(r'(?<!\*)\*([^*\n]+?)\*(?!\*)', r'\1', content)
    # Remove italic (_text_) but not __
    content = re.sub(r'(?<!_)_([^_\n]+?)_(?!_)', r'\1', content)
    # Remove strikethrough (~~text~~)
    content = re.sub(r'~~(.+?)~~', r'\1', content)
    return content


def create_colored_avatar(hex_color: str, size: int = 50) -> Image.Image:
    """Create a simple colored circle avatar."""
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # Parse hex color
    hex_color = hex_color.lstrip('#')
    rgb = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
    
    # Draw filled circle
    draw.ellipse([2, 2, size - 2, size - 2], fill=(*rgb, 255))
    
    return img


def render_message(role: str, content: str, sources: list = None, avatar_img: Image.Image = None, label: str = None):
    content = strip_markdown_formatting(content)
    if label:
        content = f"**{label}**\n\n{content}"
    
    if role == "user":
        if avatar_img:
            with st.chat_message("user", avatar=avatar_img):
                st.markdown(content)
        else:
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
"""
Authentication module for Medical CAT Translator
Provides password protection for the web interface
"""

import streamlit as st
import hashlib
import os

# Default password - CHANGE THIS TO YOUR SECURE PASSWORD
# Format: sha256 hash of the password
DEFAULT_PASSWORD_HASH = hashlib.sha256("medtranslator2026".encode()).hexdigest()

def get_password_hash(password: str) -> str:
    """Generate SHA256 hash of password"""
    return hashlib.sha256(password.encode()).hexdigest()

def check_password() -> bool:
    """
    Show password login form if not authenticated.
    Returns True if user is authenticated, False otherwise.
    """

    # Check if already authenticated in session
    if "authenticated" in st.session_state and st.session_state.authenticated:
        return True

    # Show login form
    st.set_page_config(
        page_title="Medical CAT Translator - Login",
        page_icon="🔐",
        layout="centered"
    )

    # Center the login form
    col1, col2, col3 = st.columns([1, 2, 1])

    with col2:
        st.markdown("---")
        st.markdown("## 🔐 Medical CAT Translator v5.5")
        st.markdown("**Advanced Medical Document Translation System**")
        st.markdown("---")

        password = st.text_input(
            "Enter password:",
            type="password",
            placeholder="Enter your password",
            key="password_input"
        )

        col_left, col_right = st.columns(2)

        with col_left:
            if st.button("🔓 Login", use_container_width=True):
                password_hash = get_password_hash(password)

                if password_hash == DEFAULT_PASSWORD_HASH:
                    st.session_state.authenticated = True
                    st.success("✅ Login successful!")
                    st.rerun()
                else:
                    st.error("❌ Incorrect password. Please try again.")

        with col_right:
            if st.button("ℹ️ Help", use_container_width=True):
                st.info(
                    "**Default password:** medtranslator2026\n\n"
                    "Contact administrator to change password."
                )

        st.markdown("---")
        st.markdown(
            "<p style='text-align: center; color: #888;'>"
            "Medical CAT Translator v5.5 | Production Ready | 2026"
            "</p>",
            unsafe_allow_html=True
        )

    return False

def logout():
    """Log out the user"""
    st.session_state.authenticated = False
    st.rerun()

def show_logout_button():
    """Show logout button in sidebar"""
    if "authenticated" in st.session_state and st.session_state.authenticated:
        with st.sidebar:
            st.divider()
            if st.button("🔐 Logout", use_container_width=True):
                logout()

def set_password(new_password: str):
    """
    Update the password hash.
    WARNING: This is for development only. In production, use environment variables.

    Usage:
        set_password("new_secure_password")
    """
    global DEFAULT_PASSWORD_HASH
    DEFAULT_PASSWORD_HASH = get_password_hash(new_password)
    st.success(f"✅ Password updated!")

def get_password_from_env():
    """
    Get password from environment variable if set.
    Environment variable: STREAMLIT_PASSWORD

    Example in Streamlit Cloud secrets:
        STREAMLIT_PASSWORD = "your_secure_password"
    """
    env_password = os.getenv("STREAMLIT_PASSWORD")
    if env_password:
        global DEFAULT_PASSWORD_HASH
        DEFAULT_PASSWORD_HASH = get_password_hash(env_password)

# Load password from environment on module import
get_password_from_env()

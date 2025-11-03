from typing import List
import streamlit as st
from st_supabase_connection import SupabaseConnection

def get_db_connection():
    try:
        # use the connection defined in secrets.toml
        conn = st.connection("supabase", type=SupabaseConnection)
        return conn
    except Exception as e:
        st.error(f"Error connecting to Supabase: {e}")
        raise

def initialize_database():
    """Initialize the database with required tables"""
    conn = get_db_connection()
    pass

def get_departments() -> List[str]:
    return [
        "Computer Science Engineering",
        "Artificial Intelligence and Data Science",
        "Computer Science and Business Systems",
        "Electronics and Communications Engineering",
        "Mechanical Engineering",
        "Civil Engineering"
    ]
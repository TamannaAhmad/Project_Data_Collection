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

# Department code mapping
def get_department_code(department_name: str) -> str:
    """Get department code from department name"""
    dept_mapping = {
        "Computer Science Engineering": "CS",
        "Artificial Intelligence and Data Science": "AD",
        "Computer Science and Business Systems": "CB", 
        "Electronics and Communications Engineering": "EC",
        "Mechanical Engineering": "ME",
        "Civil Engineering": "CV"
    }
    return dept_mapping.get(department_name, "XX")

def get_departments() -> List[str]:
    return [
        "Computer Science Engineering (CS)",
        "Artificial Intelligence and Data Science (AD)",
        "Computer Science and Business Systems (CB)",
        "Electronics and Communications Engineering (EC)",
        "Mechanical Engineering (ME)",
        "Civil Engineering (CV)"
    ]
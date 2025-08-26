from datetime import time
from typing import List, Dict, Any
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
        "Mechanical Engineering Engineering",
        "Civil Engineering Engineering"
    ]

def get_skills(custom_skills: set = None) -> List[str]:
    """Get all skills from database, optionally including custom skills"""
    conn = get_db_connection()
    try:
        result = conn.table('skills').select('name').order('name').execute()
        db_skills = [row['name'] for row in result.data]
        
        if custom_skills:
            all_skills = sorted(set(db_skills).union(custom_skills))
        else:
            all_skills = sorted(db_skills)
            
        return all_skills
    except Exception as e:
        st.error(f"Error fetching skills: {e}")
        return []
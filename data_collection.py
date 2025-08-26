import streamlit as st
from db_connection import get_db_connection, get_departments, get_skills, initialize_database
from datetime import time
from typing import List, Dict, Any
from streamlit_tags import st_tags

# Page config
st.set_page_config(
    page_title="ScholarX - User Data Collection",
    page_icon="🎓",
    layout="wide"
)

# Initialize session state
if 'form_submitted' not in st.session_state:
    st.session_state.form_submitted = False

if 'current_step' not in st.session_state:
    st.session_state.current_step = 'personal_info'

# Initialize database
initialize_database()

# Initialize the connection
@st.cache_resource
def init_connection():
    return get_db_connection()

conn = init_connection()

# Constants
TIME_SLOTS = [
    (time(9, 0), time(12, 0)),   # 9 AM - 12 PM
    (time(13, 0), time(16, 0)),  # 1 PM - 4 PM
    (time(17, 0), time(20, 0)),  # 5 PM - 8 PM
    (time(21, 0), time(23, 59))  # 9 PM - 12 AM
]
DAYS_OF_WEEK = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
DAY_TO_INT = {day: i for i, day in enumerate(DAYS_OF_WEEK)}

def create_availability_grid() -> Dict[str, List[bool]]:
    """Create an empty availability grid"""
    return {day: [False] * len(TIME_SLOTS) for day in DAYS_OF_WEEK}

# Initialize form data in session state
if 'initialized' not in st.session_state:
    st.session_state.initialized = True
    st.session_state.form_data = {
        'availability': create_availability_grid(),
        'avoid_times': create_availability_grid(),
        'skills': []
    }

@st.cache_data(ttl=3600)  # Cache for 1 hour
def get_skills_from_db() -> List[str]:
    """Get all skills from database"""
    try:
        conn = get_db_connection()
        result = conn.table('skills').select('name').order('name').execute()
        return [row['name'] for row in result.data]
    except Exception as e:
        st.error(f"Error fetching skills: {e}")
        return []

def save_user_data(form_data: Dict[str, Any]) -> bool:
    """Save or update user data in the database"""
    conn = get_db_connection()
    
    try:
        # Prepare user data
        user_data = {
            'usn': form_data['usn'].upper(),
            'first_name': form_data['first_name'],
            'last_name': form_data['last_name'],
            'department': form_data['department'],
            'year': form_data['year']
        }
        
        # Upsert user data using Supabase methods
        conn.table('sample_users').upsert(user_data, on_conflict='usn').execute()
        
        # Handle skills
        existing_skills = {}
        
        # Get existing skills for this user
        result = conn.table('sample_user_skills').select('skill_id').eq('usn', user_data['usn']).execute()
        existing_skill_ids = {row['skill_id'] for row in result.data}
        
        # Process new skills
        for skill_data in form_data['skills']:
            skill_name = skill_data['name'].strip()
            if not skill_name:
                continue
                
            # Check if skill exists in the main skills table
            skill_result = conn.table('skills').select('skill_id').eq('name', skill_name).execute()
            
            if not skill_result.data:
                # Insert new skill if it doesn't exist
                new_skill = conn.table('skills').insert({'name': skill_name}).execute()
                skill_id = new_skill.data[0]['skill_id']
            else:
                skill_id = skill_result.data[0]['skill_id']
            
            # Check if user already has this skill
            if skill_id not in existing_skill_ids:
                # Insert new user-skill relationship
                user_skill_data = {
                    'usn': user_data['usn'],
                    'skill_id': skill_id,
                    'proficiency_level': skill_data['proficiency_level']
                }
                conn.table('sample_user_skills').insert(user_skill_data).execute()
            else:
                # Update existing skill proficiency
                conn.table('sample_user_skills').update({
                    'proficiency_level': skill_data['proficiency_level']
                }).eq('usn', user_data['usn']).eq('skill_id', skill_id).execute()
        
        # Handle availability - first clear existing availability for this user
        conn.table('sample_user_availability').delete().eq('usn', user_data['usn']).execute()
        
        availability_records = []
        
        # Handle availability - convert time slots to start/end times and day names to integers
        for day, slots in form_data['availability'].items():
            day_int = DAY_TO_INT[day]
            for i, is_available in enumerate(slots):
                if is_available:
                    start_time = TIME_SLOTS[i][0]
                    end_time = TIME_SLOTS[i][1]
                    availability_records.append({
                        'usn': user_data['usn'],
                        'day_of_week': day_int,
                        'time_slot_start': start_time.strftime('%H:%M:%S'),
                        'time_slot_end': end_time.strftime('%H:%M:%S'),
                        'is_available': True
                    })
        
        # Handle avoid times
        for day, slots in form_data['avoid_times'].items():
            day_int = DAY_TO_INT[day]
            for i, is_avoided in enumerate(slots):
                if is_avoided:
                    start_time = TIME_SLOTS[i][0]
                    end_time = TIME_SLOTS[i][1]
                    availability_records.append({
                        'usn': user_data['usn'],
                        'day_of_week': day_int,
                        'time_slot_start': start_time.strftime('%H:%M:%S'),
                        'time_slot_end': end_time.strftime('%H:%M:%S'),
                        'is_available': False
                    })
        
        # Insert all availability records at once
        if availability_records:
            conn.table('sample_user_availability').insert(availability_records).execute()
        
        return True
            
    except Exception as e:
        # Re-raise the exception to be handled by the caller
        raise e

def render_availability_grid(grid_name: str, title: str):
    """Render a grid for availability or avoid times"""
    st.subheader(title)
    
    # Create columns for each day
    cols = st.columns(len(DAYS_OF_WEEK) + 1)  # +1 for time labels
    
    # Time labels
    with cols[0]:
        st.write("Time")
        for start, end in TIME_SLOTS:
            st.write(f"{start.strftime('%I:%M %p')} - {end.strftime('%I:%M %p')}")
    
    # Day columns with checkboxes
    for day_idx, day in enumerate(DAYS_OF_WEEK, 1):
        with cols[day_idx]:
            st.write(day)
            for time_idx, (start, end) in enumerate(TIME_SLOTS):
                # Create a unique key for each checkbox
                key = f"{grid_name}_{day}_{time_idx}"
                checked = st.session_state.form_data[grid_name][day][time_idx]
                
                # Update session state when checkbox is toggled
                if st.checkbox(
                    "",
                    key=key,
                    value=checked,
                    label_visibility="collapsed"
                ):
                    st.session_state.form_data[grid_name][day][time_idx] = True
                else:
                    st.session_state.form_data[grid_name][day][time_idx] = False

def add_new_skill_to_db(skill_name: str) -> bool:
    """Add a new skill to the database if it doesn't exist"""
    try:
        conn = get_db_connection()
        # Check if skill already exists
        result = conn.table('skills').select('skill_id').ilike('name', skill_name.strip()).execute()
        if not result.data:
            # Add new skill
            conn.table('skills').insert({'name': skill_name.strip().title()}).execute()
        return True
    except Exception as e:
        st.error(f"Error adding skill to database: {e}")
        return False

def render_skills_section():
    """Render the skills section outside of any form"""
    st.header("Skills")
    
    # Get all skills from the database for suggestions
    all_skills = get_skills_from_db()
    
    # Initialize skills in session state if not present
    if 'skills' not in st.session_state.form_data:
        st.session_state.form_data['skills'] = []
    
    skills = st.session_state.form_data['skills']
    
    # Add new skill section
    st.subheader("Add Skills")
    col1, col2 = st.columns([3, 1])
    
    with col1:
        # Use selectbox with option to add custom skill
        skill_options = [""] + all_skills + ["+ Add Custom Skill"]
        selected_skill = st.selectbox(
            "Select or type a skill",
            options=skill_options,
            key="skill_selector",
            help="Start typing to search, or select '+ Add Custom Skill' to add a new one"
        )
        
        # If custom skill option is selected, show text input
        if selected_skill == "+ Add Custom Skill":
            custom_skill = st.text_input(
                "Enter custom skill name",
                key="custom_skill_input",
                placeholder="e.g., Machine Learning, React.js"
            )
            skill_to_add = custom_skill.strip().title() if custom_skill else ""
        else:
            skill_to_add = selected_skill
    
    with col2:
        proficiency_level = st.slider(
            "Proficiency Level",
            min_value=0,
            max_value=5,
            value=3,
            key="new_skill_proficiency",
            help="0 = Yet to Start, 1-2 = Learning, 3-5 = Proficient"
        )
    
    # Add skill button
    if st.button("Add Skill", key="add_skill_btn"):
        if skill_to_add:
            # Check if skill already added
            existing_skill_names = [s['name'].lower() for s in skills]
            if skill_to_add.lower() not in existing_skill_names:
                # Add to database if it's a custom skill
                if skill_to_add not in all_skills:
                    add_new_skill_to_db(skill_to_add)
                
                # Add to user's skills
                skills.append({
                    'name': skill_to_add,
                    'proficiency_level': proficiency_level
                })
                st.session_state.form_data['skills'] = skills
                st.success(f"Added {skill_to_add}")
                st.rerun()
            else:
                st.warning("This skill is already in your list")
        else:
            st.warning("Please enter a skill name")
    
    # Display current skills
    if skills:
        st.subheader("Your Skills")
        
        # Create a container for the skills to prevent layout shifts
        skills_container = st.container()
        
        with skills_container:
            for i, skill_data in enumerate(skills):
                col1, col2, col3 = st.columns([3, 2, 1])
                with col1:
                    st.write(f"**{skill_data['name']}**")
                with col2:
                    # Use a unique key that includes skill name to prevent conflicts
                    new_proficiency = st.slider(
                        "Proficiency",
                        min_value=0,
                        max_value=5,
                        value=skill_data.get('proficiency_level', 3),
                        key=f"skill_prof_{i}_{skill_data['name']}",
                        help="0 = Yet to Start, 1-2 = Learning, 3-5 = Proficient"
                    )
                    # Update proficiency in real-time
                    if new_proficiency != skill_data.get('proficiency_level', 3):
                        st.session_state.form_data['skills'][i]['proficiency_level'] = new_proficiency
                
                with col3:
                    if st.button("Remove", key=f"remove_skill_{i}_{skill_data['name']}"):
                        st.session_state.form_data['skills'].pop(i)
                        st.success(f"Removed {skill_data['name']}")
                        st.rerun()
    
    # Continue button
    st.markdown("---")
    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("← Back to Personal Info"):
            st.session_state.current_step = 'personal_info'
            st.rerun()
    
    with col2:
        if st.button("Continue to Availability →", type="primary"):
            if not st.session_state.form_data.get('skills'):
                st.error("Please add at least one skill before continuing.")
            else:
                st.session_state.current_step = 'availability'
                st.rerun()

def main():
    st.title("🎓 ScholarX - User Data Collection")
    
    if st.session_state.form_submitted:
        st.success("Thank you for submitting your information!")
        if st.button("Submit another response"):
            st.session_state.form_submitted = False
            st.session_state.current_step = 'personal_info'
            st.session_state.form_data = {
                'availability': create_availability_grid(),
                'avoid_times': create_availability_grid(),
                'skills': []
            }
            st.rerun()
        return
    
    # Step 1: Personal Information
    if st.session_state.current_step == 'personal_info':
        with st.form("personal_info_form"):
            st.header("Personal Information")
            
            # Basic info
            col1, col2 = st.columns(2)
            with col1:
                usn = st.text_input("USN (10 characters)", 
                                  max_chars=10,
                                  value=st.session_state.form_data.get('usn', ''),
                                  help="Enter your 10-character University Seat Number")
                
                first_name = st.text_input("First Name",
                                         value=st.session_state.form_data.get('first_name', ''))
            
            with col2:
                last_name = st.text_input("Last Name",
                                        value=st.session_state.form_data.get('last_name', ''))
                
                department = st.selectbox(
                    "Department",
                    get_departments(),
                    index=get_departments().index(st.session_state.form_data.get('department', 'Computer Science')) 
                    if st.session_state.form_data.get('department') in get_departments() 
                    else 0
                )
                
                year = st.selectbox(
                    "Year of Study",
                    [1, 2, 3, 4],
                    index=st.session_state.form_data.get('year', 1) - 1 if 'year' in st.session_state.form_data else 0
                )
            
            submitted = st.form_submit_button("Continue to Skills", type="primary")
            
            if submitted:
                # Form validation
                if not all([usn, first_name, last_name]):
                    st.error("Please fill in all required fields.")
                elif len(usn) != 10:
                    st.error("USN must be exactly 10 characters long.")
                else:
                    # Save personal info to session state
                    st.session_state.form_data.update({
                        'usn': usn.upper(),
                        'first_name': first_name,
                        'last_name': last_name,
                        'department': department,
                        'year': year
                    })
                    st.session_state.current_step = 'skills'
                    st.rerun()
    
    # Step 2: Skills (outside of form to allow buttons)
    elif st.session_state.current_step == 'skills':
        render_skills_section()
    
    # Step 3: Availability
    elif st.session_state.current_step == 'availability':
        st.header("Availability")
        
        # Back button
        if st.button("← Back to Skills"):
            st.session_state.current_step = 'skills'
            st.rerun()
        
        with st.form("availability_form"):
            st.info("Please select all time slots when you are typically available for study groups.")
            render_availability_grid('availability', "Available Times")
            
            st.header("Times to Avoid")
            st.info("Please select all time slots when you are typically NOT available for study groups.")
            render_availability_grid('avoid_times', "Unavailable Times")
            
            # Final submit button
            if st.form_submit_button("Submit All Information", type="primary"):
                try:
                    if save_user_data(st.session_state.form_data):
                        st.session_state.form_submitted = True
                        st.rerun()
                except Exception as e:
                    error_msg = str(e).lower()
                    if "duplicate key" in error_msg:
                        st.error("This USN is already registered. Please use a different USN or contact support if you need to update your information.")
                    elif "connection" in error_msg or "database" in error_msg:
                        st.error("Could not connect to the database. Please check your internet connection and try again.")
                    elif "violates foreign key constraint" in error_msg:
                        st.error("There was an issue with the selected department or year. Please refresh the page and try again.")
                    else:
                        st.error(f"An unexpected error occurred. Please try again or contact support if the issue persists.")
                    st.error("Detailed error for support: " + str(e))

if __name__ == "__main__":
    main()
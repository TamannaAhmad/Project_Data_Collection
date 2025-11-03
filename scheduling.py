import pandas as pd
from typing import List, Dict, Set, Optional, Tuple
from collections import defaultdict
import itertools
from datetime import datetime, time
import json

# Database imports (choose one based on your preference)
# Option 1: PostgreSQL with psycopg2
import psycopg2
from psycopg2.extras import RealDictCursor

# Option 2: Supabase
from supabase import create_client, Client

# Option 3: SQLAlchemy (works with both PostgreSQL and Supabase)
# from sqlalchemy import create_engine, text
# import os

class WebScheduleMatcher:
    """
    Web-Ready Schedule Matcher for Team Formation

    Features:
    - Database integration (PostgreSQL/Supabase) using existing schema
    - Profile recommendation with schedule match percentage
    - Team meeting time suggestions
    - RESTful API ready
    - Sunday as first day (0=Sunday, 1=Monday, etc. - matching your schema)
    """

    def __init__(self, db_config: Optional[Dict] = None):
        # Updated time slots - 12 slots covering full day (00:00 to 23:59)
        self.time_slots = [
            ("00:00", "02:00"), ("02:00", "04:00"), ("04:00", "06:00"), ("06:00", "08:00"),
            ("08:00", "10:00"), ("10:00", "12:00"), ("12:00", "14:00"), ("14:00", "16:00"),
            ("16:00", "18:00"), ("18:00", "20:00"), ("20:00", "22:00"), ("22:00", "00:00")
        ]

        # Days mapping to match your schema (0=Sunday, 1=Monday, etc.)
        self.days = ['sunday', 'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday']
        self.day_numbers = {day: idx for idx, day in enumerate(self.days)}

        self.db_config = db_config
        self.db_connection = None

        # Cache for frequently accessed data
        self.users_cache = {}
        self.cache_timestamp = None

    # ===========================================
    # DATABASE INTEGRATION METHODS
    # ===========================================

    def connect_to_database(self) -> bool:
        """
        Connect to PostgreSQL or Supabase database
        Choose one of the implementation options below
        """
        try:
            # OPTION 1: Direct PostgreSQL connection
            if self.db_config and self.db_config.get('type') == 'postgresql':
                import psycopg2
                from psycopg2.extras import RealDictCursor

                self.db_connection = psycopg2.connect(
                    host=self.db_config['host'],
                    database=self.db_config['database'],
                    user=self.db_config['user'],
                    password=self.db_config['password'],
                    port=self.db_config.get('port', 5432)
                )
                print("Connected to PostgreSQL database")
                return True

            # OPTION 2: Supabase connection
            elif self.db_config and self.db_config.get('type') == 'supabase':
                from supabase import create_client

                supabase_url = self.db_config['url']
                supabase_key = self.db_config['service_key']
                self.db_connection = create_client(supabase_url, supabase_key)
                print("Connected to Supabase database")
                return True

            # OPTION 3: SQLAlchemy (recommended for web apps)
            elif self.db_config and self.db_config.get('type') == 'sqlalchemy':
                from sqlalchemy import create_engine

                self.db_connection = create_engine(self.db_config['connection_string'])
                print("Connected via SQLAlchemy")
                return True

            else:
                print("No database configuration provided")
                return False

        except Exception as e:
            print(f"Database connection failed: {e}")
            return False

    def load_user_profiles(self, user_ids: List[str] = None) -> Dict:
        """
        Load user profiles from database using your existing schema

        Your Schema:
        - sample_users: usn, first_name, last_name, department, year
        - sample_user_skills: usn, skill_id, proficiency_level
        - sample_user_availability: usn, day_of_week, time_slot_start, time_slot_end, is_available
        - skills: skill_id, name
        """

        try:
            # Build the query based on database type
            if self.db_config['type'] == 'postgresql':
                return self._load_from_postgresql(user_ids)
            elif self.db_config['type'] == 'supabase':
                return self._load_from_supabase(user_ids)
            elif self.db_config['type'] == 'sqlalchemy':
                return self._load_from_sqlalchemy(user_ids)

        except Exception as e:
            print(f"Error loading user profiles: {e}")
            return {}

    def _load_from_postgresql(self, user_ids: List[str] = None) -> Dict:
        """Load data using direct PostgreSQL connection"""
        users_data = {}

        with self.db_connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            # Base query
            user_filter = ""
            params = []

            if user_ids:
                user_filter = "WHERE u.usn = ANY(%s)"
                params.append(user_ids)

            # Get user basic info with skills
            query = f"""
            SELECT
                u.usn,
                u.first_name,
                u.last_name,
                u.department,
                u.year,
                COALESCE(
                    JSON_AGG(
                        JSON_BUILD_OBJECT(
                            'skill_id', us.skill_id,
                            'skill_name', s.name,
                            'proficiency_level', us.proficiency_level
                        )
                    ) FILTER (WHERE us.skill_id IS NOT NULL),
                    '[]'::json
                ) as skills
            FROM sample_users u
            LEFT JOIN sample_user_skills us ON u.usn = us.usn
            LEFT JOIN skills s ON us.skill_id = s.skill_id
            {user_filter}
            GROUP BY u.usn, u.first_name, u.last_name, u.department, u.year
            """

            cursor.execute(query, params)
            users = cursor.fetchall()

            # Get availability data separately
            availability_filter = ""
            if user_ids:
                availability_filter = "WHERE usn = ANY(%s)"

            availability_query = f"""
            SELECT usn, day_of_week, time_slot_start, time_slot_end, is_available
            FROM sample_user_availability
            {availability_filter}
            ORDER BY usn, day_of_week, time_slot_start
            """

            cursor.execute(availability_query, params)
            availability_data = cursor.fetchall()

            # Process users data
            for user in users:
                full_name = f"{user['first_name']} {user['last_name']}"
                users_data[user['usn']] = {
                    'name': full_name,
                    'first_name': user['first_name'],
                    'last_name': user['last_name'],
                    'department': user['department'],
                    'year': user['year'],
                    'skills': user['skills'] if user['skills'] else [],
                    'schedule': self._initialize_empty_schedule()
                }

            # Process availability data
            for avail in availability_data:
                usn = avail['usn']
                day_num = avail['day_of_week']
                start_time = avail['time_slot_start']
                end_time = avail['time_slot_end']
                is_available = avail['is_available']

                if usn in users_data and 0 <= day_num <= 6:
                    day_name = self.days[day_num]
                    time_slot = (start_time.strftime('%H:%M'), end_time.strftime('%H:%M'))

                    if is_available:
                        users_data[usn]['schedule'][day_name]['available'].add(time_slot)
                        users_data[usn]['schedule'][day_name]['valid'].add(time_slot)
                    else:
                        users_data[usn]['schedule'][day_name]['avoid'].add(time_slot)
                        users_data[usn]['schedule'][day_name]['valid'].discard(time_slot)

        return users_data

    def _load_from_supabase(self, user_ids: List[str] = None) -> Dict:
        """Load data using Supabase client"""
        users_data = {}

        # Get users with skills
        if user_ids:
            users_query = self.db_connection.table('sample_users').select('''
                *,
                sample_user_skills(*, skills(*))
            ''').in_('usn', user_ids)
        else:
            users_query = self.db_connection.table('sample_users').select('''
                *,
                sample_user_skills(*, skills(*))
            ''')

        users_result = users_query.execute()

        # Get availability data
        if user_ids:
            availability_query = self.db_connection.table('sample_user_availability').select('*').in_('usn', user_ids)
        else:
            availability_query = self.db_connection.table('sample_user_availability').select('*')

        availability_result = availability_query.execute()

        # Process users
        for user in users_result.data:
            full_name = f"{user['first_name']} {user['last_name']}"
            skills = []

            for user_skill in user.get('sample_user_skills', []):
                if user_skill.get('skills'):
                    skills.append({
                        'skill_id': user_skill['skill_id'],
                        'skill_name': user_skill['skills']['name'],
                        'proficiency_level': user_skill['proficiency_level']
                    })

            users_data[user['usn']] = {
                'name': full_name,
                'first_name': user['first_name'],
                'last_name': user['last_name'],
                'department': user['department'],
                'year': user['year'],
                'skills': skills,
                'schedule': self._initialize_empty_schedule()
            }

        # Process availability
        for avail in availability_result.data:
            usn = avail['usn']
            day_num = avail['day_of_week']
            start_time = avail['time_slot_start']
            end_time = avail['time_slot_end']
            is_available = avail['is_available']

            if usn in users_data and 0 <= day_num <= 6:
                day_name = self.days[day_num]
                time_slot = (start_time, end_time)

                if is_available:
                    users_data[usn]['schedule'][day_name]['available'].add(time_slot)
                    users_data[usn]['schedule'][day_name]['valid'].add(time_slot)
                else:
                    users_data[usn]['schedule'][day_name]['avoid'].add(time_slot)
                    users_data[usn]['schedule'][day_name]['valid'].discard(time_slot)

        return users_data

    def _load_from_sqlalchemy(self, user_ids: List[str] = None) -> Dict:
        """Load data using SQLAlchemy (works with both PostgreSQL and Supabase)"""
        users_data = {}

        with self.db_connection.connect() as conn:
            # Build user filter
            user_filter = ""
            if user_ids:
                user_ids_str = "', '".join(user_ids)
                user_filter = f"WHERE u.usn IN ('{user_ids_str}')"

            # Get users with skills
            query = f"""
            SELECT
                u.usn,
                u.first_name,
                u.last_name,
                u.department,
                u.year,
                us.skill_id,
                s.name as skill_name,
                us.proficiency_level
            FROM sample_users u
            LEFT JOIN sample_user_skills us ON u.usn = us.usn
            LEFT JOIN skills s ON us.skill_id = s.skill_id
            {user_filter}
            ORDER BY u.usn
            """

            result = conn.execute(text(query))

            # Process users and skills
            current_user = None
            for row in result:
                if current_user != row.usn:
                    full_name = f"{row.first_name} {row.last_name}"
                    users_data[row.usn] = {
                        'name': full_name,
                        'first_name': row.first_name,
                        'last_name': row.last_name,
                        'department': row.department,
                        'year': row.year,
                        'skills': [],
                        'schedule': self._initialize_empty_schedule()
                    }
                    current_user = row.usn

                if row.skill_name:
                    users_data[row.usn]['skills'].append({
                        'skill_id': row.skill_id,
                        'skill_name': row.skill_name,
                        'proficiency_level': row.proficiency_level
                    })

            # Get availability data
            availability_query = f"""
            SELECT usn, day_of_week, time_slot_start, time_slot_end, is_available
            FROM sample_user_availability
            {user_filter.replace('u.usn', 'usn') if user_filter else ''}
            ORDER BY usn, day_of_week, time_slot_start
            """

            availability_result = conn.execute(text(availability_query))

            # Process availability
            for row in availability_result:
                usn = row.usn
                day_num = row.day_of_week
                start_time = row.time_slot_start
                end_time = row.time_slot_end
                is_available = row.is_available

                if usn in users_data and 0 <= day_num <= 6:
                    day_name = self.days[day_num]
                    # Convert time objects to string format
                    time_slot = (start_time.strftime('%H:%M'), end_time.strftime('%H:%M'))

                    if is_available:
                        users_data[usn]['schedule'][day_name]['available'].add(time_slot)
                        users_data[usn]['schedule'][day_name]['valid'].add(time_slot)
                    else:
                        users_data[usn]['schedule'][day_name]['avoid'].add(time_slot)
                        users_data[usn]['schedule'][day_name]['valid'].discard(time_slot)

        return users_data

    def _initialize_empty_schedule(self) -> Dict:
        """Initialize empty schedule structure"""
        schedule = {}
        for day in self.days:
            schedule[day] = {
                'available': set(),  # Start with empty, populate from DB
                'avoid': set(),
                'valid': set()
            }
        return schedule

    # ===========================================
    # UTILITY METHODS FOR TIME SLOTS
    # ===========================================

    def time_slot_to_string(self, time_slot: Tuple[str, str]) -> str:
        """Convert time slot tuple to readable string"""
        return f"{time_slot[0]} - {time_slot[1]}"

    def string_to_time_slot(self, time_string: str) -> Tuple[str, str]:
        """Convert time string back to tuple"""
        if ' - ' in time_string:
            start, end = time_string.split(' - ')
            return (start.strip(), end.strip())
        return time_string, time_string

    def get_overlapping_slots(self, slot1: Tuple[str, str], slot2: Tuple[str, str]) -> bool:
        """Check if two time slots overlap"""
        start1, end1 = slot1
        start2, end2 = slot2

        # Convert to minutes for easier comparison
        def time_to_minutes(time_str):
            hours, minutes = map(int, time_str.split(':'))
            return hours * 60 + minutes

        start1_min = time_to_minutes(start1)
        end1_min = time_to_minutes(end1)
        start2_min = time_to_minutes(start2)
        end2_min = time_to_minutes(end2)

        # Handle midnight crossover
        if end1_min <= start1_min:  # Crosses midnight
            end1_min += 24 * 60
        if end2_min <= start2_min:  # Crosses midnight
            end2_min += 24 * 60

        return not (end1_min <= start2_min or end2_min <= start1_min)

    # ===========================================
    # CORE MATCHING ALGORITHMS
    # ===========================================

    def calculate_schedule_match_percentage(self, user1_id: str, user2_id: str,
                                          preferred_days: List[str] = None) -> Dict:
        """
        Calculate schedule match percentage between two users
        Used for profile recommendations

        Returns:
        - match_percentage: Overall compatibility (0-100)
        - common_slots: Number of overlapping time slots
        - day_breakdown: Per-day analysis
        - meeting_potential: Quality score for team formation
        """

        # Load user data if not in cache
        users_data = self.load_user_profiles([user1_id, user2_id])

        if user1_id not in users_data or user2_id not in users_data:
            return {
                'error': 'One or both users not found',
                'match_percentage': 0,
                'common_slots': 0
            }

        if preferred_days is None:
            preferred_days = self.days

        total_possible_slots = 0
        common_slots = 0
        day_breakdown = {}

        for day in preferred_days:
            user1_available = users_data[user1_id]['schedule'][day]['available']
            user2_available = users_data[user2_id]['schedule'][day]['available']

            # Find overlapping time slots
            day_common = 0
            day_total = len(self.time_slots)

            for slot in self.time_slots:
                if slot in user1_available and slot in user2_available:
                    day_common += 1

            # Also check for partial overlaps in custom time slots
            for slot1 in user1_available:
                for slot2 in user2_available:
                    if slot1 != slot2 and self.get_overlapping_slots(slot1, slot2):
                        day_common += 0.5  # Partial credit for overlapping but not exact slots

            day_breakdown[day] = {
                'common_slots': int(day_common),
                'total_possible': day_total,
                'day_percentage': (day_common / day_total * 100) if day_total > 0 else 0,
                'user1_available': len(user1_available),
                'user2_available': len(user2_available)
            }

            common_slots += day_common
            total_possible_slots += day_total

        # Calculate overall match percentage
        match_percentage = (common_slots / total_possible_slots * 100) if total_possible_slots > 0 else 0

        # Calculate meeting potential (weighted score)
        meeting_potential = self._calculate_meeting_potential(day_breakdown)

        return {
            'match_percentage': round(match_percentage, 1),
            'common_slots': int(common_slots),
            'total_possible_slots': total_possible_slots,
            'day_breakdown': day_breakdown,
            'meeting_potential': meeting_potential,
            'recommendation_score': self._calculate_recommendation_score(match_percentage, meeting_potential)
        }

    def get_profile_recommendations(self, user_id: str, candidate_ids: List[str],
                                  preferred_days: List[str] = None,
                                  min_match_threshold: float = 20.0) -> List[Dict]:
        """
        Get recommended profiles based on schedule compatibility

        Args:
        - user_id: Current user's ID
        - candidate_ids: List of potential teammate IDs
        - preferred_days: Days to consider for matching
        - min_match_threshold: Minimum match percentage to include

        Returns list of recommendations sorted by compatibility
        """

        recommendations = []

        # Load all required user data
        all_user_ids = [user_id] + candidate_ids
        users_data = self.load_user_profiles(all_user_ids)

        if user_id not in users_data:
            return [{'error': 'User not found'}]

        for candidate_id in candidate_ids:
            if candidate_id == user_id or candidate_id not in users_data:
                continue

            # Calculate schedule match
            match_result = self.calculate_schedule_match_percentage(
                user_id, candidate_id, preferred_days
            )

            if match_result['match_percentage'] >= min_match_threshold:
                candidate_data = users_data[candidate_id]

                recommendations.append({
                    'user_id': candidate_id,
                    'name': candidate_data['name'],
                    'first_name': candidate_data['first_name'],
                    'last_name': candidate_data['last_name'],
                    'department': candidate_data['department'],
                    'year': candidate_data['year'],
                    'skills': candidate_data['skills'],
                    'schedule_match': match_result,
                    'recommendation_priority': match_result['recommendation_score']
                })

        # Sort by recommendation score (descending)
        recommendations.sort(key=lambda x: x['recommendation_priority'], reverse=True)

        return recommendations

    def find_team_meeting_slots(self, team_member_ids: List[str],
                               preferred_days: List[str] = None,
                               min_duration_hours: int = 2) -> Dict:
        """
        Find available meeting slots for a formed team

        Args:
        - team_member_ids: List of team member IDs
        - preferred_days: Days to check for meetings
        - min_duration_hours: Minimum meeting duration

        Returns:
        - perfect_slots: 100% availability slots
        - good_slots: High availability slots (80%+)
        - backup_slots: Partial availability slots
        - statistics: Overall analysis
        """

        if len(team_member_ids) < 2:
            return {'error': 'Need at least 2 team members'}

        # Load team data
        users_data = self.load_user_profiles(team_member_ids)

        missing_users = [uid for uid in team_member_ids if uid not in users_data]
        if missing_users:
            return {'error': f'Users not found: {missing_users}'}

        if preferred_days is None:
            preferred_days = self.days

        perfect_slots = []
        good_slots = []
        backup_slots = []
        day_statistics = {}

        for day in preferred_days:
            day_perfect = 0
            day_good = 0
            day_backup = 0

            # Check each standard time slot
            for time_slot in self.time_slots:
                available_members = []

                for member_id in team_member_ids:
                    member_schedule = users_data[member_id]['schedule'][day]['available']

                    # Check if this exact slot or any overlapping slot is available
                    is_available = False
                    if time_slot in member_schedule:
                        is_available = True
                    else:
                        # Check for overlapping custom slots
                        for member_slot in member_schedule:
                            if self.get_overlapping_slots(time_slot, member_slot):
                                is_available = True
                                break

                    if is_available:
                        available_members.append(member_id)

                availability_percentage = (len(available_members) / len(team_member_ids)) * 100

                slot_info = {
                    'day': day.capitalize(),
                    'time_slot': self.time_slot_to_string(time_slot),
                    'start_time': time_slot[0],
                    'end_time': time_slot[1],
                    'availability_percentage': round(availability_percentage, 1),
                    'available_members': len(available_members),
                    'total_members': len(team_member_ids),
                    'available_member_names': [users_data[uid]['name'] for uid in available_members],
                    'unavailable_member_names': [users_data[uid]['name']
                                               for uid in team_member_ids if uid not in available_members]
                }

                if availability_percentage == 100:
                    perfect_slots.append(slot_info)
                    day_perfect += 1
                elif availability_percentage >= 80:
                    good_slots.append(slot_info)
                    day_good += 1
                elif availability_percentage >= 50:
                    backup_slots.append(slot_info)
                    day_backup += 1

            day_statistics[day] = {
                'perfect_slots': day_perfect,
                'good_slots': day_good,
                'backup_slots': day_backup,
                'total_viable_slots': day_perfect + day_good + day_backup
            }

        # Calculate overall statistics
        total_perfect = len(perfect_slots)
        total_good = len(good_slots)
        total_backup = len(backup_slots)
        total_checked = len(preferred_days) * len(self.time_slots)

        success_rate = ((total_perfect + total_good) / total_checked * 100) if total_checked > 0 else 0

        return {
            'team_info': {
                'member_ids': team_member_ids,
                'member_names': [users_data[uid]['name'] for uid in team_member_ids],
                'team_size': len(team_member_ids)
            },
            'perfect_slots': perfect_slots[:10],  # Limit to top 10
            'good_slots': good_slots[:10],
            'backup_slots': backup_slots[:5],
            'statistics': {
                'total_perfect_slots': total_perfect,
                'total_good_slots': total_good,
                'total_backup_slots': total_backup,
                'success_rate': round(success_rate, 1),
                'day_breakdown': day_statistics,
                'recommendation': self._get_meeting_recommendation(total_perfect, total_good, total_backup)
            }
        }

    # ===========================================
    # UTILITY METHODS
    # ===========================================

    def _calculate_meeting_potential(self, day_breakdown: Dict) -> float:
        """Calculate meeting potential score based on day distribution"""
        total_score = 0
        total_days = len(day_breakdown)

        for day_data in day_breakdown.values():
            # Weight recent days higher, prefer consistent availability
            day_score = day_data['day_percentage']
            if day_data['common_slots'] >= 3:  # Bonus for multiple slots per day
                day_score *= 1.2
            total_score += day_score

        return total_score / total_days if total_days > 0 else 0

    def _calculate_recommendation_score(self, match_percentage: float, meeting_potential: float) -> float:
        """Calculate overall recommendation score"""
        # Weighted combination: 60% match percentage, 40% meeting potential
        return (match_percentage * 0.6) + (meeting_potential * 0.4)

    def _get_meeting_recommendation(self, perfect: int, good: int, backup: int) -> str:
        """Generate meeting recommendation based on available slots"""
        if perfect >= 5:
            return "Excellent - Multiple perfect meeting times available"
        elif perfect >= 2:
            return "Good - Several perfect meeting times available"
        elif perfect >= 1 or good >= 3:
            return "Fair - Some good meeting opportunities"
        elif good >= 1 or backup >= 3:
            return "Challenging - Limited meeting opportunities"
        else:
            return "Difficult - Very few meeting opportunities"

    # ===========================================
    # WEB API READY METHODS
    # ===========================================

    def api_get_profile_recommendations(self, user_id: str, params: Dict) -> Dict:
        """
        API endpoint for getting profile recommendations

        Expected params:
        - candidate_ids: List[str]
        - preferred_days: Optional[List[str]]
        - min_match_threshold: Optional[float]
        - limit: Optional[int]
        """
        try:
            candidate_ids = params.get('candidate_ids', [])
            preferred_days = params.get('preferred_days', self.days)
            min_threshold = params.get('min_match_threshold', 20.0)
            limit = params.get('limit', 10)

            recommendations = self.get_profile_recommendations(
                user_id, candidate_ids, preferred_days, min_threshold
            )

            return {
                'success': True,
                'data': recommendations[:limit],
                'total_candidates': len(candidate_ids),
                'returned_recommendations': len(recommendations[:limit])
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }

    def api_get_team_meeting_slots(self, params: Dict) -> Dict:
        """
        API endpoint for getting team meeting slots

        Expected params:
        - team_member_ids: List[str]
        - preferred_days: Optional[List[str]]
        - min_duration_hours: Optional[int]
        """
        try:
            team_ids = params.get('team_member_ids', [])
            preferred_days = params.get('preferred_days', self.days)
            min_duration = params.get('min_duration_hours', 2)

            result = self.find_team_meeting_slots(team_ids, preferred_days, min_duration)

            if 'error' in result:
                return {
                    'success': False,
                    'error': result['error']
                }

            return {
                'success': True,
                'data': result
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }

# ===========================================
# USAGE EXAMPLES
# ===========================================

def example_usage():
    """Example usage of the WebScheduleMatcher"""

    # Database configuration examples

    # PostgreSQL config
    pg_config = {
        'type': 'postgresql',
        'host': 'localhost',
        'database': 'your_db',
        'user': 'your_user',
        'password': 'your_password',
        'port': 5432
    }

    # Supabase config
    supabase_config = {
        'type': 'supabase',
        'url': 'https://your-project.supabase.co',
        'service_key': 'your-service-key'
    }

    # SQLAlchemy config (recommended)
    sqlalchemy_config = {
        'type': 'sqlalchemy',
        'connection_string': 'postgresql://user:password@localhost:5432/dbname'
        # or for Supabase: 'postgresql://postgres:password@db.your-project.supabase.co:5432/postgres'
    }

    # Initialize matcher
    matcher = WebScheduleMatcher(sqlalchemy_config)

    if matcher.connect_to_database():
        # Example 1: Get profile recommendations
        recommendations = matcher.api_get_profile_recommendations(
            user_id='USN001',
            params={
                'candidate_ids': ['USN002', 'USN003', 'USN004', 'USN005'],
                'preferred_days': ['monday', 'tuesday', 'wednesday'],
                'min_match_threshold': 25.0,
                'limit': 5
            }
        )

        print("Profile Recommendations:", json.dumps(recommendations, indent=2))

        # Example 2: Get team meeting slots
        meeting_slots = matcher.api_get_team_meeting_slots({
            'team_member_ids': ['USN001', 'USN002', 'USN003'],
            'preferred_days': ['monday', 'wednesday', 'friday'],
            'min_duration_hours': 2
        })

        print("Team Meeting Slots:", json.dumps(meeting_slots, indent=2))

# ===========================================
# HELPER FUNCTIONS FOR DATA INSERTION
# ===========================================

def insert_sample_data(matcher: WebScheduleMatcher):
    """
    Helper function to insert sample data for testing
    Use this to populate your database with test data
    """

    if not matcher.db_connection:
        print("No database connection available")
        return

    # Sample users
    sample_users = [
        ('USN001', 'John', 'Doe', 'Computer Science', 3),
        ('USN002', 'Jane', 'Smith', 'Information Technology', 3),
        ('USN003', 'Mike', 'Johnson', 'Computer Science', 2),
        ('USN004', 'Sarah', 'Wilson', 'Electronics', 3),
        ('USN005', 'David', 'Brown', 'Information Technology', 4)
    ]

    # Sample skills
    sample_skills = [
        (1, 'Python'),
        (2, 'JavaScript'),
        (3, 'Java'),
        (4, 'React'),
        (5, 'Node.js'),
        (6, 'Machine Learning'),
        (7, 'Database Design'),
        (8, 'Web Development')
    ]

    # Sample user skills
    sample_user_skills = [
        ('USN001', 1, 4),  # John - Python (4/5)
        ('USN001', 6, 3),  # John - ML (3/5)
        ('USN002', 2, 5),  # Jane - JavaScript (5/5)
        ('USN002', 4, 4),  # Jane - React (4/5)
        ('USN003', 3, 3),  # Mike - Java (3/5)
        ('USN003', 7, 4),  # Mike - Database (4/5)
        ('USN004', 8, 4),  # Sarah - Web Dev (4/5)
        ('USN004', 2, 3),  # Sarah - JavaScript (3/5)
        ('USN005', 5, 5),  # David - Node.js (5/5)
        ('USN005', 1, 4),  # David - Python (4/5)
    ]

    # Sample availability (0=Sunday, 1=Monday, etc.)
    sample_availability = [
        # USN001 - available Monday-Wednesday mornings and evenings
        ('USN001', 1, '08:00', '10:00', True),
        ('USN001', 1, '18:00', '20:00', True),
        ('USN001', 2, '08:00', '10:00', True),
        ('USN001', 2, '18:00', '20:00', True),
        ('USN001', 3, '08:00', '10:00', True),
        ('USN001', 3, '18:00', '20:00', True),

        # USN002 - available Tuesday-Thursday afternoons
        ('USN002', 2, '12:00', '14:00', True),
        ('USN002', 2, '14:00', '16:00', True),
        ('USN002', 3, '12:00', '14:00', True),
        ('USN002', 3, '14:00', '16:00', True),
        ('USN002', 4, '12:00', '14:00', True),
        ('USN002', 4, '14:00', '16:00', True),

        # USN003 - available Monday, Wednesday, Friday mornings
        ('USN003', 1, '08:00', '10:00', True),
        ('USN003', 1, '10:00', '12:00', True),
        ('USN003', 3, '08:00', '10:00', True),
        ('USN003', 3, '10:00', '12:00', True),
        ('USN003', 5, '08:00', '10:00', True),
        ('USN003', 5, '10:00', '12:00', True),

        # Add some unavailable slots to test the logic
        ('USN001', 1, '12:00', '14:00', False),  # USN001 not available Mon 12-2
        ('USN002', 2, '08:00', '10:00', False),  # USN002 not available Tue 8-10
    ]

    try:
        if matcher.db_config['type'] == 'sqlalchemy':
            with matcher.db_connection.connect() as conn:
                # Insert skills first
                for skill_id, skill_name in sample_skills:
                    conn.execute(text("""
                        INSERT INTO skills (skill_id, name)
                        VALUES (:skill_id, :name)
                        ON CONFLICT (skill_id) DO NOTHING
                    """), {'skill_id': skill_id, 'name': skill_name})

                # Insert users
                for usn, first_name, last_name, dept, year in sample_users:
                    conn.execute(text("""
                        INSERT INTO sample_users (usn, first_name, last_name, department, year)
                        VALUES (:usn, :first_name, :last_name, :department, :year)
                        ON CONFLICT (usn) DO NOTHING
                    """), {
                        'usn': usn, 'first_name': first_name, 'last_name': last_name,
                        'department': dept, 'year': year
                    })

                # Insert user skills
                for usn, skill_id, level in sample_user_skills:
                    conn.execute(text("""
                        INSERT INTO sample_user_skills (usn, skill_id, proficiency_level)
                        VALUES (:usn, :skill_id, :proficiency_level)
                        ON CONFLICT (usn, skill_id) DO NOTHING
                    """), {'usn': usn, 'skill_id': skill_id, 'proficiency_level': level})

                # Insert availability
                for usn, day, start_time, end_time, available in sample_availability:
                    conn.execute(text("""
                        INSERT INTO sample_user_availability
                        (usn, day_of_week, time_slot_start, time_slot_end, is_available)
                        VALUES (:usn, :day_of_week, :time_slot_start, :time_slot_end, :is_available)
                        ON CONFLICT (usn, day_of_week, time_slot_start, time_slot_end) DO NOTHING
                    """), {
                        'usn': usn, 'day_of_week': day,
                        'time_slot_start': start_time, 'time_slot_end': end_time,
                        'is_available': available
                    })

                conn.commit()
                print("Sample data inserted successfully!")

        elif matcher.db_config['type'] == 'supabase':
            # Insert using Supabase client
            # Skills
            matcher.db_connection.table('skills').upsert([
                {'skill_id': sid, 'name': name} for sid, name in sample_skills
            ]).execute()

            # Users
            matcher.db_connection.table('sample_users').upsert([
                {
                    'usn': usn, 'first_name': fname, 'last_name': lname,
                    'department': dept, 'year': year
                }
                for usn, fname, lname, dept, year in sample_users
            ]).execute()

            # User skills
            matcher.db_connection.table('sample_user_skills').upsert([
                {'usn': usn, 'skill_id': sid, 'proficiency_level': level}
                for usn, sid, level in sample_user_skills
            ]).execute()

            # Availability
            matcher.db_connection.table('sample_user_availability').upsert([
                {
                    'usn': usn, 'day_of_week': day,
                    'time_slot_start': start_time, 'time_slot_end': end_time,
                    'is_available': available
                }
                for usn, day, start_time, end_time, available in sample_availability
            ]).execute()

            print("Sample data inserted successfully!")

    except Exception as e:
        print(f"Error inserting sample data: {e}")

# ===========================================
# FLASK/FASTAPI INTEGRATION EXAMPLES
# ===========================================

def create_flask_routes(matcher: WebScheduleMatcher):
    """
    Example Flask routes for the schedule matcher
    Install: pip install flask
    """
    try:
        from flask import Flask, request, jsonify

        app = Flask(__name__)

        @app.route('/api/recommendations/<user_id>', methods=['GET'])
        def get_recommendations(user_id):
            """Get profile recommendations for a user"""
            params = {
                'candidate_ids': request.json.get('candidate_ids', []),
                'preferred_days': request.json.get('preferred_days', matcher.days),
                'min_match_threshold': request.json.get('min_match_threshold', 20.0),
                'limit': request.json.get('limit', 10)
            }

            result = matcher.api_get_profile_recommendations(user_id, params)
            return jsonify(result)

        @app.route('/api/team-meetings', methods=['POST'])
        def get_team_meetings():
            """Get meeting slots for a team"""
            params = {
                'team_member_ids': request.json.get('team_member_ids', []),
                'preferred_days': request.json.get('preferred_days', matcher.days),
                'min_duration_hours': request.json.get('min_duration_hours', 2)
            }

            result = matcher.api_get_team_meeting_slots(params)
            return jsonify(result)

        @app.route('/api/match-percentage', methods=['POST'])
        def get_match_percentage():
            """Get match percentage between two users"""
            data = request.json
            user1_id = data.get('user1_id')
            user2_id = data.get('user2_id')
            preferred_days = data.get('preferred_days', matcher.days)

            result = matcher.calculate_schedule_match_percentage(
                user1_id, user2_id, preferred_days
            )
            return jsonify(result)

        return app

    except ImportError:
        print("Flask not installed. Install with: pip install flask")
        return None

def create_fastapi_routes(matcher: WebScheduleMatcher):
    """
    Example FastAPI routes for the schedule matcher
    Install: pip install fastapi uvicorn
    """
    try:
        from fastapi import FastAPI
        from pydantic import BaseModel
        from typing import List, Optional

        app = FastAPI(title="Schedule Matcher API", version="1.0.0")

        class RecommendationRequest(BaseModel):
            candidate_ids: List[str]
            preferred_days: Optional[List[str]] = None
            min_match_threshold: Optional[float] = 20.0
            limit: Optional[int] = 10

        class TeamMeetingRequest(BaseModel):
            team_member_ids: List[str]
            preferred_days: Optional[List[str]] = None
            min_duration_hours: Optional[int] = 2

        class MatchPercentageRequest(BaseModel):
            user1_id: str
            user2_id: str
            preferred_days: Optional[List[str]] = None

        @app.post("/api/recommendations/{user_id}")
        async def get_recommendations(user_id: str, request: RecommendationRequest):
            """Get profile recommendations for a user"""
            params = {
                'candidate_ids': request.candidate_ids,
                'preferred_days': request.preferred_days or matcher.days,
                'min_match_threshold': request.min_match_threshold,
                'limit': request.limit
            }

            return matcher.api_get_profile_recommendations(user_id, params)

        @app.post("/api/team-meetings")
        async def get_team_meetings(request: TeamMeetingRequest):
            """Get meeting slots for a team"""
            params = {
                'team_member_ids': request.team_member_ids,
                'preferred_days': request.preferred_days or matcher.days,
                'min_duration_hours': request.min_duration_hours
            }

            return matcher.api_get_team_meeting_slots(params)

        @app.post("/api/match-percentage")
        async def get_match_percentage(request: MatchPercentageRequest):
            """Get match percentage between two users"""
            result = matcher.calculate_schedule_match_percentage(
                request.user1_id, request.user2_id,
                request.preferred_days or matcher.days
            )
            return result

        return app

    except ImportError:
        print("FastAPI not installed. Install with: pip install fastapi uvicorn")
        return None

if __name__ == "__main__":
    # Example of how to use the matcher
    example_usage()

    # To insert sample data, uncomment below:
    # matcher = WebScheduleMatcher(your_db_config)
    # if matcher.connect_to_database():
    #     insert_sample_data(matcher)
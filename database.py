import sqlite3
from datetime import datetime
from typing import List, Dict, Optional
import json
from contextlib import contextmanager

class DatabaseManager:
    def __init__(self, db_path: str = "goals.db"):
        self.db_path = db_path
        self.init_database()
    
    @contextmanager
    def get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()
    
    def init_database(self):
        with self.get_connection() as conn:
            # Table des objectifs
            conn.execute("""
                CREATE TABLE IF NOT EXISTS goals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    description TEXT,
                    category TEXT,
                    priority TEXT CHECK(priority IN ('Basse', 'Moyenne', 'Haute', 'Urgent')),
                    target_date DATE,
                    current_progress REAL DEFAULT 0,
                    target_value REAL,
                    current_value REAL,
                    unit TEXT,
                    status TEXT CHECK(status IN ('En cours', 'Terminé', 'En retard', 'Annulé')) DEFAULT 'En cours',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    color_code TEXT,
                    tags TEXT
                )
            """)
            
            # Table des sous-tâches
            conn.execute("""
                CREATE TABLE IF NOT EXISTS subtasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    goal_id INTEGER,
                    name TEXT NOT NULL,
                    description TEXT,
                    completed BOOLEAN DEFAULT 0,
                    due_date DATE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (goal_id) REFERENCES goals (id) ON DELETE CASCADE
                )
            """)
            
            # Table des activités (historique)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS activities (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    goal_id INTEGER,
                    activity_type TEXT,
                    description TEXT,
                    value_before REAL,
                    value_after REAL,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (goal_id) REFERENCES goals (id) ON DELETE CASCADE
                )
            """)
            
            # Table des notes
            conn.execute("""
                CREATE TABLE IF NOT EXISTS notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    goal_id INTEGER,
                    content TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (goal_id) REFERENCES goals (id) ON DELETE CASCADE
                )
            """)
            
            # Table des rappels
            conn.execute("""
                CREATE TABLE IF NOT EXISTS reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    goal_id INTEGER,
                    message TEXT,
                    reminder_date DATE,
                    sent BOOLEAN DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (goal_id) REFERENCES goals (id) ON DELETE CASCADE
                )
            """)
    
    # CRUD Operations for Goals
    def create_goal(self, goal_data: Dict) -> int:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO goals (name, description, category, priority, target_date, 
                                 target_value, current_value, unit, color_code, tags)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                goal_data['name'],
                goal_data['description'],
                goal_data.get('category', 'Général'),
                goal_data.get('priority', 'Moyenne'),
                goal_data['target_date'],
                goal_data.get('target_value'),
                goal_data.get('current_value', 0),
                goal_data.get('unit'),
                goal_data.get('color_code', '#3B82F6'),
                json.dumps(goal_data.get('tags', []))
            ))
            return cursor.lastrowid
    
    def get_goals(self, filters: Dict = None) -> List[Dict]:
        with self.get_connection() as conn:
            query = "SELECT * FROM goals WHERE 1=1"
            params = []
            
            if filters:
                if filters.get('category'):
                    query += " AND category = ?"
                    params.append(filters['category'])
                if filters.get('priority'):
                    query += " AND priority = ?"
                    params.append(filters['priority'])
                if filters.get('status'):
                    query += " AND status = ?"
                    params.append(filters['status'])
            
            query += " ORDER BY priority DESC, target_date ASC"
            
            cursor = conn.execute(query, params)
            goals = [dict(row) for row in cursor.fetchall()]
            
            # Parse tags from JSON
            for goal in goals:
                if goal.get('tags'):
                    goal['tags'] = json.loads(goal['tags'])
                else:
                    goal['tags'] = []
            
            return goals
    
    def update_goal_progress(self, goal_id: int, progress: float):
        with self.get_connection() as conn:
            # Log activity before update
            cursor = conn.execute("SELECT current_progress FROM goals WHERE id = ?", (goal_id,))
            old_progress = cursor.fetchone()[0]
            
            # Update progress
            conn.execute("""
                UPDATE goals 
                SET current_progress = ?, updated_at = CURRENT_TIMESTAMP,
                    status = CASE 
                        WHEN ? >= 100 THEN 'Terminé'
                        WHEN target_date < DATE('now') AND ? < 100 THEN 'En retard'
                        ELSE 'En cours'
                    END
                WHERE id = ?
            """, (progress, progress, progress, goal_id))
            
            # Log activity
            conn.execute("""
                INSERT INTO activities (goal_id, activity_type, description, value_before, value_after)
                VALUES (?, 'progress_update', 'Mise à jour de la progression', ?, ?)
            """, (goal_id, old_progress, progress))
    
    def delete_goal(self, goal_id: int):
        with self.get_connection() as conn:
            conn.execute("DELETE FROM goals WHERE id = ?", (goal_id,))
    
    # Subtasks operations
    def add_subtask(self, goal_id: int, subtask_data: Dict):
        with self.get_connection() as conn:
            conn.execute("""
                INSERT INTO subtasks (goal_id, name, description, due_date)
                VALUES (?, ?, ?, ?)
            """, (goal_id, subtask_data['name'], 
                  subtask_data.get('description'), subtask_data.get('due_date')))
    
    def get_subtasks(self, goal_id: int) -> List[Dict]:
        with self.get_connection() as conn:
            cursor = conn.execute("SELECT * FROM subtasks WHERE goal_id = ?", (goal_id,))
            return [dict(row) for row in cursor.fetchall()]
    
    def update_subtask_status(self, subtask_id: int, completed: bool):
        with self.get_connection() as conn:
            conn.execute("UPDATE subtasks SET completed = ? WHERE id = ?", (completed, subtask_id))
    
    # Statistics
    def get_statistics(self) -> Dict:
        with self.get_connection() as conn:
            cursor = conn.execute("""
                SELECT 
                    COUNT(*) as total_goals,
                    AVG(current_progress) as avg_progress,
                    SUM(CASE WHEN current_progress >= 100 THEN 1 ELSE 0 END) as completed_goals,
                    SUM(CASE WHEN priority = 'Haute' OR priority = 'Urgent' THEN 1 ELSE 0 END) as high_priority,
                    SUM(CASE WHEN target_date < DATE('now') AND current_progress < 100 THEN 1 ELSE 0 END) as overdue_goals,
                    SUM(CASE WHEN target_date BETWEEN DATE('now') AND DATE('now', '+7 days') 
                           AND current_progress < 100 THEN 1 ELSE 0 END) as due_soon_goals
                FROM goals
            """)
            stats = dict(cursor.fetchone())
            
            # Category distribution
            cursor = conn.execute("""
                SELECT category, COUNT(*) as count 
                FROM goals 
                GROUP BY category
            """)
            stats['category_distribution'] = {row['category']: row['count'] for row in cursor.fetchall()}
            
            # Progress trends
            cursor = conn.execute("""
                SELECT DATE(updated_at) as date, AVG(current_progress) as avg_progress
                FROM goals
                WHERE updated_at >= DATE('now', '-30 days')
                GROUP BY DATE(updated_at)
                ORDER BY date
            """)
            stats['progress_trend'] = [dict(row) for row in cursor.fetchall()]
            
            return stats
    
    # Notes and activities
    def add_note(self, goal_id: int, content: str):
        with self.get_connection() as conn:
            conn.execute("INSERT INTO notes (goal_id, content) VALUES (?, ?)", (goal_id, content))
    
    def get_activities(self, goal_id: int = None) -> List[Dict]:
        with self.get_connection() as conn:
            if goal_id:
                cursor = conn.execute("""
                    SELECT a.*, g.name as goal_name 
                    FROM activities a
                    LEFT JOIN goals g ON a.goal_id = g.id
                    WHERE a.goal_id = ?
                    ORDER BY a.timestamp DESC
                    LIMIT 10
                """, (goal_id,))
            else:
                cursor = conn.execute("""
                    SELECT a.*, g.name as goal_name 
                    FROM activities a
                    LEFT JOIN goals g ON a.goal_id = g.id
                    ORDER BY a.timestamp DESC
                    LIMIT 20
                """)
            return [dict(row) for row in cursor.fetchall()]

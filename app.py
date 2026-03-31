import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import numpy as np
from datetime import datetime, timedelta
import json
import sqlite3
from contextlib import contextmanager
import base64
from io import BytesIO
from fpdf import FPDF
import re 

# ============================================
# CONFIGURATION INITIALE
# ============================================
st.set_page_config(
    page_title="GoalMaster Pro - Suivi d'Objectifs Intelligents",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ============================================
# BASE DE DONNÉES SQLITE
# ============================================
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
        except Exception:
            conn.rollback()
            raise
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
                    target_value REAL DEFAULT 100,
                    current_value REAL DEFAULT 0,
                    unit TEXT DEFAULT '%',
                    status TEXT CHECK(status IN ('En cours', 'Terminé', 'En retard', 'Annulé')) DEFAULT 'En cours',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    color_code TEXT DEFAULT '#3B82F6',
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
            
            # Table des activités
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
    
    def create_goal(self, goal_data: dict) -> int:
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
                goal_data.get('target_value', 100),
                goal_data.get('current_value', 0),
                goal_data.get('unit', '%'),
                goal_data.get('color_code', '#3B82F6'),
                json.dumps(goal_data.get('tags', []))
            ))
            goal_id = cursor.lastrowid
            
            # Calculer la progression initiale
            current_value = goal_data.get('current_value', 0)
            target_value = goal_data.get('target_value', 100)
            
            if target_value > 0:
                progress_percent = (current_value / target_value) * 100
            else:
                progress_percent = 0
            
            # Mettre à jour la progression
            conn.execute("""
                UPDATE goals 
                SET current_progress = ?
                WHERE id = ?
            """, (progress_percent, goal_id))
            
            # Déterminer le statut initial
            status = 'En cours'
            if progress_percent >= 100:
                status = 'Terminé'
            
            conn.execute("""
                UPDATE goals 
                SET status = ?
                WHERE id = ?
            """, (status, goal_id))
            
            # Enregistrer l'activité
            conn.execute("""
                INSERT INTO activities (goal_id, activity_type, description, value_before, value_after)
                VALUES (?, 'creation', 'Objectif créé', 0, ?)
            """, (goal_id, progress_percent))
            
            return goal_id
    
    def get_goals(self, filters: dict = None) -> list:
        with self.get_connection() as conn:
            query = "SELECT * FROM goals WHERE 1=1"
            params = []
            
            if filters:
                if filters.get('category') and filters['category'] != 'Toutes':
                    query += " AND category = ?"
                    params.append(filters['category'])
                if filters.get('priority') and filters['priority'] != 'Toutes':
                    query += " AND priority = ?"
                    params.append(filters['priority'])
                if filters.get('status') and filters['status'] != 'Tous':
                    query += " AND status = ?"
                    params.append(filters['status'])
            
            query += " ORDER BY priority DESC, target_date ASC"
            
            cursor = conn.execute(query, params)
            goals = []
            for row in cursor.fetchall():
                goal = dict(row)
                
                # S'assurer que current_progress est un float
                if goal.get('current_progress') is not None:
                    goal['current_progress'] = float(goal['current_progress'])
                else:
                    goal['current_progress'] = 0.0
                
                # Convertir les tags JSON en liste
                if goal.get('tags'):
                    try:
                        goal['tags'] = json.loads(goal['tags'])
                    except:
                        goal['tags'] = []
                else:
                    goal['tags'] = []
                
                # Vérifier si l'objectif est en retard
                if goal['status'] == 'En cours' and goal.get('target_date'):
                    try:
                        target_date = datetime.strptime(goal['target_date'], '%Y-%m-%d').date()
                        if target_date < datetime.now().date():
                            goal['status'] = 'En retard'
                            # Mettre à jour le statut dans la base de données
                            conn.execute("UPDATE goals SET status = ? WHERE id = ?", ('En retard', goal['id']))
                    except:
                        pass
                
                goals.append(goal)
            
            return goals
    
    def update_goal_progress(self, goal_id: int, progress: float):
        """Met à jour la progression d'un objectif"""
        with self.get_connection() as conn:
            # Récupérer l'objectif
            cursor = conn.execute("SELECT * FROM goals WHERE id = ?", (goal_id,))
            goal = cursor.fetchone()
            
            if not goal:
                return
            
            goal_dict = dict(goal)
            old_progress = goal_dict.get('current_progress', 0)
            
            # Déterminer le nouveau statut
            status = 'En cours'
            if progress >= 100:
                status = 'Terminé'
            elif goal_dict.get('target_date'):
                try:
                    target_date = datetime.strptime(goal_dict['target_date'], '%Y-%m-%d').date()
                    if target_date < datetime.now().date() and progress < 100:
                        status = 'En retard'
                except:
                    pass
            
            # Mettre à jour l'objectif
            conn.execute("""
                UPDATE goals 
                SET current_progress = ?, 
                    current_value = ?,
                    status = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (progress, progress, status, goal_id))
            
            # Enregistrer l'activité
            conn.execute("""
                INSERT INTO activities (goal_id, activity_type, description, value_before, value_after)
                VALUES (?, 'progress_update', 'Mise à jour de la progression', ?, ?)
            """, (goal_id, old_progress, progress))
            
            conn.commit()
    
    def delete_goal(self, goal_id: int):
        with self.get_connection() as conn:
            conn.execute("DELETE FROM goals WHERE id = ?", (goal_id,))
    
    def get_statistics(self) -> dict:
        with self.get_connection() as conn:
            # Récupérer tous les objectifs
            cursor = conn.execute("SELECT * FROM goals")
            goals = cursor.fetchall()
            
            if not goals:
                return {
                    'total_goals': 0,
                    'avg_progress': 0.0,
                    'completed_goals': 0,
                    'high_priority': 0,
                    'overdue_goals': 0,
                    'due_soon_goals': 0,
                    'category_distribution': {},
                    'recent_activities': []
                }
            
            goals_list = [dict(goal) for goal in goals]
            
            # Calculer les statistiques
            total_goals = len(goals_list)
            completed_goals = sum(1 for g in goals_list if g.get('current_progress', 0) >= 100)
            
            # Progression moyenne
            progress_values = [g.get('current_progress', 0) for g in goals_list]
            avg_progress = sum(progress_values) / total_goals if total_goals > 0 else 0
            
            # Objectifs haute priorité
            high_priority = sum(1 for g in goals_list if g.get('priority') in ['Haute', 'Urgent'])
            
            # Objectifs en retard
            now = datetime.now().date()
            overdue_goals = 0
            due_soon_goals = 0
            
            for goal in goals_list:
                progress = goal.get('current_progress', 0)
                target_date_str = goal.get('target_date')
                
                if target_date_str and progress < 100:
                    try:
                        target_date = datetime.strptime(target_date_str, '%Y-%m-%d').date()
                        if target_date < now:
                            overdue_goals += 1
                        elif (target_date - now).days <= 7:
                            due_soon_goals += 1
                    except:
                        pass
            
            # Distribution par catégorie
            category_distribution = {}
            for goal in goals_list:
                category = goal.get('category', 'Non catégorisé')
                category_distribution[category] = category_distribution.get(category, 0) + 1
            
            # Activités récentes
            cursor = conn.execute("""
                SELECT a.*, g.name as goal_name 
                FROM activities a
                LEFT JOIN goals g ON a.goal_id = g.id
                ORDER BY a.timestamp DESC
                LIMIT 5
            """)
            recent_activities = [dict(row) for row in cursor.fetchall()]
            
            stats = {
                'total_goals': total_goals,
                'avg_progress': float(avg_progress),
                'completed_goals': completed_goals,
                'high_priority': high_priority,
                'overdue_goals': overdue_goals,
                'due_soon_goals': due_soon_goals,
                'category_distribution': category_distribution,
                'recent_activities': recent_activities
            }
            
            return stats
    
    def add_subtask(self, goal_id: int, subtask_data: dict):
        with self.get_connection() as conn:
            conn.execute("""
                INSERT INTO subtasks (goal_id, name, description, due_date)
                VALUES (?, ?, ?, ?)
            """, (
                goal_id, 
                subtask_data['name'],
                subtask_data.get('description', ''),
                subtask_data.get('due_date')
            ))
    
    def get_subtasks(self, goal_id: int) -> list:
        with self.get_connection() as conn:
            cursor = conn.execute("SELECT * FROM subtasks WHERE goal_id = ? ORDER BY created_at DESC", (goal_id,))
            return [dict(row) for row in cursor.fetchall()]
    
    def update_subtask_status(self, subtask_id: int, completed: bool):
        with self.get_connection() as conn:
            conn.execute("UPDATE subtasks SET completed = ? WHERE id = ?", (1 if completed else 0, subtask_id))

# ============================================
# GÉNÉRATION PDF
# ============================================
class PDFReport:
    def generate_report(self, db_manager, output_path: str = "rapport_objectifs.pdf"):
        # Créer le PDF
        pdf = FPDF()
        pdf.add_page()
        
        # En-tête
        pdf.set_font('Arial', 'B', 16)
        pdf.cell(0, 10, 'Rapport de Progression des Objectifs', 0, 1, 'C')
        pdf.set_font('Arial', 'I', 10)
        pdf.cell(0, 10, f"Généré le {datetime.now().strftime('%d/%m/%Y %H:%M')}", 0, 1, 'C')
        pdf.ln(10)
        
        # Statistiques
        stats = db_manager.get_statistics()
        pdf.set_font('Arial', 'B', 14)
        pdf.cell(0, 10, 'Statistiques Générales', 0, 1)
        pdf.set_font('Arial', '', 12)
        
        pdf.cell(0, 10, f"Objectifs totaux: {stats['total_goals']}", 0, 1)
        pdf.cell(0, 10, f"Progression moyenne: {stats['avg_progress']:.1f}%", 0, 1)
        pdf.cell(0, 10, f"Objectifs terminés: {stats['completed_goals']}", 0, 1)
        pdf.cell(0, 10, f"Objectifs urgents: {stats['due_soon_goals']}", 0, 1)
        pdf.ln(10)
        
        # Liste des objectifs
        goals = db_manager.get_goals()
        if goals:
            pdf.set_font('Arial', 'B', 14)
            pdf.cell(0, 10, 'Détails des Objectifs', 0, 1)
            
            pdf.set_font('Arial', '', 10)
            for i, goal in enumerate(goals[:10], 1):  # Limiter à 10 objectifs
                pdf.cell(0, 8, f"{i}. {goal['name']} - {goal['current_progress']:.1f}% ({goal['status']})", 0, 1)
                pdf.cell(0, 6, f"   Catégorie: {goal['category']}, Priorité: {goal['priority']}, Date: {goal['target_date']}", 0, 1)
                pdf.ln(2)
        
        # Recommandations
        pdf.ln(10)
        pdf.set_font('Arial', 'B', 14)
        pdf.cell(0, 10, 'Recommandations', 0, 1)
        
        pdf.set_font('Arial', '', 11)
        recommendations = [
            "1. Concentrez-vous sur les objectifs à haute priorité",
            "2. Décomposez les gros objectifs en sous-tâches",
            "3. Revoyez vos progrès chaque semaine",
            "4. Célébrez chaque objectif terminé"
        ]
        
        for rec in recommendations:
            pdf.multi_cell(0, 8, rec)
        
        # Pied de page
        pdf.ln(10)
        pdf.set_font('Arial', 'I', 8)
        pdf.cell(0, 10, 'Rapport généré par GoalMaster Pro', 0, 0, 'C')
        
        # Sauvegarder
        try:
            pdf.output(output_path)
            return output_path
        except Exception as e:
            print(f"Erreur lors de la génération du PDF: {e}")
            return None

# ============================================
# STYLE CSS MODERNE
# ============================================
st.markdown("""
<style>
    /* Thème principal */
    .main-header {
        font-size: 2.8rem;
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        text-align: center;
        margin-bottom: 1rem;
        font-weight: 800;
    }
    
    .sub-header {
        font-size: 1.5rem;
        color: #4B5563;
        margin-bottom: 1.5rem;
        font-weight: 600;
    }
    
    /* Cartes */
    .stat-card {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        border-radius: 15px;
        padding: 1.5rem;
        color: white;
        text-align: center;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        margin-bottom: 1rem;
    }
    
    .goal-card {
        background: white;
        border-radius: 15px;
        padding: 1.5rem;
        margin: 1rem 0;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.05);
        border-left: 5px solid #3B82F6;
        transition: all 0.3s ease;
    }
    
    .goal-card:hover {
        box-shadow: 0 10px 20px rgba(0, 0, 0, 0.1);
        transform: translateY(-3px);
    }
    
    /* Barres de progression */
    .progress-container {
        margin: 1rem 0;
    }
    
    .progress-bar {
        height: 12px;
        background-color: #E5E7EB;
        border-radius: 6px;
        overflow: hidden;
    }
    
    .progress-fill {
        height: 100%;
        border-radius: 6px;
        background: linear-gradient(90deg, #10B981 0%, #34D399 100%);
        transition: width 0.5s ease;
    }
    
    /* Badges de priorité */
    .priority-badge {
        display: inline-block;
        padding: 0.25rem 0.75rem;
        border-radius: 20px;
        font-size: 0.875rem;
        font-weight: 600;
    }
    
    .priority-high { background: #FECACA; color: #991B1B; }
    .priority-medium { background: #FEF3C7; color: #92400E; }
    .priority-low { background: #D1FAE5; color: #065F46; }
    .priority-urgent { background: #FEE2E2; color: #7F1D1D; }
    
    /* Navigation */
    .sidebar-section {
        padding: 1rem;
        margin-bottom: 1rem;
    }
    
    /* Boutons */
    .stButton > button {
        border-radius: 10px;
        border: none;
        padding: 0.5rem 1rem;
        font-weight: 600;
        transition: all 0.3s ease;
    }
    
    .stButton > button:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
    }
    
    /* Formulaires */
    .form-container {
        background: #F9FAFB;
        padding: 2rem;
        border-radius: 15px;
        border: 2px solid #E5E7EB;
        margin-bottom: 2rem;
    }
    
    /* Animation */
    @keyframes fadeIn {
        from { opacity: 0; transform: translateY(10px); }
        to { opacity: 1; transform: translateY(0); }
    }
    
    .fade-in {
        animation: fadeIn 0.5s ease-out;
    }
    
    /* Correction pour l'affichage HTML */
    .html-content {
        font-family: sans-serif;
        color: #333;
    }
</style>
""", unsafe_allow_html=True)

# ============================================
# FONCTIONS UTILITAIRES
# ============================================

def get_database():
    return DatabaseManager()

def get_priority_color(priority):
    colors = {
        'Urgent': '#DC2626',
        'Haute': '#EF4444',
        'Moyenne': '#F59E0B',
        'Basse': '#10B981'
    }
    return colors.get(priority, '#6B7280')

def create_goal_card(goal):
    """Crée une carte d'objectif avec une barre de progression"""
    priority_color = get_priority_color(goal['priority'])
    progress = goal.get('current_progress', 0)
    
    # Créer la carte avec HTML/CSS
    card_html = f"""
    <div class="goal-card fade-in">
        <div style="display: flex; justify-content: space-between; align-items: start; margin-bottom: 1rem;">
            <h4 style="margin: 0; color: #1F2937;">{goal['name']}</h4>
            <span class="priority-badge priority-{goal['priority'].lower().replace(' ', '-')}">
                {goal['priority']}
            </span>
        </div>
        
        <p style="color: #6B7280; margin-bottom: 1rem; font-size: 0.95rem;">
            {goal.get('description', '')[:120]}{'...' if len(goal.get('description', '')) > 120 else ''}
        </p>
        
        <div class="progress-container">
            <div style="display: flex; justify-content: space-between; margin-bottom: 0.5rem; font-size: 0.9rem;">
                <span style="color: #6B7280;">Progression</span>
                <span style="font-weight: 600; color: {priority_color};">{progress:.1f}%</span>
            </div>
            <div class="progress-bar">
                <div class="progress-fill" style="width: {min(progress, 100)}%; 
                     background: linear-gradient(90deg, {priority_color} 0%, {priority_color}88 100%);">
                </div>
            </div>
        </div>
        
        <div style="display: flex; justify-content: space-between; font-size: 0.85rem; color: #6B7280; margin-top: 1rem;">
            <div style="display: flex; align-items: center; gap: 0.3rem;">
                <span>📅</span>
                <span>{goal.get('target_date', 'Non définie')}</span>
            </div>
            <div style="display: flex; align-items: center; gap: 0.3rem;">
                <span>🏷️</span>
                <span>{goal.get('category', 'Non catégorisé')}</span>
            </div>
            <div style="display: flex; align-items: center; gap: 0.3rem;">
                <span>📊</span>
                <span>{goal.get('status', 'En cours')}</span>
            </div>
        </div>
    </div>
    """
    
    st.markdown(card_html, unsafe_allow_html=True)

# ============================================
# PAGES DE L'APPLICATION
# ============================================

def dashboard_page(db):
    """Page Tableau de bord"""
    st.markdown('<h1 class="main-header">🎯 Tableau de Bord</h1>', unsafe_allow_html=True)
    st.markdown('<p style="text-align: center; color: #6B7280; font-size: 1.2rem; margin-bottom: 2rem;">Visualisez vos progrès en temps réel</p>', unsafe_allow_html=True)
    
    # Récupérer les statistiques
    stats = db.get_statistics()
    
    # Afficher les métriques KPI
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.markdown(f"""
        <div class="stat-card fade-in">
            <div style="font-size: 2rem; margin-bottom: 0.5rem;">🎯</div>
            <div style="font-size: 2rem; font-weight: 700;">{stats['total_goals']}</div>
            <div>Objectifs Actifs</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col2:
        st.markdown(f"""
        <div class="stat-card fade-in">
            <div style="font-size: 2rem; margin-bottom: 0.5rem;">📈</div>
            <div style="font-size: 2rem; font-weight: 700;">{stats['avg_progress']:.1f}%</div>
            <div>Progression Moyenne</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col3:
        st.markdown(f"""
        <div class="stat-card fade-in">
            <div style="font-size: 2rem; margin-bottom: 0.5rem;">🏆</div>
            <div style="font-size: 2rem; font-weight: 700;">{stats['completed_goals']}</div>
            <div>Objectifs Terminés</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col4:
        st.markdown(f"""
        <div class="stat-card fade-in">
            <div style="font-size: 2rem; margin-bottom: 0.5rem;">⏰</div>
            <div style="font-size: 2rem; font-weight: 700;">{stats['due_soon_goals']}</div>
            <div>À Terminer</div>
        </div>
        """, unsafe_allow_html=True)
    
    # Section graphiques
    st.markdown('<h2 class="sub-header">📊 Analyse Visuelle</h2>', unsafe_allow_html=True)
    
    goals = db.get_goals()
    
    if goals and len(goals) > 0:
        df = pd.DataFrame(goals)
        
        # S'assurer que current_progress est numérique
        df['current_progress'] = pd.to_numeric(df['current_progress'], errors='coerce').fillna(0)
        
        # Graphiques
        col1, col2 = st.columns(2)
        
        with col1:
            # Graphique à barres
            if len(df) > 0:
                fig1 = px.bar(df, x='name', y='current_progress',
                             color='priority',
                             title="Progression par Objectif",
                             color_discrete_map={
                                 'Urgent': '#DC2626',
                                 'Haute': '#EF4444',
                                 'Moyenne': '#F59E0B',
                                 'Basse': '#10B981'
                             },
                             height=400)
                fig1.update_layout(
                    xaxis_title="Objectifs", 
                    yaxis_title="Progression (%)",
                    xaxis_tickangle=-45
                )
                st.plotly_chart(fig1, use_container_width=True)
            else:
                st.info("Aucun objectif à afficher dans le graphique.")
        
        with col2:
            # Camembert par catégorie
            if len(df) > 0:
                fig2 = px.pie(df, names='category', 
                             title="Répartition par Catégorie",
                             height=400)
                st.plotly_chart(fig2, use_container_width=True)
            else:
                st.info("Aucun objectif à afficher dans le graphique.")
        
        # NOTE: Section "Objectifs Prioritaires" a été supprimée comme demandé
        
        # Activités récentes
        st.markdown('<h2 class="sub-header">📝 Activités Récentes</h2>', unsafe_allow_html=True)
        
        activities = stats.get('recent_activities', [])
        
        if activities:
            for activity in activities:
                with st.container():
                    cols = st.columns([3, 1])
                    with cols[0]:
                        st.write(f"**{activity.get('goal_name', 'Système')}**")
                        st.write(activity.get('description', ''))
                    with cols[1]:
                        timestamp = activity.get('timestamp', '')
                        if timestamp:
                            st.caption(timestamp[:16])
                    st.divider()
        else:
            st.info("Aucune activité récente à afficher.")
    else:
        # Écran de bienvenue
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            st.markdown("""
            <div style="text-align: center; padding: 3rem; background: linear-gradient(135deg, #667eea15 0%, #764ba215 100%); 
                 border-radius: 20px; margin: 2rem 0;">
                <h3 style="color: #4B5563;">🎯 Bienvenue sur GoalMaster Pro !</h3>
                <p style="color: #6B7280;">Commencez par ajouter votre premier objectif pour suivre vos progrès.</p>
                <p style="color: #6B7280; font-size: 0.9rem;">Allez dans la section "Objectifs" ➕ pour créer votre premier objectif.</p>
            </div>
            """, unsafe_allow_html=True)

def goals_page(db):
    """Page de gestion des objectifs"""
    st.markdown('<h1 class="main-header">🎯 Gestion des Objectifs</h1>', unsafe_allow_html=True)
    
    # Onglets
    tab1, tab2 = st.tabs(["📋 Liste des Objectifs", "➕ Nouvel Objectif"])
    
    with tab1:
        # Filtres
        goals_list = db.get_goals()
        categories = ['Toutes'] + sorted(list(set([g.get('category', 'Général') for g in goals_list])))
        
        col1, col2, col3 = st.columns(3)
        with col1:
            category_filter = st.selectbox("Catégorie", categories, key="category_filter")
        with col2:
            priority_filter = st.selectbox("Priorité", ["Toutes", "Urgent", "Haute", "Moyenne", "Basse"], key="priority_filter")
        with col3:
            status_filter = st.selectbox("Statut", ["Tous", "En cours", "Terminé", "En retard"], key="status_filter")
        
        # Appliquer les filtres
        filters = {}
        if category_filter != 'Toutes':
            filters['category'] = category_filter
        if priority_filter != 'Toutes':
            filters['priority'] = priority_filter
        if status_filter != 'Tous':
            filters['status'] = status_filter
        
        # Récupérer les objectifs filtrés
        goals = db.get_goals(filters)
        
        if goals:
            for goal in goals:
                with st.expander(f"{goal['name']} - {goal.get('current_progress', 0):.1f}%", expanded=False):
                    col_a, col_b = st.columns([3, 1])
                    
                    with col_a:
                        st.write(f"**Description :** {goal.get('description', 'Non renseignée')}")
                        st.write(f"**Catégorie :** {goal.get('category', 'Non catégorisé')}")
                        st.write(f"**Priorité :** {goal.get('priority', 'Moyenne')}")
                        st.write(f"**Date cible :** {goal.get('target_date', 'Non définie')}")
                        st.write(f"**Statut :** {goal.get('status', 'En cours')}")
                        
                        # Mise à jour de la progression
                        current_progress = goal.get('current_progress', 0)
                        new_progress = st.slider(
                            "Progression (%)", 
                            0.0, 100.0, 
                            float(current_progress),
                            key=f"progress_slider_{goal['id']}"
                        )
                        
                        # Bouton de mise à jour
                        if st.button("💾 Mettre à jour", key=f"update_btn_{goal['id']}"):
                            db.update_goal_progress(goal['id'], new_progress)
                            st.success("✅ Progression mise à jour !")
                            st.rerun()
                    
                    with col_b:
                        # Bouton suppression
                        if st.button("🗑️ Supprimer", key=f"delete_btn_{goal['id']}"):
                            db.delete_goal(goal['id'])
                            st.success("✅ Objectif supprimé !")
                            st.rerun()
                    
                    # Sous-tâches
                    st.subheader("📝 Sous-tâches")
                    subtasks = db.get_subtasks(goal['id'])
                    
                    if subtasks:
                        for subtask in subtasks:
                            cols = st.columns([4, 1])
                            with cols[0]:
                                st.write(f"• {subtask['name']}")
                            with cols[1]:
                                completed = st.checkbox(
                                    "Terminé", 
                                    value=bool(subtask.get('completed', False)),
                                    key=f"subtask_checkbox_{subtask['id']}"
                                )
                                if st.button("Mettre à jour", key=f"update_subtask_{subtask['id']}"):
                                    db.update_subtask_status(subtask['id'], completed)
                                    st.success("✅ Statut mis à jour !")
                                    st.rerun()
                    else:
                        st.info("Aucune sous-tâche pour cet objectif.")
                    
                    # Ajouter une sous-tâche
                    st.subheader("Ajouter une sous-tâche")
                    with st.form(key=f"add_subtask_form_{goal['id']}"):
                        new_subtask = st.text_input("Nouvelle sous-tâche", key=f"new_subtask_{goal['id']}")
                        submit_subtask = st.form_submit_button("➕ Ajouter")
                        
                        if submit_subtask and new_subtask:
                            db.add_subtask(goal['id'], {"name": new_subtask})
                            st.success("✅ Sous-tâche ajoutée !")
                            st.rerun()
        
        else:
            st.info("📭 Aucun objectif trouvé avec ces filtres.")
    
    with tab2:
        st.markdown('<h2 class="sub-header">Créer un nouvel objectif</h2>', unsafe_allow_html=True)
        
        # Créer un conteneur stylisé pour le formulaire
        with st.container():
            st.markdown('<div class="form-container">', unsafe_allow_html=True)
            
            # Formulaire pour créer un objectif
            goal_name = st.text_input("Nom de l'objectif*", 
                                     placeholder="Ex: Apprendre Python",
                                     key="goal_name_input")
            
            goal_description = st.text_area("Description*", 
                                           placeholder="Décrivez votre objectif en détail...",
                                           height=120,
                                           key="goal_description_input")
            
            col1, col2 = st.columns(2)
            with col1:
                category = st.selectbox(
                    "Catégorie*",
                    ["Professionnel", "Personnel", "Santé", "Finance", "Éducation", "Loisirs", "Autre"],
                    key="category_select"
                )
            
            with col2:
                priority = st.selectbox(
                    "Priorité*",
                    ["Basse", "Moyenne", "Haute", "Urgent"],
                    key="priority_select"
                )
            
            col3, col4 = st.columns(2)
            with col3:
                target_date = st.date_input(
                    "Date cible*",
                    min_value=datetime.now().date(),
                    value=datetime.now().date() + timedelta(days=30),
                    key="target_date_input"
                )
            
            with col4:
                initial_progress = st.slider("Progression initiale (%)", 0.0, 100.0, 0.0, key="progress_slider")
            
            # Tags optionnels
            tags = st.multiselect(
                "Tags (optionnel)",
                ["Important", "À long terme", "Quotidien", "Hebdomadaire", "Mensuel", "Challenge"],
                key="tags_multiselect"
            )
            
            # Bouton de soumission
            create_button = st.button("🎯 Créer l'objectif", width='stretch', key="create_goal_button")
            
            if create_button:
                if goal_name and goal_description:
                    try:
                        goal_data = {
                            'name': goal_name,
                            'description': goal_description,
                            'category': category,
                            'priority': priority,
                            'target_date': target_date.strftime('%Y-%m-%d'),
                            'current_value': initial_progress,
                            'tags': tags
                        }
                        
                        goal_id = db.create_goal(goal_data)
                        
                        # Afficher le succès avec un message spécifique
                        st.success("✅ Objectif ajouté avec succès !")
                        st.balloons()
                        
                        # Ajouter un délai avant le rerun pour que l'utilisateur voie le message
                        st.session_state.show_success_message = True
                        
                        # Réinitialiser les champs
                        st.rerun()
                        
                    except Exception as e:
                        st.error(f"❌ Erreur lors de la création : {str(e)}")
                else:
                    st.error("❌ Veuillez remplir tous les champs obligatoires (*)")
            
            # Afficher un message de succès persistant si nécessaire
            if st.session_state.get('show_success_message', False):
                st.success("✅ Objectif ajouté avec succès !")
                # Réinitialiser après affichage
                st.session_state.show_success_message = False
            
            st.markdown('</div>', unsafe_allow_html=True)

def analytics_page(db):
    """Page d'analyses avancées"""
    st.markdown('<h1 class="main-header">📊 Analytics Avancés</h1>', unsafe_allow_html=True)
    
    goals = db.get_goals()
    
    if not goals:
        st.info("📊 Ajoutez des objectifs pour voir les analyses détaillées.")
        return
    
    df = pd.DataFrame(goals)
    
    # S'assurer que les colonnes nécessaires existent et sont numériques
    if 'current_progress' in df.columns:
        df['current_progress'] = pd.to_numeric(df['current_progress'], errors='coerce').fillna(0)
    
    # Métriques avancées
    st.markdown('<h2 class="sub-header">📈 Métriques Clés</h2>', unsafe_allow_html=True)
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        if len(df) > 0 and 'current_progress' in df.columns:
            completion_rate = ((df['current_progress'] >= 100).sum() / len(df)) * 100
            st.metric("Taux de Complétion", f"{completion_rate:.1f}%")
        else:
            st.metric("Taux de Complétion", "N/A")
    
    with col2:
        st.metric("Objectifs Totaux", len(df))
    
    with col3:
        if len(df) > 0 and 'current_progress' in df.columns:
            avg_progress = df['current_progress'].mean()
            st.metric("Progression Moyenne", f"{avg_progress:.1f}%")
        else:
            st.metric("Progression Moyenne", "N/A")
    
    with col4:
        if 'priority' in df.columns:
            high_priority = len(df[df['priority'].isin(['Haute', 'Urgent'])])
            st.metric("Haute Priorité", high_priority)
        else:
            st.metric("Haute Priorité", 0)
    
    # Graphiques avancés
    st.markdown('<h2 class="sub-header">📊 Visualisations</h2>', unsafe_allow_html=True)
    
    col1, col2 = st.columns(2)
    
    with col1:
        # Graphique à barres
        if len(df) > 0 and 'current_progress' in df.columns and 'name' in df.columns:
            fig = px.bar(df, x='name', y='current_progress',
                        title="Progression des Objectifs",
                        color='priority',
                        color_discrete_map={
                            'Urgent': '#DC2626',
                            'Haute': '#EF4444',
                            'Moyenne': '#F59E0B',
                            'Basse': '#10B981'
                        },
                        height=400)
            fig.update_layout(
                xaxis_title="Objectifs",
                yaxis_title="Progression (%)",
                xaxis_tickangle=-45
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Données insuffisantes pour le graphique")
    
    with col2:
        # Camembert par statut
        if len(df) > 0 and 'status' in df.columns:
            status_counts = df['status'].value_counts()
            if len(status_counts) > 0:
                fig = px.pie(
                    values=status_counts.values,
                    names=status_counts.index,
                    title="Répartition par Statut",
                    height=400
                )
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("Données insuffisantes pour le graphique")
        else:
            st.info("Données insuffisantes pour le graphique")
    
    # Insights
    st.markdown('<h2 class="sub-header">💡 Insights Intelligents</h2>', unsafe_allow_html=True)
    
    insights = []
    
    # Objectifs en retard
    if 'status' in df.columns:
        overdue = df[df['status'] == 'En retard']
        if len(overdue) > 0:
            insights.append(f"⚠️ **{len(overdue)} objectif(s) en retard** - Priorisez ces tâches immédiatement.")
    
    # Objectifs presque terminés
    if 'current_progress' in df.columns and 'status' in df.columns:
        almost_done = df[(df['current_progress'] >= 90) & (df['current_progress'] < 100) & (df['status'] == 'En cours')]
        if len(almost_done) > 0:
            insights.append(f"🎯 **{len(almost_done)} objectif(s) presque terminé(s)** - Un dernier effort !")
    
    # Objectifs à faible progression
    if 'current_progress' in df.columns and 'status' in df.columns:
        low_progress = df[(df['current_progress'] < 30) & (df['status'] == 'En cours')]
        if len(low_progress) > 0:
            insights.append(f"📉 **{len(low_progress)} objectif(s) à faible progression** - Considérez de les réévaluer.")
    
    # Distribution des priorités
    if 'priority' in df.columns:
        high_priority_count = len(df[df['priority'].isin(['Haute', 'Urgent'])])
        if len(df) > 0 and high_priority_count / len(df) > 0.6:
            insights.append("🎯 **Trop d'objectifs haute priorité** - Revoyez votre système de priorisation.")
    
    # Afficher les insights
    if insights:
        for insight in insights[:4]:
            st.info(insight)
    else:
        st.success("✅ Tous vos objectifs sont sur la bonne voie !")

def reports_page(db):
    """Page de génération de rapports"""
    st.markdown('<h1 class="main-header">📄 Rapports & Export</h1>', unsafe_allow_html=True)
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown('<h2 class="sub-header">📊 Générer un Rapport</h2>', unsafe_allow_html=True)
        
        # Conteneur pour le formulaire
        with st.container():
            st.markdown('<div class="form-container">', unsafe_allow_html=True)
            
            report_type = st.selectbox(
                "Type de rapport",
                ["Rapport Complet", "Rapport Hebdomadaire", "Rapport Mensuel", "Rapport par Priorité"],
                key="report_type_select"
            )
            
            include_stats = st.checkbox("Inclure les statistiques", value=True, key="include_stats_check")
            include_goals = st.checkbox("Inclure la liste des objectifs", value=True, key="include_goals_check")
            include_recommendations = st.checkbox("Inclure les recommandations", value=True, key="include_recommendations_check")
            
            if st.button("📄 Générer le Rapport PDF", width='stretch', key="generate_report_button"):
                with st.spinner("🔄 Génération du rapport en cours..."):
                    try:
                        pdf_generator = PDFReport()
                        report_path = pdf_generator.generate_report(db)
                        
                        if report_path:
                            # Lire le fichier PDF
                            with open(report_path, "rb") as f:
                                pdf_bytes = f.read()
                            
                            # Afficher le bouton de téléchargement
                            st.download_button(
                                label="📥 Télécharger le Rapport PDF",
                                data=pdf_bytes,
                                file_name="rapport_objectifs.pdf",
                                mime="application/pdf",
                                width='stretch',
                                key="download_pdf_button"
                            )
                            
                            st.success("✅ Rapport généré avec succès !")
                        else:
                            st.error("❌ Erreur lors de la génération du PDF")
                    except Exception as e:
                        st.error(f"❌ Erreur lors de la génération : {str(e)}")
            
            st.markdown('</div>', unsafe_allow_html=True)
    
    with col2:
        st.markdown('<h2 class="sub-header">📈 Exporter les Données</h2>', unsafe_allow_html=True)
        
        goals = db.get_goals()
        
        if goals:
            df = pd.DataFrame(goals)
            
            # Exporter en CSV
            csv_data = df.to_csv(index=False).encode('utf-8')
            
            st.download_button(
                label="📊 Télécharger CSV (.csv)",
                data=csv_data,
                file_name="objectifs_export.csv",
                mime="text/csv",
                width='stretch',
                key="download_csv_button"
            )
            
            # Exporter en JSON
            json_data = json.dumps(goals, indent=2, ensure_ascii=False, default=str)
            
            st.download_button(
                label="📋 Télécharger JSON (.json)",
                data=json_data,
                file_name="objectifs_export.json",
                mime="application/json",
                width='stretch',
                key="download_json_button"
            )
        else:
            st.info("Aucune donnée à exporter.")
    
    # Prévisualisation
    st.markdown('<h2 class="sub-header">👁️ Prévisualisation des Données</h2>', unsafe_allow_html=True)
    
    goals = db.get_goals()
    if goals:
        df_preview = pd.DataFrame(goals)
        
        # Sélectionner les colonnes à afficher
        columns_to_show = ['name', 'category', 'priority', 'current_progress', 'target_date', 'status']
        available_columns = [col for col in columns_to_show if col in df_preview.columns]
        
        if available_columns:
            st.dataframe(
                df_preview[available_columns],
                use_container_width=True,
                height=300
            )
        else:
            st.info("Aucune donnée disponible pour la prévisualisation.")
    else:
        st.info("Aucune donnée disponible pour la prévisualisation.")

# ============================================
# APPLICATION PRINCIPALE
# ============================================
def main():
    # Initialiser la base de données
    db = get_database()
    
    # Initialiser les variables de session
    if 'show_success_message' not in st.session_state:
        st.session_state.show_success_message = False
    
    # Sidebar - Navigation
    st.sidebar.markdown("""
    <div style="text-align: center; margin-bottom: 2rem;">
        <h1 style="font-size: 2rem; margin: 0;">🎯</h1>
        <h2 style="font-size: 1.5rem; margin: 0.5rem 0; color: #4B5563;">GoalMaster Pro</h2>
        <p style="color: #6B7280; font-size: 0.9rem;">Suivi d'Objectifs Intelligents</p>
    </div>
    """, unsafe_allow_html=True)
    
    st.sidebar.markdown("---")
    
    # Initialiser la variable de navigation dans session_state
    if 'page' not in st.session_state:
        st.session_state.page = "📊 Tableau de Bord"
    
    # Navigation - version corrigée sans session_state problématique
    page_options = ["📊 Tableau de Bord", "🎯 Objectifs", "📈 Analytics", "📄 Rapports"]
    
    # Créer un widget de navigation simple
    page_selection = st.sidebar.selectbox(
        "Navigation",
        page_options,
        index=page_options.index(st.session_state.page) if st.session_state.page in page_options else 0,
        key="page_select",
        label_visibility="collapsed"
    )
    
    # Mettre à jour la page dans session_state
    if page_selection != st.session_state.page:
        st.session_state.page = page_selection
        st.rerun()
    
    # Utiliser la page de session_state
    page = st.session_state.page
    
    # Statistiques rapides
    st.sidebar.markdown("---")
    st.sidebar.markdown("### 📊 Aperçu Rapide")
    
    stats = db.get_statistics()
    col1, col2 = st.sidebar.columns(2)
    with col1:
        st.metric("Objectifs", stats['total_goals'])
    with col2:
        st.metric("Progression", f"{stats['avg_progress']:.1f}%")
    
    # Actions rapides
    st.sidebar.markdown("---")
    st.sidebar.markdown("### ⚡ Actions Rapides")
    
    # Footer
    st.sidebar.markdown("---")
    st.sidebar.markdown("""
    <div style="text-align: center; color: #6B7280; font-size: 0.8rem; padding: 1rem 0;">
        <p>Version 4.0.0</p>
        <p>© 2024 GoalMaster Pro</p>
    </div>
    """, unsafe_allow_html=True)
    
    # Afficher la page sélectionnée
    if page == "📊 Tableau de Bord":
        dashboard_page(db)
    elif page == "🎯 Objectifs":
        goals_page(db)
    elif page == "📈 Analytics":
        analytics_page(db)
    elif page == "📄 Rapports":
        reports_page(db)

if __name__ == "__main__":
    main()

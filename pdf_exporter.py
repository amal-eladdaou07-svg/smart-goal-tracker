from fpdf import FPDF
from datetime import datetime
import sqlite3
from typing import List, Dict

class PDFReport(FPDF):
    def __init__(self, db_path: str = "goals.db"):
        super().__init__()
        self.db_path = db_path
        self.set_auto_page_break(auto=True, margin=15)
    
    def header(self):
        # Logo
        self.image('assets/logo.png', 10, 8, 33)
        # Title
        self.set_font('Arial', 'B', 16)
        self.cell(0, 10, 'Rapport de Progression des Objectifs', 0, 1, 'C')
        # Date
        self.set_font('Arial', 'I', 10)
        self.cell(0, 10, f"Généré le {datetime.now().strftime('%d/%m/%Y %H:%M')}", 0, 1, 'C')
        self.ln(10)
    
    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.cell(0, 10, f'Page {self.page_no()}', 0, 0, 'C')
    
    def add_statistics_section(self, stats: Dict):
        self.set_font('Arial', 'B', 14)
        self.cell(0, 10, 'Statistiques Générales', 0, 1)
        self.set_font('Arial', '', 12)
        
        col_width = self.w / 3 - 10
        self.cell(col_width, 10, f"Objectifs totaux: {stats['total_goals']}", 1, 0, 'C')
        self.cell(col_width, 10, f"Progression moyenne: {stats['avg_progress']:.1f}%", 1, 0, 'C')
        self.cell(col_width, 10, f"Objectifs terminés: {stats['completed_goals']}", 1, 1, 'C')
        
        self.ln(5)
    
    def add_goals_table(self, goals: List[Dict]):
        self.set_font('Arial', 'B', 14)
        self.cell(0, 10, 'Détails des Objectifs', 0, 1)
        
        # Table header
        self.set_font('Arial', 'B', 11)
        col_widths = [40, 50, 25, 20, 20, 25]
        
        headers = ['Objectif', 'Description', 'Priorité', 'Progression', 'Date cible', 'Statut']
        for i, header in enumerate(headers):
            self.cell(col_widths[i], 10, header, 1, 0, 'C')
        self.ln()
        
        # Table rows
        self.set_font('Arial', '', 10)
        for goal in goals:
            # Truncate description if too long
            desc = goal['description'][:30] + '...' if len(goal['description']) > 30 else goal['description']
            
            self.cell(col_widths[0], 10, goal['name'], 1, 0, 'L')
            self.cell(col_widths[1], 10, desc, 1, 0, 'L')
            self.cell(col_widths[2], 10, goal['priority'], 1, 0, 'C')
            self.cell(col_widths[3], 10, f"{goal['current_progress']}%", 1, 0, 'C')
            self.cell(col_widths[4], 10, goal['target_date'], 1, 0, 'C')
            self.cell(col_widths[5], 10, goal['status'], 1, 0, 'C')
            self.ln()
        
        self.ln(10)
    
    def add_progress_chart_section(self):
        self.set_font('Arial', 'B', 14)
        self.cell(0, 10, 'Analyse des Progrès', 0, 1)
        
        # Placeholder pour graphique
        self.set_font('Arial', 'I', 10)
        self.multi_cell(0, 10, "Graphiques de progression disponibles dans la version numérique du rapport.")
        self.ln(5)
    
    def add_recommendations(self, recommendations: List[str]):
        self.set_font('Arial', 'B', 14)
        self.cell(0, 10, 'Recommandations', 0, 1)
        
        self.set_font('Arial', '', 11)
        for i, rec in enumerate(recommendations, 1):
            self.multi_cell(0, 8, f"{i}. {rec}")
            self.ln(2)
    
    def generate_report(self, output_path: str = "rapport_progression.pdf"):
        # Connect to database
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Get statistics
        cursor.execute("""
            SELECT 
                COUNT(*) as total_goals,
                AVG(current_progress) as avg_progress,
                SUM(CASE WHEN current_progress >= 100 THEN 1 ELSE 0 END) as completed_goals
            FROM goals
        """)
        stats = dict(cursor.fetchone())
        
        # Get goals
        cursor.execute("SELECT * FROM goals ORDER BY priority DESC, target_date")
        goals = [dict(row) for row in cursor.fetchall()]
        
        # Generate PDF
        self.add_page()
        self.add_statistics_section(stats)
        self.add_goals_table(goals)
        self.add_progress_chart_section()
        
        # Recommendations
        recommendations = [
            "Concentrez-vous sur les objectifs à haute priorité qui approchent de leur date limite.",
            "Décomposez les objectifs complexes en sous-tâches plus gérables.",
            "Revoyez régulièrement vos objectifs pour ajuster les priorités si nécessaire.",
            "Célébrez les petites victoires pour maintenir la motivation."
        ]
        self.add_recommendations(recommendations)
        
        # Save PDF
        self.output(output_path)
        conn.close()
        return output_path

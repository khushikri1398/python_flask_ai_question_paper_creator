from fpdf import FPDF

class OMRGenerator(FPDF):
    def __init__(self, total_questions):
        super().__init__()
        self.total_questions = total_questions
        # Default number of questions per subject
        questions_per_subject = total_questions // 5
        # Calculate how many questions each subject should have
        self.subject_questions = [questions_per_subject] * 5
        # Add any remaining questions to the first subject
        self.subject_questions[0] += total_questions % 5
        
        self.bubble_diameter = 4.5  # Smaller bubble size for better fit
        self.page_height = 297
        self.page_width = 210
        self.set_auto_page_break(auto=False)
        self.set_font("Helvetica", "", 8)

    def draw_target_logo(self, x, y, r):
        # Creates the circular target logo like in the image
        self.set_draw_color(0, 0, 0)
        self.set_fill_color(255, 255, 255)
        self.ellipse(x, y, 2*r, 2*r, 'D')
        self.ellipse(x+r*0.3, y+r*0.3, 2*r*0.7, 2*r*0.7, 'D')
        self.ellipse(x+r*0.6, y+r*0.6, 2*r*0.4, 2*r*0.4, 'D')
        self.set_fill_color(0, 0, 0)
        self.ellipse(x+r*0.8, y+r*0.8, 2*r*0.2, 2*r*0.2, 'F')

    def header(self):
        # Draw target logos in all four corners
        r = 7
        self.draw_target_logo(20, 20, r)
        self.draw_target_logo(self.page_width-20, 20, r)
        self.draw_target_logo(20, self.page_height-20, r)
        self.draw_target_logo(self.page_width-20, self.page_height-20, r)
        
        # Title
        self.set_font("Helvetica", "B", 12)
        self.set_xy(0, 20)
        self.cell(self.page_width, 10, "OMR Answer Sheet", 0, 1, "C")

    def add_instructions(self):
        self.set_font("Helvetica", "", 8)
        self.set_xy(90, 30)
        self.cell(0, 5, "Instructions for filling the sheet:", 0, 2)
        instructions = [
            "- Circle should be darkened completely.",
            "- Don't fold the sheet. Answer once marked cannot be changed.",
            "- Use only ball pen to darken the appropriate circle.",
            "- Only use UPPER CASE CAPITAL LETTER ALPHABETS in the boxes."
        ]
        for line in instructions:
            self.cell(0, 4, line, 0, 2)

    def add_student_info_fields(self):
        # Student info section based on image
        self.set_font("Helvetica", "", 8)
        self.set_xy(95, 55)
        
        # The student info grid as seen in the image
        info_fields = [
            ("Student Name", 50),
            ("Exam Name", 30),
            ("Class (6,7,8,9)", 20),
            ("Section", 10),
            ("Date", 20)
        ]
        
        # Admission number section
        self.set_xy(10, 55)
        self.cell(30, 6, "Admission number", 1, 1, 'C')
        
        # Create student info header row
        x = 45
        y = 55
        self.set_xy(x, y)
        for label, width in info_fields:
            self.cell(width, 6, label, 1, 0, 'C')
        
        # Create empty info field row
        self.ln(6)
        self.set_x(x)
        for _, width in info_fields:
            self.cell(width, 6, "", 1, 0)
        
        # Create admission number bubbles grid
        x = 10
        y = 61
        cols = 5  # 5 columns of bubbles
        rows = 10  # 0-9 digits
        
        for row in range(rows):
            self.set_xy(x, y + row*6)
            self.cell(5, 6, str(row), 1, 0, 'C')
            
            for col in range(cols):
                self.set_xy(x + 5 + col*5, y + row*6)
                self.cell(5, 6, "", 0, 0)
                self.ellipse(x + 7.5 + col*5, y + row*6 + 3, self.bubble_diameter, self.bubble_diameter)

    def add_question_bubbles(self):
        # Question section setup
        subjects = ["Mathematics", "Mathematics", "Physics", "Chemistry", "MAT"]
        options = ['a', 'b', 'c', 'd']
        
        x_start = 20
        y_start = 125  # Start below the admission number section
        total_width = 170
        col_width = total_width / len(subjects)
        row_height = 6
        
        # Add subject headers
        self.set_font("Helvetica", "B", 8)
        for i, subject in enumerate(subjects):
            self.set_xy(x_start + i*col_width, y_start)
            self.cell(col_width, 6, subject, 0, 0, 'C')
        
        # Add option letters above bubble columns
        self.set_font("Helvetica", "", 7)
        for i, subject in enumerate(subjects):
            x = x_start + i*col_width
            for j, opt in enumerate(options):
                self.set_xy(x + 10 + j*6, y_start + 6)
                self.cell(6, 5, opt, 0, 0, 'C')
        
        # Add question bubbles
        q_count = 0
        max_rows = 20  # Number of questions per column
        
        for section in range(len(subjects)):
            start_q = q_count
            section_questions = min(self.subject_questions[section], max_rows)
            
            for q in range(section_questions):
                q_num = q + start_q + 1
                
                if q_num > self.total_questions:
                    break
                
                # Question number
                x = x_start + section*col_width
                y = y_start + 12 + q*row_height
                self.set_xy(x, y)
                self.set_font("Helvetica", "", 7)
                self.cell(10, 5, f"Q{q_num:03d}", 0, 0)
                
                # Option bubbles
                for o in range(len(options)):
                    bx = x + 10 + o*6
                    by = y + 2.5
                    self.ellipse(bx, by, self.bubble_diameter, self.bubble_diameter)
            
            q_count += section_questions

    def add_signature_fields(self):
        # Signature fields at bottom
        self.set_y(self.page_height - 25)
        self.set_font("Helvetica", "", 8)
        self.cell(80, 5, "Invigilator's Signature: _________________", 0, 0)
        self.cell(80, 5, "Student's Signature: _________________", 0, 1)

    def generate(self):
        self.add_page()
        self.add_instructions()
        self.add_student_info_fields()
        self.add_question_bubbles()
        self.add_signature_fields()
        return self.output(dest='S').encode('latin-1')

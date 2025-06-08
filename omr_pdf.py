from fpdf import FPDF

class OMRGenerator(FPDF):
    def __init__(self, subject_questions):
        super().__init__()
        self.subjects = ["Mathematics-1", "Mathematics-2", "Physics", "Chemistry", "MAT"]
        self.subject_questions = subject_questions  # List of 5 integers
        self.total_questions = sum(subject_questions)
        self.bubble_diameter = 4.5
        self.page_height = 297
        self.page_width = 210
        self.set_auto_page_break(auto=False)
        self.set_font("Helvetica", "", 8)
        self.options = ['a', 'b', 'c', 'd']

    def draw_target_logo(self, x, y, r):
        self.set_draw_color(0, 0, 0)
        self.set_fill_color(255, 255, 255)
        self.ellipse(x, y, 2*r, 2*r, 'D')
        self.ellipse(x+r*0.3, y+r*0.3, 2*r*0.7, 2*r*0.7, 'D')
        self.ellipse(x+r*0.6, y+r*0.6, 2*r*0.4, 2*r*0.4, 'D')
        self.set_fill_color(0, 0, 0)
        self.ellipse(x+r*0.8, y+r*0.8, 2*r*0.2, 2*r*0.2, 'F')

    def header(self):
        r = 7
        self.draw_target_logo(20, 20, r)
        self.draw_target_logo(self.page_width-20, 20, r)
        self.draw_target_logo(20, self.page_height-20, r)
        self.draw_target_logo(self.page_width-20, self.page_height-20, r)
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
        self.set_font("Helvetica", "", 8)
        self.set_xy(95, 55)
        info_fields = [
            ("Student Name", 50),
            ("Exam Name", 30),
            ("Class (6,7,8,9)", 20),
            ("Section", 10),
            ("Date", 20)
        ]
        # Admission number section label
        self.set_xy(10, 55)
        self.cell(30, 6, "Admission number", 1, 1, 'C')
        # Student info header row
        x = 45
        y = 55
        self.set_xy(x, y)
        for label, width in info_fields:
            self.cell(width, 6, label, 1, 0, 'C')
        # Empty info field row
        self.ln(6)
        self.set_x(x)
        for _, width in info_fields:
            self.cell(width, 6, "", 1, 0)
        # Admission number section with empty boxes
        x = 10
        y = 61
        cols = 5
        self.set_xy(x, y)
        for col in range(cols):
            self.cell(6, 8, "", 1, 0, 'C')

    def add_signature_fields(self):
        self.set_y(self.page_height - 25)
        self.set_font("Helvetica", "", 8)
        self.cell(80, 5, "Invigilator's Signature: _________________", 0, 0)
        self.cell(80, 5, "Student's Signature: _________________", 0, 1)

    def add_question_bubbles(self):
        x_start = 20
        y_start_first = 125  # after student info
        y_start_others = 40  # higher up on subsequent pages
        total_width = 170
        col_width = total_width / len(self.subjects)
        row_height = 6

        # Find max questions in any subject
        max_questions = max(self.subject_questions)
        question_indices = [0] * len(self.subjects)
        page = 1
        current_row = 0
        finished = False

        while not finished:
            if page == 1:
                y_start = y_start_first
            else:
                self.add_page()
                y_start = y_start_others

            # Draw subject headers
            self.set_font("Helvetica", "B", 8)
            for i, subject in enumerate(self.subjects):
                self.set_xy(x_start + i*col_width, y_start)
                self.cell(col_width, 6, subject, 0, 0, 'C')
            # Draw option letters
            self.set_font("Helvetica", "", 7)
            for i in range(len(self.subjects)):
                x = x_start + i*col_width
                for j, opt in enumerate(self.options):
                    self.set_xy(x + 10 + j*6, y_start + 6)
                    self.cell(6, 5, opt, 0, 0, 'C')

            # Compute max rows per page
            if page == 1:
                max_rows = int((self.page_height - (y_start + 12) - 30) // row_height)
            else:
                max_rows = int((self.page_height - (y_start + 12) - 30) // row_height)

            rows_drawn = 0
            for row in range(max_rows):
                any_drawn = False
                for section in range(len(self.subjects)):
                    if question_indices[section] < self.subject_questions[section]:
                        x = x_start + section*col_width
                        y = y_start + 12 + row*row_height
                        qnum = question_indices[section] + 1
                        self.set_xy(x, y)
                        self.set_font("Helvetica", "", 7)
                        self.cell(10, 5, f"Q{qnum:03d}", 0, 0)
                        for o in range(len(self.options)):
                            bx = x + 10 + o*6
                            by = y + 2.5
                            self.ellipse(bx, by, self.bubble_diameter, self.bubble_diameter)
                        question_indices[section] += 1
                        any_drawn = True
                rows_drawn += 1
                if all(qi >= sq for qi, sq in zip(question_indices, self.subject_questions)):
                    finished = True
                    break
            page += 1

    def generate(self):
        self.add_page()
        self.add_instructions()
        self.add_student_info_fields()
        self.add_question_bubbles()
        self.add_signature_fields()
        return self.output(dest='S').encode('latin-1')

from flask import Flask, render_template, request,jsonify,flash,session,redirect,url_for
from jinja2 import ChoiceLoader, FileSystemLoader
from werkzeug.security import generate_password_hash, check_password_hash
from flask_mysqldb import MySQL
import re
import torch
import torch.nn as nn
import torch.nn.functional as F
from torchvision import transforms
from PIL import Image
import io
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY', 'dev-change-this-secret-key')
app.jinja_loader = ChoiceLoader([
    FileSystemLoader('templates'),
    FileSystemLoader('templates_login'),
])

# ---------------- MODEL ----------------
class FingerprintCNN(nn.Module):
    def __init__(self, num_classes=8):
        super().__init__()
        self.features = nn.Sequential(
            nn.Conv2d(3, 32, 3, padding=1), nn.ReLU(), nn.MaxPool2d(2),
            nn.Conv2d(32, 64, 3, padding=1), nn.ReLU(), nn.MaxPool2d(2),
            nn.Conv2d(64, 128, 3, padding=1), nn.ReLU(), nn.MaxPool2d(2),
            nn.Conv2d(128, 256, 3, padding=1), nn.ReLU(), nn.MaxPool2d(2)
        )
        self.classifier = nn.Sequential(
            nn.Flatten(),
            nn.Linear(256 * 14 * 14, 512),
            nn.ReLU(),
            nn.Linear(512, num_classes)
        )

    def forward(self, x):
        return self.classifier(self.features(x))


model = FingerprintCNN()
model.load_state_dict(torch.load("fingerprint_cnn_model.pth", map_location="cpu"))
model.eval()

classes = ['A+', 'A-', 'AB+', 'AB-', 'B+', 'B-', 'O+', 'O-']

transform = transforms.Compose([
    transforms.Resize((224, 224)),
    transforms.Grayscale(num_output_channels=3),
    transforms.ToTensor()
])

app.config['MYSQL_HOST'] = os.environ.get('MYSQL_HOST', 'localhost')
app.config['MYSQL_USER'] = os.environ.get('MYSQL_USER', 'root')
app.config['MYSQL_PASSWORD'] = os.environ.get('MYSQL_PASSWORD', 'root')
app.config['MYSQL_DB'] = os.environ.get('MYSQL_DB', 'bloodscan')
app.config['MYSQL_CURSORCLASS'] = 'DictCursor'

mysql = MySQL(app)

# -------------- Helper: create table if not exists --------------
def initialize_database():
    with mysql.connection.cursor() as cursor:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INT AUTO_INCREMENT PRIMARY KEY,
                first_name VARCHAR(100),
                last_name VARCHAR(100),
                email VARCHAR(255) NOT NULL UNIQUE,
                phone VARCHAR(50),
                password_hash VARCHAR(255) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB;
            """
        )
        mysql.connection.commit()


# ---------------- ROUTES ----------------
@app.route("/")
def index():
    return render_template("index.html")
@app.route("/result")
def result():
    return render_template("result.html")


@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect(url_for('index'))

    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')

        if not email or not password:
            flash('Please enter both email and password.', 'error')
            return redirect(url_for('login'))

        cursor = mysql.connection.cursor()
        cursor.execute('SELECT * FROM users WHERE email = %s', (email,))
        user = cursor.fetchone()

        if user and check_password_hash(user['password_hash'], password):
            session['user_id'] = user['id']
            session['user_name'] = f"{user['first_name']} {user['last_name']}"
           # flash('', 'success')
            return redirect(url_for('index'))

        flash('Invalid email or password.', 'error')
        return redirect(url_for('login'))

    return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if 'user_id' in session:
        return redirect(url_for('index'))

    if request.method == 'POST':
        first_name = request.form.get('first_name', '').strip()
        last_name = request.form.get('last_name', '').strip()
        email = request.form.get('email', '').strip().lower()
        phone = request.form.get('phone', '').strip()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')

        if not (first_name and last_name and email and password and confirm_password):
            flash('Please fill in all required fields.', 'error')
            return redirect(url_for('register'))

        if password != confirm_password:
            flash('Passwords do not match.', 'error')
            return redirect(url_for('register'))

        if len(password) < 8:
            flash('Password must be at least 8 characters long.', 'error')
            return redirect(url_for('register'))

        if not re.match(r'[^@]+@[^@]+\.[^@]+', email):
            flash('Invalid email address.', 'error')
            return redirect(url_for('register'))

        cursor = mysql.connection.cursor()
        cursor.execute('SELECT id FROM users WHERE email = %s', (email,))
        existing = cursor.fetchone()

        if existing:
            flash('Email already registered. Please login.', 'error')
            return redirect(url_for('login'))

        password_hash = generate_password_hash(password)
        cursor.execute(
            'INSERT INTO users (first_name, last_name, email, phone, password_hash) VALUES (%s, %s, %s, %s, %s)',
            (first_name, last_name, email, phone, password_hash),
        )
        mysql.connection.commit()

        flash('Registration complete. Please login.', 'success')
        return redirect(url_for('login'))

    return render_template('Register.html')


@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()

        if not email:
            flash('Please enter your email to reset password.', 'error')
            return redirect(url_for('forgot_password'))

        cursor = mysql.connection.cursor()
        cursor.execute('SELECT id FROM users WHERE email = %s', (email,))
        user = cursor.fetchone()

        if user:
            # Real implementation should send email with reset link.
            flash('Check your email for password reset instructions.', 'success')
        else:
            flash('Email not found.', 'error')

        return redirect(url_for('forgot_password'))

    return render_template('Forget.html')


@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        flash('Please login first.', 'error')
        return redirect(url_for('login'))

    return f"<h1>Welcome, {session.get('user_name')}</h1><p><a href='{url_for('logout')}'>Logout</a></p>"


@app.route('/logout')
def logout():
    session.clear()
    flash('You have logged out.', 'success')
    return redirect(url_for('login'))



@app.route("/analyze", methods=["POST"])
def analyze():
    file = request.files.get("image")
    if not file:
        return "No file uploaded"

    image = Image.open(io.BytesIO(file.read()))
    img = transform(image).unsqueeze(0)

    with torch.no_grad():
        output = model(img)
        probs = F.softmax(output, dim=1)
        conf, pred = torch.max(probs, 1)

    blood_group = classes[pred.item()]
    confidence = round(conf.item() * 100, 2)

    predictions = {
        classes[i]: round(probs[0][i].item() * 100, 2)
        for i in range(len(classes))
    }

    return render_template(
        "result.html",
        blood_group=blood_group,
        confidence=confidence,
        predictions=predictions
    )
@app.route("/predict", methods=["POST"])
def predict():
    file = request.files["image"]
    image = Image.open(io.BytesIO(file.read()))
    img = transform(image).unsqueeze(0)

    with torch.no_grad():
        output = model(img)
        probs = F.softmax(output, dim=1)[0]

    all_predictions = {
        classes[i]: round(probs[i].item() * 100, 2)
        for i in range(len(classes))
    }

    predicted_group = max(all_predictions, key=all_predictions.get)
    confidence = all_predictions[predicted_group]

    return jsonify({
        "predicted_group": predicted_group,
        "confidence": confidence,
        "all_predictions": all_predictions
})
if __name__ == "__main__":
    with app.app_context():
        initialize_database()
    app.run(debug=True)

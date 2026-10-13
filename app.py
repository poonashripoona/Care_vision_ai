"""
CARE VISION AI — Flask application.

Upload a skin photo and symptoms, store a preliminary assessment, and
show nearby dummy hospitals. This is guidance only, not a diagnosis.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

from flask import (
    Flask,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import inspect, text
from werkzeug.utils import secure_filename

from models.ml_model import analyze_skin_image

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "bmp"}
MAX_CONTENT_LENGTH = 8 * 1024 * 1024  # 8 MB

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "care-vision-ai-dev-key")
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(BASE_DIR, "database.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH

db = SQLAlchemy(app)


class Assessment(db.Model):
    __tablename__ = "assessments"

    id = db.Column(db.Integer, primary_key=True)
    image_path = db.Column(db.String(512), nullable=False)
    symptoms_text = db.Column(db.Text, default="")
    duration = db.Column(db.String(64), default="")
    progression = db.Column(db.String(64), default="")
    risk_level = db.Column(db.String(32), nullable=False)
    explanation = db.Column(db.Text, nullable=False)
    specialist = db.Column(db.String(256), default="Dermatologist")
    concern_label = db.Column(db.String(256), default="")
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)


class Hospital(db.Model):
    __tablename__ = "hospitals"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    address = db.Column(db.String(256), nullable=False)
    distance_km = db.Column(db.Float, nullable=False)
    available_specialists = db.Column(db.String(256), nullable=False)
    contact_number = db.Column(db.String(64), nullable=False)
    doctors_available = db.Column(db.Integer, default=1)
    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)

    def to_map_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "address": self.address,
            "distance_km": self.distance_km,
            "available_specialists": self.available_specialists,
            "contact_number": self.contact_number,
            "doctors_available": self.doctors_available,
            "lat": self.latitude,
            "lng": self.longitude,
        }


# Demo village center used until the user shares a real location.
DEMO_ORIGIN = {"lat": 20.9460, "lng": 77.7750, "label": "Demo village center"}

SEED_HOSPITALS = [
    {
        "name": "Green Valley Community Hospital",
        "address": "12 Market Road, Riverside Village",
        "distance_km": 2.4,
        "available_specialists": "Dermatologist, General Physician",
        "contact_number": "+91 90000 11111",
        "doctors_available": 3,
        "latitude": 20.9582,
        "longitude": 77.7924,
    },
    {
        "name": "Sunrise Rural Health Centre",
        "address": "NH-44, Mile 8, Near Bus Stand",
        "distance_km": 5.1,
        "available_specialists": "General Physician, Nurse Practitioner",
        "contact_number": "+91 90000 22222",
        "doctors_available": 2,
        "latitude": 20.9104,
        "longitude": 77.8088,
    },
    {
        "name": "Lotus Skin & Care Clinic",
        "address": "45 Temple Street, Central Town",
        "distance_km": 8.7,
        "available_specialists": "Dermatologist",
        "contact_number": "+91 90000 33333",
        "doctors_available": 1,
        "latitude": 20.9921,
        "longitude": 77.8412,
    },
    {
        "name": "District Medical College Hospital",
        "address": "1 Hospital Campus, District HQ",
        "distance_km": 18.3,
        "available_specialists": "Dermatologist, Emergency, General Physician",
        "contact_number": "+91 90000 44444",
        "doctors_available": 6,
        "latitude": 21.0488,
        "longitude": 77.9286,
    },
    {
        "name": "Hope Mobile Clinic (weekly van)",
        "address": "Panchayat Ground, West Hamlet",
        "distance_km": 1.2,
        "available_specialists": "General Physician (visiting)",
        "contact_number": "+91 90000 55555",
        "doctors_available": 1,
        "latitude": 20.9511,
        "longitude": 77.7658,
    },
]


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def ensure_hospital_geo_columns() -> None:
    """Add lat/lng on existing SQLite files created before mapping support."""
    inspector = inspect(db.engine)
    if "hospitals" not in inspector.get_table_names():
        return
    columns = {col["name"] for col in inspector.get_columns("hospitals")}
    with db.engine.begin() as conn:
        if "latitude" not in columns:
            conn.execute(text("ALTER TABLE hospitals ADD COLUMN latitude FLOAT"))
        if "longitude" not in columns:
            conn.execute(text("ALTER TABLE hospitals ADD COLUMN longitude FLOAT"))


def seed_hospitals() -> None:
    if Hospital.query.count() == 0:
        for row in SEED_HOSPITALS:
            db.session.add(Hospital(**row))
        db.session.commit()
        return

    by_name = {row["name"]: row for row in SEED_HOSPITALS}
    for hospital in Hospital.query.all():
        seed = by_name.get(hospital.name)
        if not seed:
            continue
        if hospital.latitude is None or hospital.longitude is None:
            hospital.latitude = seed["latitude"]
            hospital.longitude = seed["longitude"]
    db.session.commit()


with app.app_context():
    db.create_all()
    ensure_hospital_geo_columns()
    seed_hospitals()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/analyze", methods=["POST"])
def analyze():
    image = request.files.get("image")
    symptoms = (request.form.get("symptoms") or "").strip()
    duration = (request.form.get("duration") or "").strip()
    progression = (request.form.get("progression") or "").strip()

    if image is None or image.filename == "":
        flash("Please add a clear photo of the skin area.", "error")
        return redirect(url_for("index"))

    if not allowed_file(image.filename):
        flash("Please upload a photo file (JPG, PNG, or WEBP).", "error")
        return redirect(url_for("index"))

    filename = secure_filename(image.filename)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    stored_name = f"{stamp}_{filename}"
    save_path = os.path.join(app.config["UPLOAD_FOLDER"], stored_name)

    try:
        image.save(save_path)
    except OSError:
        flash("Could not save the photo. Please try again.", "error")
        return redirect(url_for("index"))

    relative_path = f"uploads/{stored_name}"
    try:
        result = analyze_skin_image(
            save_path,
            {
                "symptoms": symptoms,
                "duration": duration,
                "progression": progression,
            },
        )
    except Exception:
        app.logger.exception("Skin analysis failed")
        result = {
            "risk_level": "Moderate",
            "explanation": (
                "We could not fully read the photo, so we treated this as a "
                "moderate concern. Please show the skin to a doctor to be safe. "
                "This is not a diagnosis."
            ),
            "specialist": "Dermatologist or General Physician",
            "concern_label": "Could not fully read the photo",
        }

    record = Assessment(
        image_path=relative_path,
        symptoms_text=symptoms,
        duration=duration,
        progression=progression,
        risk_level=result["risk_level"],
        explanation=result["explanation"],
        specialist=result.get("specialist", "Dermatologist"),
        concern_label=result.get("concern_label", ""),
    )
    db.session.add(record)
    db.session.commit()
    return redirect(url_for("results", assessment_id=record.id))


@app.route("/results/<int:assessment_id>")
def results(assessment_id: int):
    assessment = Assessment.query.get_or_404(assessment_id)
    hospitals = Hospital.query.order_by(Hospital.distance_km.asc()).all()
    return render_template(
        "results.html",
        assessment=assessment,
        hospitals=hospitals,
        hospitals_geo=[h.to_map_dict() for h in hospitals],
        map_origin=DEMO_ORIGIN,
    )


@app.errorhandler(413)
def too_large(_error):
    flash("That photo is too large. Please use a file under 8 MB.", "error")
    return redirect(url_for("index"))


@app.errorhandler(404)
def not_found(_error):
    return (
        "<h1>Page not found</h1><p><a href='/'>Back to CARE VISION AI</a></p>",
        404,
    )


if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5000)

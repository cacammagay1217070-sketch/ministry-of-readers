from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    full_name = db.Column(db.String(150), nullable=False)
    role = db.Column(db.String(20), default='member')  # admin or member
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    phone = db.Column(db.String(30), nullable=True)

    # Relationships
    original_assignments = db.relationship('Assignment', foreign_keys='Assignment.original_user_id', backref='original_user', lazy='dynamic')
    actual_assignments = db.relationship('Assignment', foreign_keys='Assignment.actual_user_id', backref='actual_user', lazy='dynamic')
    announcements = db.relationship('Announcement', backref='author', lazy='dynamic')
    notifications = db.relationship('Notification', backref='user', lazy='dynamic')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def is_admin(self):
        return self.role == 'admin'

class MassSchedule(db.Model):
    __tablename__ = 'mass_schedules'
    id = db.Column(db.Integer, primary_key=True)
    mass_date = db.Column(db.Date, nullable=False)
    mass_time = db.Column(db.String(20), nullable=False)  # e.g. "06:00 AM"
    mass_type = db.Column(db.String(100), nullable=False)  # Sunday Mass, Weekday, Special, Funeral, etc.
    language = db.Column(db.String(50), default='English')  # English, Pangasinan
    location = db.Column(db.String(100), default='Main Church')
    notes = db.Column(db.Text, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    assignments = db.relationship('Assignment', backref='schedule', lazy='dynamic', cascade='all, delete-orphan')

class Assignment(db.Model):
    __tablename__ = 'assignments'
    id = db.Column(db.Integer, primary_key=True)
    schedule_id = db.Column(db.Integer, db.ForeignKey('mass_schedules.id'), nullable=False)
    role = db.Column(db.String(50), nullable=False)  # Lector 1, Lector 2, Commentator, etc.
    original_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    actual_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)  # who actually served
    status = db.Column(db.String(30), default='pending')  # pending, attended, absent, swapped, substituted
    swap_partner_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    remarks = db.Column(db.Text, nullable=True)
    status_updated_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    status_updated_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Reading(db.Model):
    __tablename__ = 'readings'
    id = db.Column(db.Integer, primary_key=True)
    reading_date = db.Column(db.Date, nullable=False, unique=True)
    liturgical_season = db.Column(db.String(100), nullable=True)
    celebration = db.Column(db.String(200), nullable=True)  # e.g. 32nd Sunday in Ordinary Time
    first_reading = db.Column(db.Text, nullable=True)
    first_reading_citation = db.Column(db.String(100), nullable=True)
    responsorial_psalm = db.Column(db.Text, nullable=True)
    psalm_citation = db.Column(db.String(100), nullable=True)
    second_reading = db.Column(db.Text, nullable=True)
    second_reading_citation = db.Column(db.String(100), nullable=True)
    gospel = db.Column(db.Text, nullable=True)
    gospel_citation = db.Column(db.String(100), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    uploaded_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Announcement(db.Model):
    __tablename__ = 'announcements'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    priority = db.Column(db.String(20), default='normal')  # normal, urgent, important
    author_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    image_path = db.Column(db.String(255), nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=True)

class Guide(db.Model):
    __tablename__ = 'guides'
    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(50), nullable=False)  # pangasinan, english, funeral
    title = db.Column(db.String(200), nullable=False)
    section = db.Column(db.String(100), nullable=True)  # opening, welcome, introductions, etc.
    content = db.Column(db.Text, nullable=True)  # text content
    file_path = db.Column(db.String(255), nullable=True)  # for PDF/docs
    order_index = db.Column(db.Integer, default=0)
    uploaded_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Notification(db.Model):
    __tablename__ = 'notifications'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    type = db.Column(db.String(50), default='info')  # schedule, reading, announcement, swap, etc.
    is_read = db.Column(db.Boolean, default=False)
    link = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class AttendanceArchive(db.Model):
    """Archived attendance records older than 30 days"""
    __tablename__ = 'attendance_archive'
    id = db.Column(db.Integer, primary_key=True)
    original_assignment_id = db.Column(db.Integer)
    mass_date = db.Column(db.Date)
    mass_time = db.Column(db.String(20))
    role = db.Column(db.String(50))
    original_user_name = db.Column(db.String(150))
    actual_user_name = db.Column(db.String(150))
    status = db.Column(db.String(30))
    remarks = db.Column(db.Text)
    status_updated_at = db.Column(db.DateTime)
    archived_at = db.Column(db.DateTime, default=datetime.utcnow)

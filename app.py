import os
from datetime import datetime, date, timedelta
from functools import wraps
from flask import (Flask, render_template, redirect, url_for, flash, request,
                   jsonify, send_from_directory, abort)
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.utils import secure_filename
from models import (db, User, MassSchedule, Assignment, Reading, Announcement,
                    Guide, Notification, AttendanceArchive)

basedir = os.path.abspath(os.path.dirname(__file__))

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'ministry-of-readers-st-john-baptist-2026-secure-key')

# Support both local SQLite and Render PostgreSQL
database_url = os.environ.get('DATABASE_URL')
if database_url:
    # Render uses postgres:// but SQLAlchemy needs postgresql://
    if database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql://', 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
else:
    # Local development
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:////tmp/ministry_readers.db'

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.path.join(basedir, 'static', 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(os.path.join(basedir, 'instance'), exist_ok=True)

db.init_app(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message_category = 'warning'

ALLOWED_EXTENSIONS = {'pdf', 'doc', 'docx', 'txt', 'png', 'jpg', 'jpeg', 'gif'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin():
            flash('Administrator access required.', 'danger')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function

def create_notification(user_id, title, message, ntype='info', link=None):
    notif = Notification(user_id=user_id, title=title, message=message, type=ntype, link=link)
    db.session.add(notif)
    db.session.commit()

def archive_old_attendance():
    """Archive or clean attendance records older than 30 days"""
    cutoff = datetime.utcnow() - timedelta(days=30)
    old_assignments = Assignment.query.filter(
        Assignment.status_updated_at != None,
        Assignment.status_updated_at < cutoff
    ).all()
    for a in old_assignments:
        schedule = a.schedule
        orig_name = a.original_user.full_name if a.original_user else 'Unknown'
        act_name = a.actual_user.full_name if a.actual_user else orig_name
        archive = AttendanceArchive(
            original_assignment_id=a.id,
            mass_date=schedule.mass_date if schedule else None,
            mass_time=schedule.mass_time if schedule else None,
            role=a.role,
            original_user_name=orig_name,
            actual_user_name=act_name,
            status=a.status,
            remarks=a.remarks,
            status_updated_at=a.status_updated_at
        )
        db.session.add(archive)
        # Optionally delete or keep; here we keep but could soft-delete
    db.session.commit()

# ---------- Auth Routes ----------
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password) and user.is_active:
            login_user(user, remember=True)
            flash(f'Welcome back, {user.full_name}!', 'success')
            next_page = request.args.get('next')
            return redirect(next_page or url_for('dashboard'))
        flash('Invalid username or password.', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

# ---------- Main Routes ----------
@app.route('/')
@login_required
def dashboard():
    today = date.today()
    # Upcoming schedules (next 14 days)
    upcoming = MassSchedule.query.filter(
        MassSchedule.mass_date >= today
    ).order_by(MassSchedule.mass_date, MassSchedule.mass_time).limit(10).all()

    # Latest announcements
    announcements = Announcement.query.filter_by(is_active=True).order_by(
        Announcement.priority.desc(), Announcement.created_at.desc()
    ).limit(5).all()

    # Recent readings
    readings = Reading.query.order_by(Reading.reading_date.desc()).limit(5).all()

    # User's upcoming assignments
    my_assignments = Assignment.query.join(MassSchedule).filter(
        Assignment.original_user_id == current_user.id,
        MassSchedule.mass_date >= today
    ).order_by(MassSchedule.mass_date).limit(5).all()

    # Unread notifications
    notifications = Notification.query.filter_by(
        user_id=current_user.id, is_read=False
    ).order_by(Notification.created_at.desc()).limit(8).all()

    # Admin stats
    stats = {}
    if current_user.is_admin():
        stats['total_members'] = User.query.filter_by(role='member', is_active=True).count()
        stats['pending_attendance'] = Assignment.query.filter_by(status='pending').count()
        stats['upcoming_masses'] = MassSchedule.query.filter(MassSchedule.mass_date >= today).count()
        stats['recent_announcements'] = Announcement.query.filter(
            Announcement.created_at >= datetime.utcnow() - timedelta(days=7)
        ).count()

    return render_template('dashboard.html',
                           upcoming=upcoming,
                           announcements=announcements,
                           readings=readings,
                           my_assignments=my_assignments,
                           notifications=notifications,
                           stats=stats,
                           today=today)

@app.route('/schedules')
@login_required
def schedules():
    view = request.args.get('view', 'list')  # list, week, month
    month = request.args.get('month', type=int) or date.today().month
    year = request.args.get('year', type=int) or date.today().year

    query = MassSchedule.query.order_by(MassSchedule.mass_date, MassSchedule.mass_time)

    if view == 'month':
        start = date(year, month, 1)
        if month == 12:
            end = date(year + 1, 1, 1)
        else:
            end = date(year, month + 1, 1)
        schedules_list = query.filter(
            MassSchedule.mass_date >= start,
            MassSchedule.mass_date < end
        ).all()
    else:
        # Default: upcoming list
        schedules_list = query.filter(MassSchedule.mass_date >= date.today()).limit(30).all()

    return render_template('schedules.html',
                           schedules=schedules_list,
                           view=view,
                           month=month,
                           year=year,
                           today=date.today())

@app.route('/schedules/<int:id>')
@login_required
def schedule_detail(id):
    schedule = MassSchedule.query.get_or_404(id)
    assignments = Assignment.query.filter_by(schedule_id=id).all()
    members = User.query.filter_by(is_active=True).order_by(User.full_name).all()
    return render_template('schedule_detail.html', schedule=schedule, assignments=assignments, members=members)

@app.route('/my-assignments')
@login_required
def my_assignments():
    assignments = Assignment.query.join(MassSchedule).filter(
        (Assignment.original_user_id == current_user.id) |
        (Assignment.actual_user_id == current_user.id)
    ).order_by(MassSchedule.mass_date.desc()).all()
    return render_template('my_assignments.html', assignments=assignments)

# ---------- Admin Schedule Management ----------
@app.route('/admin/schedules/new', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_new_schedule():
    if request.method == 'POST':
        try:
            mass_date = datetime.strptime(request.form['mass_date'], '%Y-%m-%d').date()
            schedule = MassSchedule(
                mass_date=mass_date,
                mass_time=request.form['mass_time'],
                mass_type=request.form['mass_type'],
                language=request.form.get('language', 'English'),
                location=request.form.get('location', 'Main Church'),
                notes=request.form.get('notes'),
                created_by=current_user.id
            )
            db.session.add(schedule)
            db.session.flush()

            # Create assignments from form
            roles = request.form.getlist('role[]')
            user_ids = request.form.getlist('user_id[]')
            for role, uid in zip(roles, user_ids):
                if role and uid:
                    assignment = Assignment(
                        schedule_id=schedule.id,
                        role=role,
                        original_user_id=int(uid),
                        status='pending'
                    )
                    db.session.add(assignment)
                    # Notify the assigned member
                    create_notification(
                        int(uid),
                        'New Schedule Assignment',
                        f'You have been assigned as {role} for {schedule.mass_type} on {mass_date.strftime("%B %d, %Y")} at {schedule.mass_time}.',
                        'schedule',
                        url_for('schedule_detail', id=schedule.id)
                    )

            db.session.commit()
            flash('Schedule created successfully.', 'success')
            return redirect(url_for('schedules'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error creating schedule: {str(e)}', 'danger')

    members = User.query.filter_by(is_active=True).order_by(User.full_name).all()
    return render_template('admin/new_schedule.html', members=members)

@app.route('/admin/schedules/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_edit_schedule(id):
    schedule = MassSchedule.query.get_or_404(id)
    if request.method == 'POST':
        try:
            schedule.mass_date = datetime.strptime(request.form['mass_date'], '%Y-%m-%d').date()
            schedule.mass_time = request.form['mass_time']
            schedule.mass_type = request.form['mass_type']
            schedule.language = request.form.get('language', 'English')
            schedule.location = request.form.get('location', 'Main Church')
            schedule.notes = request.form.get('notes')
            schedule.updated_at = datetime.utcnow()
            db.session.commit()
            flash('Schedule updated.', 'success')
            return redirect(url_for('schedule_detail', id=id))
        except Exception as e:
            db.session.rollback()
            flash(f'Error: {str(e)}', 'danger')
    members = User.query.filter_by(is_active=True).order_by(User.full_name).all()
    assignments = Assignment.query.filter_by(schedule_id=id).all()
    return render_template('admin/edit_schedule.html', schedule=schedule, members=members, assignments=assignments)

@app.route('/admin/assignments/<int:id>/update-status', methods=['POST'])
@login_required
@admin_required
def update_assignment_status(id):
    assignment = Assignment.query.get_or_404(id)
    new_status = request.form.get('status')
    actual_user_id = request.form.get('actual_user_id')
    remarks = request.form.get('remarks', '')
    swap_partner = request.form.get('swap_partner_id')

    valid_statuses = ['pending', 'attended', 'absent', 'swapped', 'substituted']
    if new_status not in valid_statuses:
        flash('Invalid status.', 'danger')
        return redirect(request.referrer or url_for('schedules'))

    assignment.status = new_status
    assignment.remarks = remarks
    assignment.status_updated_by = current_user.id
    assignment.status_updated_at = datetime.utcnow()

    if new_status in ['substituted', 'swapped'] and actual_user_id:
        assignment.actual_user_id = int(actual_user_id)
        if new_status == 'swapped' and swap_partner:
            assignment.swap_partner_id = int(swap_partner)

    # Notify original and actual if different
    if assignment.original_user_id:
        create_notification(
            assignment.original_user_id,
            f'Schedule Status Updated: {new_status.title()}',
            f'Your assignment as {assignment.role} on {assignment.schedule.mass_date} has been marked as {new_status}. {remarks}',
            'attendance'
        )
    if assignment.actual_user_id and assignment.actual_user_id != assignment.original_user_id:
        create_notification(
            assignment.actual_user_id,
            f'You served as substitute/swap',
            f'You served as {assignment.role} on {assignment.schedule.mass_date} (original: {assignment.original_user.full_name}).',
            'attendance'
        )

    db.session.commit()
    flash('Attendance status updated.', 'success')
    return redirect(request.referrer or url_for('schedule_detail', id=assignment.schedule_id))

@app.route('/admin/schedules/<int:id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_schedule(id):
    schedule = MassSchedule.query.get_or_404(id)
    db.session.delete(schedule)
    db.session.commit()
    flash('Schedule deleted.', 'success')
    return redirect(url_for('schedules'))

# ---------- Readings ----------
@app.route('/readings')
@login_required
def readings():
    search_date = request.args.get('date')
    if search_date:
        try:
            d = datetime.strptime(search_date, '%Y-%m-%d').date()
            readings_list = Reading.query.filter_by(reading_date=d).all()
        except ValueError:
            readings_list = []
            flash('Invalid date format.', 'warning')
    else:
        readings_list = Reading.query.order_by(Reading.reading_date.desc()).limit(30).all()
    return render_template('readings.html', readings=readings_list, search_date=search_date)

@app.route('/readings/<int:id>')
@login_required
def reading_detail(id):
    reading = Reading.query.get_or_404(id)
    return render_template('reading_detail.html', reading=reading)

@app.route('/admin/readings/new', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_new_reading():
    if request.method == 'POST':
        try:
            rdate = datetime.strptime(request.form['reading_date'], '%Y-%m-%d').date()
            # Check unique
            if Reading.query.filter_by(reading_date=rdate).first():
                flash('A reading for this date already exists. Edit it instead.', 'warning')
                return redirect(url_for('readings'))

            reading = Reading(
                reading_date=rdate,
                liturgical_season=request.form.get('liturgical_season'),
                celebration=request.form.get('celebration'),
                first_reading=request.form.get('first_reading'),
                first_reading_citation=request.form.get('first_reading_citation'),
                responsorial_psalm=request.form.get('responsorial_psalm'),
                psalm_citation=request.form.get('psalm_citation'),
                second_reading=request.form.get('second_reading'),
                second_reading_citation=request.form.get('second_reading_citation'),
                gospel=request.form.get('gospel'),
                gospel_citation=request.form.get('gospel_citation'),
                notes=request.form.get('notes'),
                uploaded_by=current_user.id
            )
            db.session.add(reading)
            db.session.commit()

            # Notify all members
            for member in User.query.filter_by(is_active=True).all():
                create_notification(
                    member.id,
                    'New Reading Uploaded',
                    f'Readings for {rdate.strftime("%B %d, %Y")} ({reading.celebration or "Liturgical Day"}) are now available.',
                    'reading',
                    url_for('reading_detail', id=reading.id)
                )

            flash('Reading uploaded successfully.', 'success')
            return redirect(url_for('readings'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error: {str(e)}', 'danger')
    return render_template('admin/new_reading.html')

@app.route('/admin/readings/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_edit_reading(id):
    reading = Reading.query.get_or_404(id)
    if request.method == 'POST':
        reading.liturgical_season = request.form.get('liturgical_season')
        reading.celebration = request.form.get('celebration')
        reading.first_reading = request.form.get('first_reading')
        reading.first_reading_citation = request.form.get('first_reading_citation')
        reading.responsorial_psalm = request.form.get('responsorial_psalm')
        reading.psalm_citation = request.form.get('psalm_citation')
        reading.second_reading = request.form.get('second_reading')
        reading.second_reading_citation = request.form.get('second_reading_citation')
        reading.gospel = request.form.get('gospel')
        reading.gospel_citation = request.form.get('gospel_citation')
        reading.notes = request.form.get('notes')
        reading.updated_at = datetime.utcnow()
        db.session.commit()
        flash('Reading updated.', 'success')
        return redirect(url_for('reading_detail', id=id))
    return render_template('admin/edit_reading.html', reading=reading)

# ---------- Announcements ----------
@app.route('/announcements')
@login_required
def announcements():
    anns = Announcement.query.filter_by(is_active=True).order_by(
        Announcement.priority.desc(), Announcement.created_at.desc()
    ).all()
    return render_template('announcements.html', announcements=anns)

@app.route('/admin/announcements/new', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_new_announcement():
    if request.method == 'POST':
        title = request.form.get('title')
        content = request.form.get('content')
        priority = request.form.get('priority', 'normal')
        image_path = None
        if 'image' in request.files:
            file = request.files['image']
            if file and file.filename and allowed_file(file.filename):
                filename = secure_filename(f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{file.filename}")
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                image_path = f'uploads/{filename}'

        ann = Announcement(
            title=title,
            content=content,
            priority=priority,
            author_id=current_user.id,
            image_path=image_path
        )
        db.session.add(ann)
        db.session.commit()

        for member in User.query.filter_by(is_active=True).all():
            create_notification(
                member.id,
                f'New Announcement: {title}',
                content[:150] + ('...' if len(content) > 150 else ''),
                'announcement',
                url_for('announcements')
            )

        flash('Announcement published.', 'success')
        return redirect(url_for('announcements'))
    return render_template('admin/new_announcement.html')

@app.route('/admin/announcements/<int:id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_announcement(id):
    ann = Announcement.query.get_or_404(id)
    ann.is_active = False
    db.session.commit()
    flash('Announcement archived.', 'success')
    return redirect(url_for('announcements'))

# ---------- Guides ----------
@app.route('/guides')
@login_required
def guides():
    category = request.args.get('category', 'english')
    guides_list = Guide.query.filter_by(category=category).order_by(Guide.order_index, Guide.title).all()
    return render_template('guides.html', guides=guides_list, category=category)

@app.route('/guides/<int:id>')
@login_required
def guide_detail(id):
    guide = Guide.query.get_or_404(id)
    return render_template('guide_detail.html', guide=guide)

@app.route('/admin/guides/new', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_new_guide():
    if request.method == 'POST':
        category = request.form.get('category')
        title = request.form.get('title')
        section = request.form.get('section')
        content = request.form.get('content')
        order_index = int(request.form.get('order_index', 0))
        file_path = None
        if 'file' in request.files:
            file = request.files['file']
            if file and file.filename and allowed_file(file.filename):
                filename = secure_filename(f"{category}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{file.filename}")
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                file_path = f'uploads/{filename}'

        guide = Guide(
            category=category,
            title=title,
            section=section,
            content=content,
            file_path=file_path,
            order_index=order_index,
            uploaded_by=current_user.id
        )
        db.session.add(guide)
        db.session.commit()
        flash('Guide uploaded.', 'success')
        return redirect(url_for('guides', category=category))
    return render_template('admin/new_guide.html')

@app.route('/funeral')
@login_required
def funeral_guides():
    guides_list = Guide.query.filter_by(category='funeral').order_by(Guide.order_index).all()
    return render_template('funeral.html', guides=guides_list)

# ---------- Attendance History ----------
@app.route('/attendance')
@login_required
def attendance_history():
    if current_user.is_admin():
        # Full history for admin, last 30 days primarily
        cutoff = date.today() - timedelta(days=30)
        assignments = Assignment.query.join(MassSchedule).filter(
            MassSchedule.mass_date >= cutoff
        ).order_by(MassSchedule.mass_date.desc()).all()
        # Summary stats
        total = len(assignments)
        attended = sum(1 for a in assignments if a.status == 'attended')
        absent = sum(1 for a in assignments if a.status == 'absent')
        substituted = sum(1 for a in assignments if a.status == 'substituted')
        swapped = sum(1 for a in assignments if a.status == 'swapped')
        pending = sum(1 for a in assignments if a.status == 'pending')
        stats = {
            'total': total, 'attended': attended, 'absent': absent,
            'substituted': substituted, 'swapped': swapped, 'pending': pending
        }
    else:
        assignments = Assignment.query.join(MassSchedule).filter(
            (Assignment.original_user_id == current_user.id) |
            (Assignment.actual_user_id == current_user.id)
        ).order_by(MassSchedule.mass_date.desc()).limit(50).all()
        stats = None

    return render_template('attendance.html', assignments=assignments, stats=stats)

# ---------- Notifications ----------
@app.route('/notifications')
@login_required
def notifications():
    notifs = Notification.query.filter_by(user_id=current_user.id).order_by(
        Notification.created_at.desc()
    ).limit(50).all()
    # Mark all as read
    for n in notifs:
        if not n.is_read:
            n.is_read = True
    db.session.commit()
    return render_template('notifications.html', notifications=notifs)

@app.route('/notifications/mark-read/<int:id>', methods=['POST'])
@login_required
def mark_notification_read(id):
    notif = Notification.query.get_or_404(id)
    if notif.user_id == current_user.id:
        notif.is_read = True
        db.session.commit()
    return jsonify({'ok': True})

# ---------- Admin Members ----------
@app.route('/admin/members')
@login_required
@admin_required
def admin_members():
    members = User.query.order_by(User.full_name).all()
    return render_template('admin/members.html', members=members)

@app.route('/admin/members/new', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_new_member():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        full_name = request.form.get('full_name', '').strip()
        password = request.form.get('password', '')
        role = request.form.get('role', 'member')
        if User.query.filter((User.username == username) | (User.email == email)).first():
            flash('Username or email already exists.', 'danger')
        else:
            user = User(username=username, email=email, full_name=full_name, role=role)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            flash(f'Member {full_name} created.', 'success')
            return redirect(url_for('admin_members'))
    return render_template('admin/new_member.html')

@app.route('/admin/dashboard')
@login_required
@admin_required
def admin_dashboard():
    today = date.today()
    total_members = User.query.filter_by(is_active=True).count()
    upcoming = MassSchedule.query.filter(MassSchedule.mass_date >= today).count()
    pending = Assignment.query.filter_by(status='pending').count()
    recent_mods = Assignment.query.filter(
        Assignment.status_updated_at != None
    ).order_by(Assignment.status_updated_at.desc()).limit(10).all()
    latest_readings = Reading.query.order_by(Reading.created_at.desc()).limit(5).all()
    latest_anns = Announcement.query.order_by(Announcement.created_at.desc()).limit(5).all()

    # Attendance summary last 30 days
    cutoff = today - timedelta(days=30)
    recent_assign = Assignment.query.join(MassSchedule).filter(MassSchedule.mass_date >= cutoff).all()
    summary = {
        'total': len(recent_assign),
        'attended': sum(1 for a in recent_assign if a.status == 'attended'),
        'absent': sum(1 for a in recent_assign if a.status == 'absent'),
        'substituted': sum(1 for a in recent_assign if a.status == 'substituted'),
        'swapped': sum(1 for a in recent_assign if a.status == 'swapped'),
        'pending': sum(1 for a in recent_assign if a.status == 'pending'),
    }

    return render_template('admin/dashboard.html',
                           total_members=total_members,
                           upcoming=upcoming,
                           pending=pending,
                           recent_mods=recent_mods,
                           latest_readings=latest_readings,
                           latest_anns=latest_anns,
                           summary=summary)

# ---------- Init DB & Sample Data ----------
def init_db():
    with app.app_context():
        db.create_all()
        if User.query.count() == 0:
            # Create admin
            admin = User(
                username='admin',
                email='admin@stjohnbaptist.ph',
                full_name='Ministry President',
                role='admin'
            )
            admin.set_password('admin123')
            db.session.add(admin)

            # Sample members
            members_data = [
                ('maria.santos', 'maria.santos@email.com', 'Maria Santos'),
                ('juan.delacruz', 'juan.delacruz@email.com', 'Juan Dela Cruz'),
                ('ana.reyes', 'ana.reyes@email.com', 'Ana Reyes'),
                ('pedro.garcia', 'pedro.garcia@email.com', 'Pedro Garcia'),
                ('luisa.ramos', 'luisa.ramos@email.com', 'Luisa Ramos'),
                ('carlos.mendoza', 'carlos.mendoza@email.com', 'Carlos Mendoza'),
            ]
            members = []
            for u, e, n in members_data:
                m = User(username=u, email=e, full_name=n, role='member')
                m.set_password('reader123')
                db.session.add(m)
                members.append(m)

            db.session.commit()

            # Sample schedules
            today = date.today()
            sample_schedules = [
                (today + timedelta(days=2), '06:00 AM', 'Sunday Mass', 'Pangasinan'),
                (today + timedelta(days=2), '08:00 AM', 'Sunday Mass', 'English'),
                (today + timedelta(days=2), '05:00 PM', 'Sunday Mass', 'English'),
                (today + timedelta(days=5), '06:00 AM', 'Weekday Mass', 'Pangasinan'),
                (today + timedelta(days=9), '06:00 AM', 'Sunday Mass', 'Pangasinan'),
                (today + timedelta(days=9), '08:00 AM', 'Sunday Mass', 'English'),
            ]
            for d, t, mt, lang in sample_schedules:
                s = MassSchedule(
                    mass_date=d, mass_time=t, mass_type=mt, language=lang,
                    created_by=admin.id
                )
                db.session.add(s)
                db.session.flush()
                # Assign some members
                if members:
                    a1 = Assignment(schedule_id=s.id, role='Commentator',
                                    original_user_id=members[0].id, status='pending')
                    a2 = Assignment(schedule_id=s.id, role='First Reader',
                                    original_user_id=members[1].id, status='pending')
                    a3 = Assignment(schedule_id=s.id, role='Second Reader',
                                    original_user_id=members[2].id, status='pending')
                    db.session.add_all([a1, a2, a3])

            # Sample reading
            r = Reading(
                reading_date=today + timedelta(days=2),
                liturgical_season='Ordinary Time',
                celebration='33rd Sunday in Ordinary Time',
                first_reading_citation='Malachi 3:19-20a',
                first_reading='Lo, the day is coming, blazing like an oven, when all the proud and all evildoers will be stubble...',
                psalm_citation='Psalm 98:5-6, 7-8, 9',
                responsorial_psalm='The Lord comes to rule the earth with justice.',
                second_reading_citation='2 Thessalonians 3:7-12',
                second_reading='Brothers and sisters: You know how one must imitate us...',
                gospel_citation='Luke 21:5-19',
                gospel='While some people were speaking about how the temple was adorned with costly stones and votive offerings...',
                notes='Please proclaim clearly and pause after each reading.',
                uploaded_by=admin.id
            )
            db.session.add(r)

            # Sample announcements
            a1 = Announcement(
                title='Welcome to the Ministry of Readers Portal',
                content='Dear brothers and sisters in the Ministry of Readers, welcome to our new digital platform. Here you can view schedules, access readings, and stay updated with ministry announcements. Please update your contact information if needed. God bless!',
                priority='important',
                author_id=admin.id
            )
            a2 = Announcement(
                title='Schedule for the Coming Sundays',
                content='Please check the Schedules section for your upcoming assignments. If you need to request a swap, contact the ministry officers at least 3 days in advance.',
                priority='normal',
                author_id=admin.id
            )
            db.session.add_all([a1, a2])

            # Sample guides
            guides_data = [
                ('english', 'Opening Remarks', 'opening', 'Good morning / Good afternoon, brothers and sisters. Welcome to the celebration of the Holy Eucharist...', 1),
                ('english', 'Introduction to the Readings', 'readings', 'Let us now listen to the Word of God. The First Reading is taken from...', 2),
                ('english', 'Prayer of the Faithful - Sample', 'petitions', 'Let us now offer our prayers to the Lord...\n1. For the Church...\nResponse: Lord, hear our prayer.', 3),
                ('pangasinan', 'Opening Remarks (Pangasinan)', 'opening', 'Maong ya agew / Maong ya ngarem, kakaibegasan. Welcome ed sayan Misa...', 1),
                ('pangasinan', 'Introduction to Readings', 'readings', 'Dinggen tayo so Basaen na Dios. Say Unan Basaen nanlapud...', 2),
                ('funeral', 'Opening Welcome', 'opening', 'On behalf of the family of the deceased, we welcome you to this Funeral Mass...', 1),
                ('funeral', 'Prayer of the Faithful', 'petitions', 'For our brother/sister who has gone before us marked with the sign of faith...', 2),
            ]
            for cat, title, sec, cont, ord_ in guides_data:
                g = Guide(category=cat, title=title, section=sec, content=cont,
                          order_index=ord_, uploaded_by=admin.id)
                db.session.add(g)

            db.session.commit()
            print('Database initialized with sample data.')
            print('Admin login: username=admin  password=admin123')
            print('Member login example: username=maria.santos  password=reader123')

if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=5000, debug=True)

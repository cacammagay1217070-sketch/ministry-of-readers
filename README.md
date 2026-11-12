# Ministry of Readers – St. John the Baptist Parish Church

Official digital platform for the Ministry of Readers (lectors & commentators).

## Features

- **Secure login** with role-based access (Administrator / Member)
- **Dashboard** with upcoming assignments, announcements, readings, and notifications
- **Schedules**: List & monthly views, detailed assignments with original vs actual server tracking
- **Attendance statuses**: Pending, Attended, Absent, Swapped, Substituted (original assignment preserved)
- **Daily Readings**: Upload, view, search by date (admin-controlled, no auto-generated Scripture)
- **Announcements** with priority levels
- **Commentators' Guides**: English Mass, Pangasinan Mass, and dedicated Funeral Mass section
- **Attendance history** (30-day focus) with admin summary statistics
- **In-app notifications** for schedule changes, new readings, announcements
- **Admin panel** for managing members, schedules, readings, guides, and attendance
- Fully responsive design with Catholic-inspired elegant palette (burgundy, gold, cream)

## Quick Start

```bash
cd ministry_readers
python3 app.py
```

Then open http://127.0.0.1:5000

### Demo Accounts

| Role   | Username       | Password   |
|--------|----------------|------------|
| Admin  | admin          | admin123   |
| Member | maria.santos   | reader123  |
| Member | juan.delacruz  | reader123  |

## Tech Stack

- Python 3 + Flask
- SQLAlchemy + SQLite (persistent)
- Flask-Login for authentication
- Tailwind CSS (CDN) + custom elegant typography
- File uploads for guides and announcement images

## Notes

- Sample data is pre-loaded for demonstration. Administrators should replace it with official parish content.
- Database file: `/tmp/ministry_readers.db` (or configure in `app.py`)
- The system distinguishes original assignees from those who actually served (swaps/substitutions).
- Attendance records older than 30 days can be archived via the built-in archive helper.

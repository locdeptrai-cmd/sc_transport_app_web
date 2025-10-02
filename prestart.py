# prestart.py
import os
from app import app, db

IMPORT_EXCEL = os.getenv("IMPORT_EXCEL_PATH")  # ví dụ: data/DS sale, drivers, cars.xlsx

def ensure_admin():
    from models import User
    admin = User.query.filter_by(email="admin@sc.local").first()
    if not admin:
        admin = User(email="admin@sc.local", role="admin", active=True)
        admin.set_password("Admin@123")
        db.session.add(admin)
        db.session.commit()
        print("Seeded admin@sc.local / Admin@123")

def maybe_import_excel():
    if not IMPORT_EXCEL:
        print("No IMPORT_EXCEL_PATH; skip Excel import.")
        return
    if not os.path.exists(IMPORT_EXCEL):
        print(f"Excel path '{IMPORT_EXCEL}' not found; skip.")
        return
    try:
        import import_named_users
        import sys
        sys.argv = ["import_named_users.py", IMPORT_EXCEL]
        import_named_users.main()
    except Exception as e:
        print("Excel import failed:", e)

with app.app_context():
    db.create_all()
    print("DB tables ensured.")
    ensure_admin()
    maybe_import_excel()

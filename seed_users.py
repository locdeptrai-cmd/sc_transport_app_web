# seed_users.py - tạo admin + sale01..sale20
from app import app
from models import db, User

# Thử dùng passlib bcrypt (nếu có), fallback sang werkzeug
try:
    from passlib.hash import bcrypt
except Exception:
    bcrypt = None

try:
    from werkzeug.security import generate_password_hash
except Exception:
    generate_password_hash = None


def set_password_smart(user, plain: str):
    """Đặt password theo cách tương thích với dự án."""
    # 1) Nếu model có sẵn set_password(...) thì dùng luôn (chuẩn nhất)
    if hasattr(user, "set_password") and callable(user.set_password):
        user.set_password(plain)
        return

    # 2) Nếu có check_password(...) thì thử bcrypt trước
    has_checker = hasattr(user, "check_password") and callable(user.check_password)

    if bcrypt is not None:
        user.password = bcrypt.hash(plain)
        if not has_checker:
            return
        try:
            if user.check_password(plain):
                return
        except Exception:
            pass  # thử phương án khác

    # 3) Fallback: PBKDF2 của werkzeug
    if generate_password_hash is not None:
        user.password = generate_password_hash(plain)
        # nếu có checker mà checker dùng bcrypt thì có thể verify fail, nhưng vẫn lưu hash an toàn
        return

    # 4) Không có gì để hash -> báo lỗi rõ ràng
    raise RuntimeError("Thiếu passlib[bcrypt] hoặc werkzeug.security để tạo hash.")


with app.app_context():
    db.create_all()

    # --- Admin ---
    admin_email = "admin@sc.local"
    admin = User.query.filter_by(email=admin_email).first()
    if not admin:
        admin = User(email=admin_email, role="admin", active=True)
    else:
        if hasattr(admin, "active"):
            admin.active = True
        if hasattr(admin, "role"):
            admin.role = "admin"
    set_password_smart(admin, "Admin@123")
    db.session.add(admin)

    # --- Sales: sale01..sale20 ---
    for i in range(1, 21):
        email = f"sale{i:02d}@sc.local"
        u = User.query.filter_by(email=email).first()
        if not u:
            u = User(email=email, role="sales", active=True)
            if hasattr(u, "username"):
                u.username = f"sale{i:02d}"
            if hasattr(u, "commission_rate") and not getattr(u, "commission_rate", None):
                u.commission_rate = 0.05
        else:
            if hasattr(u, "active"):
                u.active = True
            if hasattr(u, "role"):
                u.role = "sales"

        set_password_smart(u, "Sale@123")
        db.session.add(u)

    db.session.commit()
    print("✅ Seed thành công: admin + sale01..sale20")

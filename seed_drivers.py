# seed_drivers.py - tạo 5 driver + 5 car và map quan hệ
from app import app
from models import db, User, Driver, Car

# Hash mật khẩu: ưu tiên passlib bcrypt, fallback về werkzeug
try:
    from passlib.hash import bcrypt
except Exception:
    bcrypt = None
try:
    from werkzeug.security import generate_password_hash
except Exception:
    generate_password_hash = None

def set_password_smart(user, plain: str):
    # Nếu model đã có sẵn set_password() -> dùng chính hàm đó
    if hasattr(user, "set_password") and callable(user.set_password):
        user.set_password(plain)
        return
    # Thử bcrypt trước
    if bcrypt is not None:
        user.password = bcrypt.hash(plain)
        return
    # Fallback PBKDF2 của werkzeug
    if generate_password_hash is not None:
        user.password = generate_password_hash(plain)
        return
    raise RuntimeError("Thiếu passlib[bcrypt] hoặc werkzeug.security để hash mật khẩu")

def set_if_has(obj, field, value):
    if hasattr(obj, field):
        setattr(obj, field, value)

# Tên cột biển số có thể khác nhau giữa dự án (license_plate/plate/plate_number/plate_no/registration)
CAR_PLATE_FIELDS = ("license_plate", "plate", "plate_number", "plate_no", "registration")
# Tên cột hiển thị xe (brand/model/name)
CAR_NAME_FIELDS  = ("name", "model", "brand")

# Tên cột thông tin driver có thể khác nhau
DRIVER_NAME_FIELDS  = ("name", "full_name")
DRIVER_PHONE_FIELDS = ("phone", "phone_number")

with app.app_context():
    db.create_all()

    def ensure_car(idx:int):
        # tạo biển số dạng 51A-0000X
        plate_value = f"51A-0000{idx}"
        car = None

        # Thử tìm xe đã có theo các cột biển số
        for f in CAR_PLATE_FIELDS:
            if hasattr(Car, f):
                car = db.session.query(Car).filter(getattr(Car, f) == plate_value).first()
                if car:
                    break

        if not car:
            car = Car()
            # đặt biển số vào cột đầu tiên tìm thấy
            for f in CAR_PLATE_FIELDS:
                if hasattr(car, f):
                    setattr(car, f, plate_value)
                    break
            # đặt tên/nhãn nếu có cột phù hợp
            for f in CAR_NAME_FIELDS:
                if hasattr(car, f):
                    setattr(car, f, f"Sedan #{idx}")
                    break
            db.session.add(car)
            db.session.flush()  # có id

        return car

    def ensure_driver_user(idx:int):
        email = f"driver_{idx:02d}@sc.local"
        user = User.query.filter_by(email=email).first()
        if not user:
            user = User(email=email)
        # đảm bảo role/active/username nếu có
        set_if_has(user, "role", "driver")
        set_if_has(user, "active", True)
        set_if_has(user, "username", f"driver_{idx:02d}")
        set_password_smart(user, "Driver@123")
        db.session.add(user)
        db.session.flush()  # có id
        return user

    def ensure_driver_profile(user, car):
        # tìm bản ghi Driver theo user_id
        drv = Driver.query.filter_by(user_id=user.id).first()
        if not drv:
            drv = Driver(user_id=user.id)
        # gán car_id nếu có cột
        if hasattr(drv, "car_id"):
            drv.car_id = car.id
        # đặt name/phone nếu mô hình có
        for f in DRIVER_NAME_FIELDS:
            if hasattr(drv, f) and not getattr(drv, f, None):
                setattr(drv, f, f"Tài xế {user.email.split('@')[0]}")
                break
        for f in DRIVER_PHONE_FIELDS:
            if hasattr(drv, f) and not getattr(drv, f, None):
                setattr(drv, f, f"09{idx:02d}123456")
                break
        db.session.add(drv)
        return drv

    # Tạo 5 driver + 5 car
    for idx in range(1, 6):
        car  = ensure_car(idx)
        user = ensure_driver_user(idx)
        drv  = ensure_driver_profile(user, car)

    db.session.commit()
    print("✅ Seed xong: driver_01..driver_05@sc.local / mật khẩu Driver@123 (đã map với Car)")

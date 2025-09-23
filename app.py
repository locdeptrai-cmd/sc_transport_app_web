# app.py (FULL: dashboard + claims + reports + admin users)
from flask import Flask, render_template, redirect, url_for, request, flash, send_file
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from datetime import datetime, date, time, timedelta
import os, csv, io, secrets, unicodedata, re

from models import db, User, Trip, Car, Driver, Cost, Payment, Settings, Maintenance

app = Flask(__name__)
from flask_wtf import CSRFProtect

# ==== CONFIG ====
app.config.update(
    SECRET_KEY=os.getenv("FLASK_SECRET_KEY", "change-me-now"),
    SQLALCHEMY_DATABASE_URI=os.getenv("DATABASE_URL", "sqlite:///sc.db"),
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    WTF_CSRF_ENABLED=True,
)
csrf = CSRFProtect(app)
db.init_app(app)

# ==== LOGIN ====
login_manager = LoginManager(app)
login_manager.login_view = "login"

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

# ==== TIME HELPERS (LOCAL) ====
def now_local():
    return datetime.now()

def day_bounds(d: date):
    start = datetime.combine(d, time.min)
    end = start + timedelta(days=1)
    return start, end

def month_bounds(d: date):
    start = d.replace(day=1)
    if start.month == 12:
        end = start.replace(year=start.year+1, month=1)
    else:
        end = start.replace(month=start.month+1)
    return datetime.combine(start, time.min), datetime.combine(end, time.min)

# ==== STRING HELPERS ====
def slugify_name(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^a-zA-Z0-9]+", "", s)  # bỏ khoảng trắng/ký tự lạ
    return s.lower()[:32] or "user"

def set_attr_if_has(obj, field, value):
    if hasattr(obj, field):
        setattr(obj, field, value)

# prefer passlib bcrypt, fallback werkzeug
def set_password_smart(user, plain: str):
    if hasattr(user, "set_password") and callable(user.set_password):
        user.set_password(plain)
        return
    try:
        from passlib.hash import bcrypt
        user.password = bcrypt.hash(plain)
        return
    except Exception:
        pass
    try:
        from werkzeug.security import generate_password_hash
        user.password = generate_password_hash(plain)
        return
    except Exception:
        pass
    raise RuntimeError("No password hasher available")

def compute_ordinal_for_role(role: str, join_dt: date | None) -> int:
    # nếu model có cột join_date thì xếp theo ngày vào cty; nếu không thì đếm số lượng hiện có
    if hasattr(User, "join_date") and join_dt:
        q = db.session.query(User).filter(User.role == role)
        try:
            q = q.filter(User.join_date <= join_dt)
            return q.count() + 1  # vị trí *sau* tất cả người vào cùng/ngày trước
        except Exception:
            pass
    return db.session.query(User).filter(User.role == role).count() + 1

def generate_credentials(full_name: str, role: str, join_dt: date | None):
    base = slugify_name(full_name or role)
    ordinal = compute_ordinal_for_role(role, join_dt)
    staff_code = f"{base}{ordinal:02d}"

    domain = os.getenv("ORG_EMAIL_DOMAIN", "sc.local")
    email_candidate = f"{staff_code}@{domain}"

    # đảm bảo email duy nhất
    idx = 1
    while db.session.query(User).filter_by(email=email_candidate).first():
        email_candidate = f"{staff_code}{idx}@{domain}"
        idx += 1

    prefix = "Sale" if role == "sales" else "Driver" if role == "driver" else "User"
    password = f"{prefix}@{secrets.randbelow(9000)+1000}"
    return staff_code, email_candidate, password

# ======================= COMMON / AUTH =======================
@app.route("/")
def index():
    if current_user.is_authenticated:
        if current_user.role == "driver":
            return redirect(url_for("driver_dashboard"))
        elif current_user.role == "sales":
            return redirect(url_for("sales_dashboard"))
        else:
            return redirect(url_for("admin_dashboard"))
    return redirect(url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        user = User.query.filter_by(email=email).first()
        if user and getattr(user, "active", True) and user.check_password(password):
            login_user(user)
            return redirect(url_for("index"))
        flash("Sai tài khoản/mật khẩu hoặc tài khoản bị khóa.", "danger")
    return render_template("login.html")

@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))

# ============================ SALES ============================
@app.route("/sales")
@login_required
def sales_dashboard():
    if current_user.role != "sales":
        return redirect(url_for("index"))

    today = date.today()
    day_start, day_end = day_bounds(today)
    mon_start, mon_end = month_bounds(today)

    trips_daily = Trip.query.filter(
        Trip.sales_id == current_user.id,
        Trip.ended_at >= day_start, Trip.ended_at < day_end
    ).all()
    trips_month = Trip.query.filter(
        Trip.sales_id == current_user.id,
        Trip.ended_at >= mon_start, Trip.ended_at < mon_end
    ).all()

    pending_trips = Trip.query.filter(
        Trip.sales_id == current_user.id,
        Trip.status.in_(["booked", "assigned"]),
        Trip.driver_id.is_(None)
    ).order_by(Trip.id.desc()).all()

    daily_rev = sum((t.final_fare or 0) for t in trips_daily)
    month_rev = sum((t.final_fare or 0) for t in trips_month)
    rate = current_user.commission_rate or 0.05

    return render_template(
        "sales_dashboard.html",
        trips_daily=trips_daily, trips_month=trips_month,
        pending_trips=pending_trips,
        daily_rev=daily_rev, month_rev=month_rev,
        commission_rate=rate,
        est_commission_daily=daily_rev * rate,
        est_commission_month=month_rev * rate
    )

@app.route("/sales/trip/new", methods=["POST"])
@login_required
def sales_trip_new():
    if current_user.role != "sales":
        return redirect(url_for("index"))
    origin = (request.form.get("origin") or "").strip()
    destination = (request.form.get("destination") or "").strip() or None
    fare_raw = (request.form.get("fare_quote") or "").replace(",", "").strip()
    try:
        fare_quote = float(fare_raw) if fare_raw else 0.0
    except Exception:
        fare_quote = 0.0
    if not origin:
        flash("Vui lòng nhập điểm đón (origin).", "warning")
        return redirect(url_for("sales_dashboard"))
    t = Trip(
        sales_id=current_user.id,
        origin=origin,
        destination=destination,
        fare_quote=fare_quote,
        status="booked",
        started_at=None,
        ended_at=None,
        car_id=None,
        driver_id=None,
    )
    db.session.add(t); db.session.commit()
    flash(f"Đã tạo đơn #{t.id}.", "success")
    return redirect(url_for("sales_dashboard"))

# ============================ DRIVER ============================
@app.route("/driver")
@login_required
def driver_dashboard():
    if current_user.role != "driver":
        return redirect(url_for("index"))

    driver = Driver.query.filter_by(user_id=current_user.id).first()
    if not driver:
        flash("Tài khoản chưa có hồ sơ Driver. Liên hệ admin.", "warning")
        return redirect(url_for("index"))

    today = date.today()
    day_start, day_end = day_bounds(today)
    mon_start, mon_end = month_bounds(today)

    trips_daily = Trip.query.filter(
        Trip.driver_id == driver.id,
        Trip.ended_at >= day_start, Trip.ended_at < day_end
    ).all()
    trips_month = Trip.query.filter(
        Trip.driver_id == driver.id,
        Trip.ended_at >= mon_start, Trip.ended_at < mon_end
    ).all()

    daily_rev = sum((t.final_fare or 0) for t in trips_daily)
    month_rev = sum((t.final_fare or 0) for t in trips_month)
    cash_daily = sum((t.cash_collected or 0) for t in trips_daily)
    cash_month = sum((t.cash_collected or 0) for t in trips_month)
    rate = current_user.commission_rate or 0.40

    open_trips = Trip.query.filter(
        Trip.status.in_(["booked", "assigned"]),
        Trip.driver_id.is_(None)
    ).order_by(Trip.id.asc()).all()

    my_assigned = Trip.query.filter(
        Trip.driver_id == driver.id,
        Trip.status.in_(["assigned", "ongoing"])
    ).order_by(Trip.id.desc()).all()

    return render_template(
        "driver_dashboard.html",
        trips_daily=trips_daily, trips_month=trips_month,
        daily_rev=daily_rev, month_rev=month_rev,
        cash_daily=cash_daily, cash_month=cash_month,
        driver_commission_rate=rate,
        commission_daily=daily_rev * rate,
        commission_month=month_rev * rate,
        open_trips=open_trips, my_assigned=my_assigned, driver=driver
    )

@app.route("/driver/claim/<int:trip_id>", methods=["POST"])
@login_required
def driver_claim(trip_id):
    if current_user.role != "driver":
        return redirect(url_for("index"))
    driver = Driver.query.filter_by(user_id=current_user.id).first()
    if not driver:
        flash("Tài khoản chưa gắn với Driver.", "danger")
        return redirect(url_for("driver_dashboard"))
    trip = db.session.get(Trip, trip_id)
    if not trip:
        flash("Đơn không tồn tại.", "danger")
        return redirect(url_for("driver_dashboard"))
    if trip.status not in ("booked", "assigned") or trip.driver_id is not None:
        flash("Đơn đã có tài xế khác nhận hoặc không còn ở trạng thái chờ.", "warning")
        return redirect(url_for("driver_dashboard"))
    trip.driver_id = driver.id
    if hasattr(driver, "car_id") and driver.car_id and hasattr(trip, "car_id"):
        trip.car_id = driver.car_id
    trip.status = "assigned"
    db.session.commit()
    flash(f"Đã nhận đơn #{trip.id}.", "success")
    return redirect(url_for("driver_dashboard"))

@app.route("/trip/start/<int:trip_id>", methods=["POST"])
@login_required
def trip_start_existing(trip_id):
    if current_user.role != "driver":
        return redirect(url_for("index"))
    driver = Driver.query.filter_by(user_id=current_user.id).first()
    if not driver:
        flash("Tài khoản chưa gắn với Driver.", "danger")
        return redirect(url_for("driver_dashboard"))
    trip = db.session.get(Trip, trip_id)
    if not trip:
        flash("Đơn không tồn tại.", "danger")
        return redirect(url_for("driver_dashboard"))

    if trip.driver_id is None:
        trip.driver_id = driver.id
        if hasattr(driver, "car_id") and driver.car_id and hasattr(trip, "car_id"):
            trip.car_id = driver.car_id
    elif trip.driver_id != driver.id:
        flash("Bạn không phải tài xế được gán cho đơn này.", "danger")
        return redirect(url_for("driver_dashboard"))

    if trip.status in ("booked", "assigned"):
        trip.started_at = now_local()
        trip.status = "ongoing"
        db.session.commit()
        flash(f"Đang chở đơn #{trip.id}.", "success")
    else:
        flash("Đơn này đã bắt đầu trước đó hoặc đã hoàn tất.", "warning")
    return redirect(url_for("driver_dashboard"))

@app.route("/trip/start", methods=["POST"])
@login_required
def trip_start():
    if current_user.role != "driver":
        return redirect(url_for("index"))
    driver = Driver.query.filter_by(user_id=current_user.id).first()
    trip = Trip(
        driver_id=driver.id,
        car_id=getattr(driver, "car_id", None),
        started_at=now_local(),
        origin=request.form.get("origin"),
        destination=None,
        status="ongoing",
        fare_quote=float(request.form.get("fare_quote") or 0),
        sales_id=int(request.form.get("sales_id")) if request.form.get("sales_id") else None
    )
    db.session.add(trip); db.session.commit()
    flash("Đã nhận khách.", "success")
    return redirect(url_for("driver_dashboard"))

@app.route("/trip/finish/<int:trip_id>", methods=["POST"])
@login_required
def trip_finish(trip_id):
    if current_user.role != "driver":
        return redirect(url_for("index"))
    trip = db.session.get(Trip, trip_id)
    if not trip:
        flash("Trip không tồn tại.", "danger")
        return redirect(url_for("driver_dashboard"))

    trip.ended_at = now_local()
    trip.destination = request.form.get("destination")
    trip.final_fare = float(request.form.get("final_fare") or trip.fare_quote or 0)
    trip.payment_method = request.form.get("payment_method")
    trip.cash_collected = float(request.form.get("cash_collected") or 0)
    trip.status = "completed"

    pay = Payment(
        trip_id=trip.id,
        method=trip.payment_method,
        amount=trip.final_fare,
        received_at=now_local(),
        reference_code=request.form.get("payment_ref") or None,
    )
    db.session.add(pay)
    db.session.commit()
    flash("Đã trả khách.", "success")
    return redirect(url_for("driver_dashboard"))

# ============================ ADMIN: DASHBOARD ============================
@app.route("/admin")
@login_required
def admin_dashboard():
    if current_user.role not in ("admin", "manager", "accountant"):
        return redirect(url_for("index"))
    total_trips = db.session.execute(db.select(db.func.count()).select_from(Trip)).scalar() or 0
    total_revenue = db.session.execute(db.select(db.func.sum(Trip.final_fare))).scalar() or 0
    total_cash = db.session.execute(db.select(db.func.sum(Trip.cash_collected))).scalar() or 0
    total_costs = db.session.execute(db.select(db.func.sum(Cost.amount))).scalar() or 0
    net_profit = (total_revenue or 0) - (total_costs or 0)
    return render_template("admin_dashboard.html",
                           total_trips=total_trips, total_revenue=total_revenue,
                           total_cash=total_cash, total_costs=total_costs, net_profit=net_profit)

# ============================ ADMIN: USERS HOME ============================
@app.route("/admin/users", methods=["GET"])
@login_required
def admin_users():
    if current_user.role not in ("admin", "manager"):
        return redirect(url_for("index"))
    sales_users = User.query.filter_by(role="sales").order_by(User.id.asc()).all()
    driver_users = User.query.filter_by(role="driver").order_by(User.id.asc()).all()
    return render_template("admin_users.html", sales_users=sales_users, driver_users=driver_users)

@app.route("/admin/users/create", methods=["POST"])
@login_required
def admin_users_create():
    if current_user.role not in ("admin", "manager"):
        return redirect(url_for("index"))

    role = (request.form.get("role") or "").strip()
    full_name = (request.form.get("full_name") or "").strip()
    position = (request.form.get("position") or "").strip()
    dob_s = (request.form.get("dob") or "").strip()
    join_s = (request.form.get("join_date") or "").strip()

    dob = None
    join_dt = None
    try:
        if dob_s: dob = datetime.strptime(dob_s, "%Y-%m-%d").date()
    except Exception: pass
    try:
        if join_s: join_dt = datetime.strptime(join_s, "%Y-%m-%d").date()
    except Exception: pass

    if role not in ("sales", "driver"):
        flash("Vai trò phải là sales hoặc driver.", "danger")
        return redirect(url_for("admin_users"))
    if not full_name:
        flash("Vui lòng nhập Họ và Tên.", "warning")
        return redirect(url_for("admin_users"))

    staff_code, email, password = generate_credentials(full_name, role, join_dt)

    user = User(email=email, role=role, active=True)
    # lưu thêm thuộc tính nếu có trong model
    set_attr_if_has(user, "username", staff_code)
    set_attr_if_has(user, "staff_code", staff_code)
    set_attr_if_has(user, "full_name", full_name)
    set_attr_if_has(user, "position", position)
    set_attr_if_has(user, "dob", dob)
    set_attr_if_has(user, "join_date", join_dt)
    # mặc định commission
    if role == "sales":
        if hasattr(user, "commission_rate") and not getattr(user, "commission_rate", None):
            user.commission_rate = 0.05
    elif role == "driver":
        if hasattr(user, "commission_rate") and not getattr(user, "commission_rate", None):
            user.commission_rate = 0.40

    set_password_smart(user, password)
    db.session.add(user); db.session.flush()

    if role == "driver":
        # tạo hồ sơ Driver tối thiểu
        drv = Driver(user_id=user.id)
        # cố gắng ghi họ tên nếu model có
        for f in ("name","full_name"):
            if hasattr(drv, f):
                setattr(drv, f, full_name or staff_code)
                break
        db.session.add(drv)

    db.session.commit()
    flash(f"Tạo {role} OK: email={email} | mật khẩu={password} | mã={staff_code}", "success")
    return redirect(url_for("admin_users"))

@app.route("/admin/users/delete/<int:user_id>", methods=["POST"])
@login_required
def admin_users_delete(user_id):
    if current_user.role not in ("admin", "manager"):
        return redirect(url_for("index"))
    u = db.session.get(User, user_id)
    if not u:
        flash("User không tồn tại.", "warning")
        return redirect(url_for("admin_users"))
    # xóa driver profile nếu có
    if u.role == "driver":
        d = Driver.query.filter_by(user_id=u.id).first()
        if d:
            db.session.delete(d)
    db.session.delete(u)
    db.session.commit()
    flash("Đã xóa nhân sự.", "success")
    return redirect(url_for("admin_users"))

# ============================ ADMIN: REPORTS ============================
def parse_date_arg(name="date", default=None):
    s = request.args.get(name)
    if s:
        try:
            y, m, d = map(int, s.split("-")); return date(y, m, d)
        except Exception:
            pass
    return default or date.today()

@app.route("/admin/reports/cashbook")
@login_required
def admin_cashbook():
    if current_user.role not in ("admin", "manager", "accountant"):
        return redirect(url_for("index"))
    day = parse_date_arg(default=date.today())
    day_start, day_end = day_bounds(day)
    pays = Payment.query.filter(Payment.received_at >= day_start, Payment.received_at < day_end).all()
    costs = Cost.query.filter(Cost.occurred_at >= day_start, Cost.occurred_at < day_end).all()
    total_in = sum((p.amount or 0) for p in pays)
    total_out = sum((c.amount or 0) for c in costs)
    return render_template("admin_cashbook.html", day=day, pays=pays, costs=costs, total_in=total_in, total_out=total_out, balance=(total_in-total_out))

@app.route("/admin/reports/sales-commission")
@login_required
def admin_sales_commission():
    if current_user.role not in ("admin", "manager", "accountant"):
        return redirect(url_for("index"))
    day = parse_date_arg(default=date.today())
    day_start, day_end = day_bounds(day)
    trips = Trip.query.filter(Trip.ended_at >= day_start, Trip.ended_at < day_end, Trip.sales_id != None).all()
    per = {}
    for t in trips:
        s = db.session.get(User, t.sales_id)
        if not s: continue
        rate = s.commission_rate or 0.05
        k = s.email
        per.setdefault(k, {"sales": s, "revenue": 0.0, "commission": 0.0, "trips": 0})
        per[k]["revenue"] += (t.final_fare or 0)
        per[k]["commission"] += (t.final_fare or 0) * rate
        per[k]["trips"] += 1
    rows = list(per.values())
    return render_template("admin_sales_commission.html", day=day, rows=rows)

@app.route("/admin/reports/driver-ops")
@login_required
def admin_driver_ops():
    if current_user.role not in ("admin", "manager", "accountant"):
        return redirect(url_for("index"))
    day = parse_date_arg(default=date.today())
    day_start, day_end = day_bounds(day)
    trips = Trip.query.filter(Trip.started_at >= day_start, Trip.started_at < day_end).all()
    per = {}
    for t in trips:
        drv = db.session.get(Driver, t.driver_id) if t.driver_id else None
        usr = db.session.get(User, drv.user_id) if drv else None
        car = db.session.get(Car, t.car_id) if t.car_id else None
        key = drv.id if drv else 0
        per.setdefault(key, {"driver": usr, "car": car, "trips": 0, "revenue": 0.0, "cash": 0.0})
        per[key]["trips"] += 1
        per[key]["revenue"] += (t.final_fare or 0)
        per[key]["cash"] += (t.cash_collected or 0)
    rows = list(per.values())
    return render_template("admin_driver_ops.html", day=day, rows=rows)

@app.route("/admin/reports/maintenance")
@login_required
def admin_maintenance():
    if current_user.role not in ("admin", "manager", "accountant"):
        return redirect(url_for("index"))
    upcoming = db.session.execute(db.select(Maintenance).where(Maintenance.scheduled_date >= date.today()).order_by(Maintenance.scheduled_date.asc())).scalars().all()
    past = db.session.execute(db.select(Maintenance).where(Maintenance.scheduled_date < date.today()).order_by(Maintenance.scheduled_date.desc())).scalars().all()
    maint_costs = db.session.execute(db.select(Cost).where(Cost.category=="maintenance").order_by(Cost.occurred_at.desc())).scalars().all()
    return render_template("admin_maintenance.html", upcoming=upcoming, past=past, maint_costs=maint_costs)

@app.route("/admin/reports/maintenance.csv")
@login_required
def admin_maintenance_csv():
    if current_user.role not in ("admin", "manager", "accountant"):
        return redirect(url_for("index"))
    rows = db.session.execute(db.select(Maintenance).order_by(Maintenance.scheduled_date.asc())).scalars().all()
    si = io.StringIO(); w = csv.writer(si)
    w.writerow(["id","car_id","scheduled_date","odometer_km","task","estimated_cost","actual_cost","notes"])
    for m in rows:
        w.writerow([m.id, m.car_id, m.scheduled_date, m.odometer_km, m.task, m.estimated_cost, m.actual_cost, m.notes])
    mem = io.BytesIO(si.getvalue().encode("utf-8-sig")); mem.seek(0)
    return send_file(mem, mimetype="text/csv", as_attachment=True, download_name="maintenance.csv")

# ==== MAIN ====
if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True)

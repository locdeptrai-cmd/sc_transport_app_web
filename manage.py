import click, random
from datetime import datetime, timedelta, date
from flask import Flask
import os, pandas as pd

from models import db, User, Car, Driver, Trip, Fare, Payment, Cost, Settings, Maintenance

def create_app():
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL", "sqlite:///sc.db")
    app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY", "dev-secret")
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    db.init_app(app)
    return app

app = create_app()

@app.cli.command("init-db")
def init_db():
    with app.app_context():
        db.drop_all()
        db.create_all()
        admin = User(email="admin@sc.local", role="admin", full_name="SC Admin", commission_rate=0.00)
        admin.set_password("Admin@123")
        db.session.add(admin)
        db.session.add(Settings(key="sales_commission_default", value="0.05"))
        db.session.add(Settings(key="driver_commission_default", value="0.40"))
        db.session.commit()
        click.echo("Initialized DB + admin account.")

def seed_sales(n=20):
    sales_users = []
    for i in range(1, n+1):
        email = f"sale{i:02d}@sc.local"
        u = User.query.filter_by(email=email).first()
        if not u:
            u = User(email=email, role="sales", full_name=f"Sales {i:02d}", commission_rate=0.05)
            u.set_password("Sale@123")
            db.session.add(u)
            sales_users.append(u)
    return sales_users

def guess_plate_and_driver(df):
    plate_col = None
    for c in df.columns:
        s = str(c).lower()
        if any(k in s for k in ["biển", "plate", "license", "xe", "bienso"]):
            plate_col = c; break
    if plate_col is None:
        plate_col = df.columns[0]
    driver_col = None
    for c in df.columns:
        s = str(c).lower()
        if any(k in s for k in ["tài xế","taixe","nhân viên","nhanvien","driver","họ tên","hoten"]):
            driver_col = c; break
    return plate_col, driver_col

def seed_cars_drivers_from_excel(excel_path=None):
    created = 0
    if excel_path and os.path.exists(excel_path):
        xls = pd.ExcelFile(excel_path)
        target_sheet = None
        for name in xls.sheet_names:
            if "CHI TIẾT" in name.upper() or "XE" in name.upper() or "CAR" in name.upper():
                target_sheet = name; break
        if target_sheet is None:
            target_sheet = xls.sheet_names[0]
        df = pd.read_excel(excel_path, sheet_name=target_sheet)
        plate_col, driver_col = guess_plate_and_driver(df)
        for _, row in df.iterrows():
            plate = str(row.get(plate_col,"")).strip()
            if not plate or plate.lower()=="nan":
                continue
            car = Car.query.filter_by(plate=plate).first()
            if not car:
                car = Car(plate=plate)
                db.session.add(car); db.session.flush()
                email = f"driver_{car.id}@sc.local"
                name = str(row.get(driver_col,"")).strip() if driver_col else ""
                user = User(email=email, role="driver", full_name=(name or f"Driver {car.id}"), commission_rate=0.40)
                user.set_password("Driver@123")
                db.session.add(user); db.session.flush()
                driver = Driver(user_id=user.id, car_id=car.id, license_no=f"D{car.id:04d}")
                db.session.add(driver)
                created += 1
    else:
        for i in range(1, 11):
            plate = f"SC-{i:02d}-{1000+i}"
            car = Car(plate=plate); db.session.add(car); db.session.flush()
            email = f"driver_{car.id}@sc.local"
            user = User(email=email, role="driver", full_name=f"Driver {car.id}", commission_rate=0.40)
            user.set_password("Driver@123")
            db.session.add(user); db.session.flush()
            driver = Driver(user_id=user.id, car_id=car.id, license_no=f"D{car.id:04d}")
            db.session.add(driver)
            created += 1
    return created

def seed_fares():
    presets = [
        ("SGN_T1-Center", "SGN T1", "Q1 Center", 7, 120000, 15000, 10000, 0, "Base day"),
        ("SGN_T3-ThuDuc", "SGN T3", "Thu Duc", 12, 180000, 15000, 10000, 20, "Night + airport"),
        ("SGN_T3-D7", "SGN T3", "District 7", 14, 200000, 15000, 10000, 0, ""),
    ]
    for rc, o, d, bk, bf, pk, sur, night, note in presets:
        if not db.session.execute(db.select(Fare).where(Fare.route_code==rc)).scalars().first():
            db.session.add(Fare(route_code=rc, origin=o, destination=d, base_km=bk, base_fare=bf, per_km=pk, airport_surcharge=sur, night_surcharge_pct=night, notes=note))

def seed_demo_trips(days_back=3):
    drivers = db.session.execute(db.select(Driver)).scalars().all()
    sales = db.session.execute(db.select(User).where(User.role=="sales")).scalars().all()
    if not drivers or not sales:
        return 0
    import random
    from random import choice, randint
    today = date.today()
    count = 0
    for d in drivers[:min(len(drivers), 12)]:
        for k in range(days_back, -1, -1):
            day = today - timedelta(days=k)
            for _ in range(randint(1, 2)):
                started = datetime(day.year, day.month, day.day, randint(6,22), randint(0,59))
                ended = started + timedelta(minutes=randint(25, 60))
                price = choice([180000, 200000, 220000, 250000, 280000])
                cash = choice([price, 0])
                s = choice(sales)
                t = Trip(driver_id=d.id, car_id=d.car_id, sales_id=s.id,
                         started_at=started, ended_at=ended,
                         origin="SGN T3", destination=choice(["Q1 Center","Thu Duc","District 7","Phu Nhuan"]),
                         fare_quote=price, final_fare=price, payment_method="cash" if cash>0 else "transfer",
                         cash_collected=cash, status="completed")
                db.session.add(t); db.session.flush()
                db.session.add(Payment(trip_id=t.id, method=t.payment_method, amount=t.final_fare, received_at=ended))
                count += 1
    return count

def seed_maintenance():
    cars = db.session.execute(db.select(Car)).scalars().all()
    if not cars:
        return 0
    from datetime import timedelta
    cnt = 0
    for i, c in enumerate(cars[:10], start=1):
        db.session.add(Maintenance(car_id=c.id, scheduled_date=date.today() + timedelta(days=7*i), odometer_km=50000+i*2500, task="Oil change", estimated_cost=800000, notes="Định kỳ 5k km"))
        db.session.add(Maintenance(car_id=c.id, scheduled_date=date.today() - timedelta(days=30*i), odometer_km=45000+i*2000, task="Brake inspection", estimated_cost=600000, actual_cost=620000, notes="Đã thực hiện"))
        db.session.add(Cost(car_id=c.id, category="maintenance", amount=620000.0, notes="Brake inspection"))
        cnt += 2
    return cnt

@app.cli.command("seed-all")
@click.option("--excel", default=None, help="Path to XE SC.xlsx to create drivers/cars")
def seed_all(excel):
    with app.app_context():
        added_sales = seed_sales(20)
        created = seed_cars_drivers_from_excel(excel)
        seed_fares()
        trips = seed_demo_trips(3)
        maint = seed_maintenance()
        db.session.commit()
        click.echo(f"Seeded: sales={len(added_sales)}; drivers_from_excel={created}; demo_trips={trips}; maintenance={maint}.")

# Utilities
@app.cli.command("list-users")
def list_users():
    with app.app_context():
        rows = db.session.execute(db.select(User)).scalars().all()
        for u in rows:
            print(f"{u.id:>3} | {u.email:30} | {u.role:10} | active={u.active} | rate={u.commission_rate}")

@app.cli.command("set-password")
@click.argument("email")
@click.argument("newpass")
def set_password(email, newpass):
    with app.app_context():
        u = User.query.filter_by(email=email).first()
        if not u:
            print("User not found"); return
        u.set_password(newpass); db.session.commit()
        print(f"Password reset for {email}")

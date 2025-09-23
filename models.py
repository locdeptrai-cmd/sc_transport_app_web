from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from passlib.hash import bcrypt
from datetime import datetime, date

db = SQLAlchemy()

class Settings(db.Model):
    __tablename__ = "settings"
    key = db.Column(db.String(64), primary_key=True)
    value = db.Column(db.String(256))

class User(UserMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="sales")
    full_name = db.Column(db.String(120))
    phone = db.Column(db.String(40))
    commission_rate = db.Column(db.Float, default=0.05)
    active = db.Column(db.Boolean, default=True)

    def set_password(self, password: str):
        self.password_hash = bcrypt.hash(password)

    def check_password(self, password: str) -> bool:
        try:
            return bcrypt.verify(password, self.password_hash)
        except Exception:
            return False

class Car(db.Model):
    __tablename__ = "cars"
    id = db.Column(db.Integer, primary_key=True)
    plate = db.Column(db.String(32), unique=True, nullable=False)
    make = db.Column(db.String(64))
    model = db.Column(db.String(64))
    year = db.Column(db.Integer)

class Driver(db.Model):
    __tablename__ = "drivers"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    car_id = db.Column(db.Integer, db.ForeignKey("cars.id"), nullable=False)
    license_no = db.Column(db.String(64))

class Fare(db.Model):
    __tablename__ = "fares"
    id = db.Column(db.Integer, primary_key=True)
    route_code = db.Column(db.String(32), unique=True)
    origin = db.Column(db.String(64))
    destination = db.Column(db.String(64))
    base_km = db.Column(db.Float, default=0)
    base_fare = db.Column(db.Float, default=0)
    per_km = db.Column(db.Float, default=0)
    airport_surcharge = db.Column(db.Float, default=0)
    night_surcharge_pct = db.Column(db.Float, default=0)
    notes = db.Column(db.String(255))

class Trip(db.Model):
    __tablename__ = "trips"
    id = db.Column(db.Integer, primary_key=True)
    driver_id = db.Column(db.Integer, db.ForeignKey("drivers.id"))
    car_id = db.Column(db.Integer, db.ForeignKey("cars.id"))
    sales_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    started_at = db.Column(db.DateTime)
    ended_at = db.Column(db.DateTime)
    origin = db.Column(db.String(64))
    destination = db.Column(db.String(64))
    distance_km = db.Column(db.Float, default=0)
    fare_quote = db.Column(db.Float, default=0)
    final_fare = db.Column(db.Float, default=0)
    payment_method = db.Column(db.String(32))
    cash_collected = db.Column(db.Float, default=0)
    status = db.Column(db.String(16), default="planned")

class Payment(db.Model):
    __tablename__ = "payments"
    id = db.Column(db.Integer, primary_key=True)
    trip_id = db.Column(db.Integer, db.ForeignKey("trips.id"), nullable=False)
    method = db.Column(db.String(32))
    amount = db.Column(db.Float, default=0)
    received_at = db.Column(db.DateTime, default=datetime.utcnow)
    reference_code = db.Column(db.String(64))

class Cost(db.Model):
    __tablename__ = "costs"
    id = db.Column(db.Integer, primary_key=True)
    occurred_at = db.Column(db.DateTime, default=datetime.utcnow)
    car_id = db.Column(db.Integer, db.ForeignKey("cars.id"))
    driver_id = db.Column(db.Integer, db.ForeignKey("drivers.id"))
    category = db.Column(db.String(64))
    amount = db.Column(db.Float, default=0)
    notes = db.Column(db.String(255))

class Maintenance(db.Model):
    __tablename__ = "maintenance"
    id = db.Column(db.Integer, primary_key=True)
    car_id = db.Column(db.Integer, db.ForeignKey("cars.id"), nullable=False)
    scheduled_date = db.Column(db.Date)
    odometer_km = db.Column(db.Integer)
    task = db.Column(db.String(128))
    estimated_cost = db.Column(db.Float, default=0)
    actual_cost = db.Column(db.Float, default=0)
    notes = db.Column(db.String(255))

from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, FloatField, IntegerField, TextAreaField, SelectField, FileField, BooleanField
from wtforms.validators import DataRequired, Email, Length, ValidationError, Optional
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import os
import json
from datetime import datetime, timedelta
import io
from reportlab.pdfgen import canvas
from flask import Response
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.lib import colors
import csv

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-change-in-production'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///courier.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Create upload directory if it doesn't exist
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

@login_manager.user_loader
def load_user(user_id):
    return Client.query.get(int(user_id))

# Database Models
class Client(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    cnic = db.Column(db.String(20), unique=True, nullable=False)
    address = db.Column(db.Text, nullable=False)
    postal_code = db.Column(db.String(20), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Country(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    code = db.Column(db.String(3), unique=True, nullable=False)
    currency = db.Column(db.String(3), nullable=False)
    is_active = db.Column(db.Boolean, default=True)

class PricingTier(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    country_id = db.Column(db.Integer, db.ForeignKey('country.id'), nullable=False)
    min_weight = db.Column(db.Float, nullable=False)
    max_weight = db.Column(db.Float, nullable=False)
    price_per_kg = db.Column(db.Float, nullable=False)
    base_fee = db.Column(db.Float, default=0)
    is_active = db.Column(db.Boolean, default=True)

    country = db.relationship('Country', backref=db.backref('pricing_tiers', lazy=True))

class Shipment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tracking_id = db.Column(db.String(50), unique=True, nullable=False)
    client_id = db.Column(db.Integer, db.ForeignKey('client.id'), nullable=False)

    # Sender Information
    sender_name = db.Column(db.String(100), nullable=False)
    sender_phone = db.Column(db.String(20), nullable=False)
    sender_cnic = db.Column(db.String(20), nullable=False)
    sender_address = db.Column(db.Text, nullable=False)
    sender_postal_code = db.Column(db.String(20), nullable=False)

    # Receiver Information
    receiver_name = db.Column(db.String(100), nullable=False)
    receiver_phone = db.Column(db.String(20), nullable=False)
    receiver_cnic = db.Column(db.String(20), nullable=False)
    receiver_address = db.Column(db.Text, nullable=False)
    receiver_postal_code = db.Column(db.String(20), nullable=False)

    # Package Information
    destination_country_id = db.Column(db.Integer, db.ForeignKey('country.id'), nullable=False)
    length = db.Column(db.Float, nullable=False)
    width = db.Column(db.Float, nullable=False)
    height = db.Column(db.Float, nullable=False)
    actual_weight = db.Column(db.Float, nullable=False)
    weight_type = db.Column(db.String(20), nullable=False)  # 'actual' or 'volumetric'
    document_type = db.Column(db.String(20), nullable=False, default='non_docs')  # 'docs' or 'non_docs'

    # Pricing Information
    volumetric_weight = db.Column(db.Float, nullable=False)
    chargeable_weight = db.Column(db.Float, nullable=False)
    base_price = db.Column(db.Float, nullable=False)
    gst_amount = db.Column(db.Float, nullable=False)
    final_price = db.Column(db.Float, nullable=False)

    # Status
    status = db.Column(db.String(20), default='booked')  # booked, in_transit, delivered, cancelled

    # Undertaking
    undertaking_accepted = db.Column(db.Boolean, default=False)
    undertaking_text = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    client = db.relationship('Client', backref=db.backref('shipments', lazy=True))
    destination_country = db.relationship('Country', backref=db.backref('shipments', lazy=True))

class DailyRecord(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False, unique=True)
    total_shipments = db.Column(db.Integer, default=0)
    total_revenue = db.Column(db.Float, default=0)
    total_weight = db.Column(db.Float, default=0)
    avg_package_value = db.Column(db.Float, default=0)
    top_destination = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class MonthlyRecord(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    year = db.Column(db.Integer, nullable=False)
    month = db.Column(db.Integer, nullable=False)  # 1-12
    total_shipments = db.Column(db.Integer, default=0)
    total_revenue = db.Column(db.Float, default=0)
    total_weight = db.Column(db.Float, default=0)
    avg_package_value = db.Column(db.Float, default=0)
    growth_rate = db.Column(db.Float, default=0)  # Compared to previous month
    top_destination = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint('year', 'month', name='unique_year_month'),)

class ShipmentAnalytics(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    shipment_id = db.Column(db.Integer, db.ForeignKey('shipment.id'), nullable=False)
    processing_time = db.Column(db.Float)  # Time from booking to delivery in hours
    delivery_status = db.Column(db.String(20), default='pending')
    customer_rating = db.Column(db.Integer)  # 1-5 rating
    issues_reported = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    shipment = db.relationship('Shipment', backref=db.backref('analytics', lazy=True))

# Forms
class LoginForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired()])

class RegistrationForm(FlaskForm):
    name = StringField('Full Name', validators=[DataRequired(), Length(min=2, max=100)])
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired(), Length(min=6)])
    phone = StringField('Phone', validators=[DataRequired(), Length(min=10, max=20)])
    cnic = StringField('CNIC', validators=[DataRequired(), Length(min=13, max=20)])
    address = TextAreaField('Address', validators=[DataRequired()])
    postal_code = StringField('Postal Code', validators=[DataRequired()])

    def validate_email(self, email):
        client = Client.query.filter_by(email=email.data).first()
        if client:
            raise ValidationError('Email already registered.')

    def validate_cnic(self, cnic):
        client = Client.query.filter_by(cnic=cnic.data).first()
        if client:
            raise ValidationError('CNIC already registered.')


class ShipmentForm(FlaskForm):
    # Sender Information
    sender_name = StringField('Sender Name', validators=[DataRequired()])
    sender_phone = StringField('Sender Phone', validators=[DataRequired()])
    sender_cnic = StringField('Sender CNIC', validators=[DataRequired()])
    sender_address = TextAreaField('Sender Address', validators=[DataRequired()])
    sender_postal_code = StringField('Sender Postal Code', validators=[DataRequired()])

    # Receiver Information
    receiver_name = StringField('Receiver Name', validators=[DataRequired()])
    receiver_phone = StringField('Receiver Phone', validators=[DataRequired()])
    receiver_cnic = StringField('Receiver CNIC', validators=[DataRequired()])
    receiver_address = TextAreaField('Receiver Address', validators=[DataRequired()])
    receiver_postal_code = StringField('Receiver Postal Code', validators=[DataRequired()])

    # Package Information
    destination_country = SelectField('Destination Country', validators=[DataRequired()])
    length = FloatField('Length (cm)', validators=[DataRequired()])
    width = FloatField('Width (cm)', validators=[DataRequired()])
    height = FloatField('Height (cm)', validators=[DataRequired()])
    actual_weight = FloatField('Actual Weight (kg)', validators=[DataRequired()])
    weight_type = SelectField('Weight Type', choices=[('actual', 'Actual Weight'), ('volumetric', 'Volumetric Weight')], validators=[DataRequired()])
    document_type = SelectField('Package Type', choices=[('docs', 'Documents'), ('non_docs', 'Non-Documents')], validators=[DataRequired()])

    # Undertaking
    undertaking_accepted = BooleanField('I accept the Terms and Conditions', validators=[Optional()])
    undertaking_text = TextAreaField('Special Instructions (Optional)', validators=[Optional()])

class PricingUploadForm(FlaskForm):
    pricing_file = FileField('Pricing File (CSV)', validators=[DataRequired()])

# Routes
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    form = LoginForm()
    if form.validate_on_submit():
        client = Client.query.filter_by(email=form.email.data).first()
        if client and client.check_password(form.password.data):
            login_user(client)
            flash('Logged in successfully!', 'success')
            return redirect(url_for('dashboard'))
        flash('Invalid email or password.', 'error')

    return render_template('login.html', form=form)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    form = RegistrationForm()
    if form.validate_on_submit():
        client = Client(
            name=form.name.data,
            email=form.email.data,
            phone=form.phone.data,
            cnic=form.cnic.data,
            address=form.address.data,
            postal_code=form.postal_code.data
        )
        client.set_password(form.password.data)
        db.session.add(client)
        db.session.commit()

        flash('Registration successful! Please log in.', 'success')
        return redirect(url_for('login'))

    return render_template('register.html', form=form)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Logged out successfully!', 'success')
    return redirect(url_for('index'))

@app.route('/dashboard')
@login_required
def dashboard():
    shipments = Shipment.query.filter_by(client_id=current_user.id).order_by(Shipment.created_at.desc()).limit(10).all()

    # Get statistics
    total_shipments = Shipment.query.filter_by(client_id=current_user.id).count()
    total_revenue = db.session.query(db.func.sum(Shipment.final_price)).filter_by(client_id=current_user.id).scalar() or 0

    # Today's stats
    today = datetime.now().date()
    today_stats = DailyRecord.query.filter_by(date=today).first()

    # Current month's stats
    current_month = datetime.now().month
    current_year = datetime.now().year
    month_stats = MonthlyRecord.query.filter_by(year=current_year, month=current_month).first()

    return render_template('dashboard.html',
                         shipments=shipments,
                         total_shipments=total_shipments,
                         total_revenue=total_revenue,
                         today_stats=today_stats,
                         month_stats=month_stats)

@app.route('/book-shipment', methods=['GET', 'POST'])
@login_required
def book_shipment():
    form = ShipmentForm()
    countries = Country.query.filter_by(is_active=True).all()
    form.destination_country.choices = [(str(c.id), f"{c.name} ({c.currency})") for c in countries]

    if form.validate_on_submit():
        # Calculate pricing
        pricing_data = calculate_pricing(
            form.destination_country.data,
            form.length.data,
            form.width.data,
            form.height.data,
            form.actual_weight.data,
            form.weight_type.data
        )

        if 'error' in pricing_data:
            flash(pricing_data['error'], 'error')
            return render_template('book_shipment.html', form=form)

        # Generate tracking ID
        tracking_id = generate_tracking_id()

        # Create shipment
        shipment = Shipment(
            tracking_id=tracking_id,
            client_id=current_user.id,
            sender_name=form.sender_name.data,
            sender_phone=form.sender_phone.data,
            sender_cnic=form.sender_cnic.data,
            sender_address=form.sender_address.data,
            sender_postal_code=form.sender_postal_code.data,
            receiver_name=form.receiver_name.data,
            receiver_phone=form.receiver_phone.data,
            receiver_cnic=form.receiver_cnic.data,
            receiver_address=form.receiver_address.data,
            receiver_postal_code=form.receiver_postal_code.data,
            destination_country_id=form.destination_country.data,
            length=form.length.data,
            width=form.width.data,
            height=form.height.data,
            actual_weight=form.actual_weight.data,
            weight_type=form.weight_type.data,
            document_type=form.document_type.data,
            volumetric_weight=pricing_data['volumetric_weight'],
            chargeable_weight=pricing_data['chargeable_weight'],
            base_price=pricing_data['base_price'],
            gst_amount=pricing_data['gst_amount'],
            final_price=pricing_data['final_price'],
            undertaking_accepted=form.undertaking_accepted.data,
            undertaking_text=form.undertaking_text.data or None
        )

        db.session.add(shipment)
        db.session.commit()

        # Generate analytics for the shipment
        generate_shipment_analytics(shipment.id)

        # Update daily and monthly records
        update_daily_records()
        update_monthly_records()

        flash(f'Shipment booked successfully! Tracking ID: {tracking_id}', 'success')
        return redirect(url_for('shipment_slip', shipment_id=shipment.id))

    return render_template('book_shipment.html', form=form)

@app.route('/api/calculate-pricing', methods=['POST'])
@login_required
def api_calculate_pricing():
    data = request.get_json()
    result = calculate_pricing(
        data['country_id'],
        data['length'],
        data['width'],
        data['height'],
        data['weight'],
        data['weight_type']
    )
    return jsonify(result)

@app.route('/shipment/<int:shipment_id>/receipt')
@login_required
def shipment_receipt(shipment_id):
    shipment = Shipment.query.get_or_404(shipment_id)
    if shipment.client_id != current_user.id and not current_user.is_admin:
        flash('Access denied.', 'error')
        return redirect(url_for('dashboard'))

    return render_template('receipt.html', shipment=shipment)

@app.route('/shipment/<int:shipment_id>/slip')
@login_required
def shipment_slip(shipment_id):
    shipment = Shipment.query.get_or_404(shipment_id)
    if shipment.client_id != current_user.id and not current_user.is_admin:
        flash('Access denied.', 'error')
        return redirect(url_for('dashboard'))

    return render_template('shipment_slip.html', shipment=shipment)

@app.route('/shipment/<int:shipment_id>/download-all-slips')
@login_required
def download_all_slips(shipment_id):
    shipment = Shipment.query.get_or_404(shipment_id)
    if shipment.client_id != current_user.id and not current_user.is_admin:
        flash('Access denied.', 'error')
        return redirect(url_for('dashboard'))

    # Generate PDF with all three slips
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    styles = getSampleStyleSheet()

    # Custom styles
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=20,
        spaceAfter=20,
        alignment=1  # Center alignment
    )

    content = []

    # Helper function to create slip content
    def create_slip_content(slip_type, title, border_color):
        slip_content = []

        # Header
        slip_content.append(Paragraph(f'PICS Courier Services - {title}', title_style))
        slip_content.append(Paragraph(f'Tracking ID: {shipment.tracking_id}', styles['Heading3']))
        slip_content.append(Spacer(1, 20))

        # Sender and Receiver Information
        sender_receiver_data = [
            ['Sender Information', 'Receiver Information'],
            ['Name:', shipment.sender_name, 'Name:', shipment.receiver_name],
            ['CNIC:', shipment.sender_cnic, 'CNIC:', shipment.receiver_cnic],
            ['Phone:', shipment.sender_phone, 'Phone:', shipment.receiver_phone],
            ['Address:', shipment.sender_address, 'Address:', shipment.receiver_address],
            ['Postal Code:', shipment.sender_postal_code, 'Postal Code:', shipment.receiver_postal_code]
        ]

        table = Table(sender_receiver_data, colWidths=[100, 200, 100, 200])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 12),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        slip_content.append(table)
        slip_content.append(Spacer(1, 20))

        # Package Details
        slip_content.append(Paragraph('Package Details', styles['Heading3']))

        # Different package details for parcel label vs other slips
        if slip_type == 'parcel':
            # Parcel label - minimal info, no pricing
            package_data = [
                ['Weight (kg):', f"{shipment.chargeable_weight:.2f}"],
                ['Dimensions (cm):', f"{shipment.length}×{shipment.width}×{shipment.height}"],
                ['Destination:', shipment.destination_country.name],
                ['Package Type:', 'Documents' if shipment.document_type == 'docs' else 'Non-Documents']
            ]
        else:
            # Sender and Courier copies - full details with pricing
            package_data = [
                ['Length (cm):', str(shipment.length)],
                ['Width (cm):', str(shipment.width)],
                ['Height (cm):', str(shipment.height)],
                ['Actual Weight (kg):', str(shipment.actual_weight)],
                ['Volumetric Weight (kg):', f"{shipment.volumetric_weight:.2f}"],
                ['Chargeable Weight (kg):', f"{shipment.chargeable_weight:.2f}"],
                ['Weight Type:', shipment.weight_type.title()],
                ['Package Type:', 'Documents' if shipment.document_type == 'docs' else 'Non-Documents']
            ]

        package_table = Table(package_data, colWidths=[150, 100])
        package_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.lightblue),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        slip_content.append(package_table)
        slip_content.append(Spacer(1, 20))

        # Pricing Details (only for sender and courier copies, not parcel label)
        if slip_type != 'parcel':
            slip_content.append(Paragraph('Pricing Details', styles['Heading3']))
            pricing_data = [
                ['Base Price:', f"{shipment.destination_country.currency} {shipment.base_price:.2f}"],
                ['GST (18%):', f"{shipment.destination_country.currency} {shipment.gst_amount:.2f}"],
                ['Final Price:', f"{shipment.destination_country.currency} {shipment.final_price:.2f}"]
            ]

            pricing_table = Table(pricing_data, colWidths=[150, 100])
            pricing_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, -1), colors.lightgreen),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('FONTNAME', (-1, 0), (-1, -1), 'Helvetica-Bold')
            ]))
            slip_content.append(pricing_table)
            slip_content.append(Spacer(1, 30))

        # Footer
        slip_content.append(Paragraph(f'Date: {shipment.created_at.strftime("%Y-%m-%d %H:%M")}', styles['Normal']))
        slip_content.append(Paragraph('Thank you for choosing PICS!', styles['Italic']))

        return slip_content

    # Add all three slips
    content.extend(create_slip_content('sender', 'SENDER COPY', colors.blue))
    content.append(PageBreak())
    content.extend(create_slip_content('courier', 'COURIER OFFICE COPY', colors.green))
    content.append(PageBreak())
    content.extend(create_slip_content('parcel', 'PARCEL LABEL', colors.purple))

    doc.build(content)

    buffer.seek(0)
    return send_file(
        buffer,
        as_attachment=True,
        download_name=f'shipment-slips-{shipment.tracking_id}.pdf',
        mimetype='application/pdf'
    )

@app.route('/shipment/<int:shipment_id>/download-receipt')
@login_required
def download_receipt(shipment_id):
    shipment = Shipment.query.get_or_404(shipment_id)
    if shipment.client_id != current_user.id and not current_user.is_admin:
        flash('Access denied.', 'error')
        return redirect(url_for('dashboard'))

    # Generate PDF receipt
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    styles = getSampleStyleSheet()

    # Custom styles
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        spaceAfter=30,
        alignment=1  # Center alignment
    )

    content = []

    # Header
    content.append(Paragraph('PICS Courier Services', title_style))
    content.append(Paragraph('Shipment Receipt', styles['Heading2']))
    content.append(Paragraph(f'Tracking ID: {shipment.tracking_id}', styles['Heading3']))
    content.append(Spacer(1, 20))

    # Sender and Receiver Information
    sender_receiver_data = [
        ['Sender Information', 'Receiver Information'],
        ['Name:', shipment.sender_name, 'Name:', shipment.receiver_name],
        ['CNIC:', shipment.sender_cnic, 'CNIC:', shipment.receiver_cnic],
        ['Phone:', shipment.sender_phone, 'Phone:', shipment.receiver_phone],
        ['Address:', shipment.sender_address, 'Address:', shipment.receiver_address],
        ['Postal Code:', shipment.sender_postal_code, 'Postal Code:', shipment.receiver_postal_code]
    ]

    table = Table(sender_receiver_data, colWidths=[100, 200, 100, 200])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 14),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))
    content.append(table)
    content.append(Spacer(1, 20))

    # Package Details
    content.append(Paragraph('Package Details', styles['Heading3']))
    package_data = [
        ['Length (cm):', str(shipment.length)],
        ['Width (cm):', str(shipment.width)],
        ['Height (cm):', str(shipment.height)],
        ['Actual Weight (kg):', str(shipment.actual_weight)],
        ['Volumetric Weight (kg):', f"{shipment.volumetric_weight:.2f}"],
        ['Chargeable Weight (kg):', f"{shipment.chargeable_weight:.2f}"],
        ['Weight Type:', shipment.weight_type.title()],
        ['Package Type:', 'Documents' if shipment.document_type == 'docs' else 'Non-Documents']
    ]

    package_table = Table(package_data, colWidths=[150, 100])
    package_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.lightblue),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))
    content.append(package_table)
    content.append(Spacer(1, 20))

    # Pricing Details
    content.append(Paragraph('Pricing Details', styles['Heading3']))
    pricing_data = [
        ['Base Price:', f"{shipment.destination_country.currency} {shipment.base_price:.2f}"],
        ['GST (18%):', f"{shipment.destination_country.currency} {shipment.gst_amount:.2f}"],
        ['Final Price:', f"{shipment.destination_country.currency} {shipment.final_price:.2f}"]
    ]

    pricing_table = Table(pricing_data, colWidths=[150, 100])
    pricing_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.lightgreen),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('FONTNAME', (-1, 0), (-1, -1), 'Helvetica-Bold')
    ]))
    content.append(pricing_table)
    content.append(Spacer(1, 20))

    # Undertaking Details
    if shipment.undertaking_accepted or shipment.undertaking_text:
        content.append(Paragraph('Declaration & Special Instructions', styles['Heading3']))

        undertaking_data = []
        if shipment.undertaking_accepted:
            undertaking_data.append(['Terms Accepted:', 'Yes'])
        if shipment.undertaking_text:
            undertaking_data.append(['Special Instructions:', shipment.undertaking_text])

        if undertaking_data:
            undertaking_table = Table(undertaking_data, colWidths=[150, 300])
            undertaking_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, -1), colors.lightyellow),
                ('GRID', (0, 0), (-1, -1), 1, colors.black)
            ]))
            content.append(undertaking_table)
            content.append(Spacer(1, 20))

    # Footer
    content.append(Paragraph(f'Date: {shipment.created_at.strftime("%Y-%m-%d %H:%M")}', styles['Normal']))
    content.append(Paragraph('Thank you for choosing PICS!', styles['Italic']))

    doc.build(content)

    buffer.seek(0)
    return send_file(
        buffer,
        as_attachment=True,
        download_name=f'receipt-{shipment.tracking_id}.pdf',
        mimetype='application/pdf'
    )

# Admin Routes
@app.route('/admin')
@login_required
def admin():
    if not current_user.is_admin:
        flash('Access denied. Admin privileges required.', 'error')
        return redirect(url_for('dashboard'))

    # Get statistics
    total_shipments = Shipment.query.count()
    total_clients = Client.query.filter_by(is_admin=False).count()
    active_countries = Country.query.filter_by(is_active=True).count()
    total_revenue = db.session.query(db.func.sum(Shipment.final_price)).scalar() or 0

    return render_template('admin.html',
                         total_shipments=total_shipments,
                         total_clients=total_clients,
                         active_countries=active_countries,
                         total_revenue=total_revenue)

@app.route('/admin/upload-pricing', methods=['GET', 'POST'])
@login_required
def upload_pricing():
    if not current_user.is_admin:
        flash('Access denied. Admin privileges required.', 'error')
        return redirect(url_for('dashboard'))

    form = PricingUploadForm()
    if form.validate_on_submit():
        file = form.pricing_file.data
        filename = secure_filename(file.filename)

        if filename.endswith('.csv'):
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)

            # Process CSV file
            success_count = 0
            error_count = 0

            try:
                with open(file_path, 'r') as csvfile:
                    reader = csv.DictReader(csvfile)
                    for row in reader:
                        try:
                            # Get or create country
                            country = Country.query.filter_by(code=row['country_code'].upper()).first()
                            if not country:
                                country = Country(
                                    name=row['country_name'],
                                    code=row['country_code'].upper(),
                                    currency=row['currency'].upper(),
                                    is_active=True
                                )
                                db.session.add(country)
                                db.session.flush()  # Get the country ID

                            # Create pricing tier
                            pricing_tier = PricingTier(
                                country_id=country.id,
                                min_weight=float(row['min_weight']),
                                max_weight=float(row['max_weight']),
                                price_per_kg=float(row['price_per_kg']),
                                base_fee=float(row.get('base_fee', 0)),
                                is_active=True
                            )
                            db.session.add(pricing_tier)
                            success_count += 1

                        except Exception as e:
                            print(f"Error processing row: {e}")
                            error_count += 1

                db.session.commit()
                flash(f'Pricing data uploaded successfully! {success_count} records added, {error_count} errors.', 'success')

            except Exception as e:
                db.session.rollback()
                flash(f'Error processing file: {str(e)}', 'error')

            # Clean up uploaded file
            os.remove(file_path)
        else:
            flash('Please upload a CSV file.', 'error')

    pricing_tiers = PricingTier.query.all()
    return render_template('upload_pricing.html', form=form, pricing_tiers=pricing_tiers)

# Report Routes
@app.route('/admin/reports')
@login_required
def reports():
    if not current_user.is_admin:
        flash('Access denied. Admin privileges required.', 'error')
        return redirect(url_for('dashboard'))

    # Get summary statistics
    today = datetime.now().date()
    current_month = datetime.now().month
    current_year = datetime.now().year

    todays_shipments = Shipment.query.filter(
        db.func.date(Shipment.created_at) == today
    ).count()

    monthly_revenue = db.session.query(db.func.sum(Shipment.final_price)).filter(
        db.func.extract('month', Shipment.created_at) == current_month,
        db.func.extract('year', Shipment.created_at) == current_year
    ).scalar() or 0

    total_shipments = Shipment.query.count()

    # Calculate growth rate (current month vs previous month)
    prev_month = current_month - 1 if current_month > 1 else 12
    prev_year = current_year if current_month > 1 else current_year - 1

    current_month_revenue = db.session.query(db.func.sum(Shipment.final_price)).filter(
        db.func.extract('month', Shipment.created_at) == current_month,
        db.func.extract('year', Shipment.created_at) == current_year
    ).scalar() or 0

    prev_month_revenue = db.session.query(db.func.sum(Shipment.final_price)).filter(
        db.func.extract('month', Shipment.created_at) == prev_month,
        db.func.extract('year', Shipment.created_at) == prev_year
    ).scalar() or 0

    growth_rate = ((current_month_revenue - prev_month_revenue) / prev_month_revenue * 100) if prev_month_revenue > 0 else 0

    # Get recent daily records
    recent_records = DailyRecord.query.order_by(DailyRecord.date.desc()).limit(5).all()

    return render_template('reports.html',
                         todays_shipments=todays_shipments,
                         monthly_revenue=monthly_revenue,
                         total_shipments=total_shipments,
                         growth_rate=growth_rate,
                         recent_records=recent_records)

@app.route('/admin/reports/daily')
@login_required
def daily_reports():
    if not current_user.is_admin:
        flash('Access denied. Admin privileges required.', 'error')
        return redirect(url_for('dashboard'))

    # Get date range parameters
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')

    if start_date_str and end_date_str:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
    else:
        # Default to last 30 days
        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=30)

    daily_records = DailyRecord.query.filter(
        DailyRecord.date >= start_date,
        DailyRecord.date <= end_date
    ).order_by(DailyRecord.date.desc()).all()

    # Calculate summary statistics
    total_shipments = sum(record.total_shipments for record in daily_records)
    total_revenue = sum(record.total_revenue for record in daily_records)
    total_weight = sum(record.total_weight for record in daily_records)
    avg_package_value = total_revenue / total_shipments if total_shipments > 0 else 0

    return render_template('daily_reports.html',
                         daily_records=daily_records,
                         start_date=start_date,
                         end_date=end_date,
                         total_shipments=total_shipments,
                         total_revenue=total_revenue,
                         total_weight=total_weight,
                         avg_package_value=avg_package_value)

@app.route('/admin/reports/monthly')
@login_required
def monthly_reports():
    if not current_user.is_admin:
        flash('Access denied. Admin privileges required.', 'error')
        return redirect(url_for('dashboard'))

    # Get year parameter
    year = request.args.get('year', datetime.now().year, type=int)
    current_year = year

    # Get monthly records for the selected year
    monthly_records = MonthlyRecord.query.filter(
        MonthlyRecord.year == year
    ).order_by(MonthlyRecord.month.desc()).all()

    # Calculate summary statistics
    total_shipments = sum(record.total_shipments for record in monthly_records)
    total_revenue = sum(record.total_revenue for record in monthly_records)
    total_weight = sum(record.total_weight for record in monthly_records)
    avg_growth_rate = sum(record.growth_rate for record in monthly_records) / len(monthly_records) if monthly_records else 0

    return render_template('monthly_reports.html',
                         monthly_records=monthly_records,
                         current_year=current_year,
                         total_shipments=total_shipments,
                         total_revenue=total_revenue,
                         total_weight=total_weight,
                         avg_growth_rate=avg_growth_rate)

@app.route('/admin/reports/export/daily/<date>')
@login_required
def export_daily_report(date):
    if not current_user.is_admin:
        flash('Access denied. Admin privileges required.', 'error')
        return redirect(url_for('dashboard'))

    try:
        report_date = datetime.strptime(date, '%Y-%m-%d').date()
        daily_record = DailyRecord.query.filter_by(date=report_date).first()

        if not daily_record:
            flash('No data found for the selected date.', 'error')
            return redirect(url_for('daily_reports'))

        # Generate CSV
        output = io.StringIO()
        writer = csv.writer(output)

        # Write header
        writer.writerow(['Date', 'Total Shipments', 'Total Revenue', 'Total Weight (kg)', 'Avg Package Value', 'Top Destination'])

        # Write data
        writer.writerow([
            daily_record.date.strftime('%Y-%m-%d'),
            daily_record.total_shipments,
            f"{daily_record.total_revenue:.2f}",
            f"{daily_record.total_weight:.2f}",
            f"{daily_record.avg_package_value:.2f}",
            daily_record.top_destination or 'N/A'
        ])

        # Get detailed shipment data for the day
        day_shipments = Shipment.query.filter(
            db.func.date(Shipment.created_at) == report_date
        ).all()

        writer.writerow([])  # Empty row
        writer.writerow(['Detailed Shipment Data'])
        writer.writerow(['Tracking ID', 'Destination', 'Weight (kg)', 'Final Price', 'Weight Type', 'Created At'])

        for shipment in day_shipments:
            writer.writerow([
                shipment.tracking_id,
                shipment.destination_country.name,
                f"{shipment.chargeable_weight:.2f}",
                f"{shipment.final_price:.2f}",
                shipment.weight_type.title(),
                shipment.created_at.strftime('%Y-%m-%d %H:%M:%S')
            ])

        output.seek(0)
        return Response(
            output.getvalue(),
            mimetype='text/csv',
            headers={'Content-disposition': f'attachment; filename=daily_report_{date}.csv'}
        )

    except Exception as e:
        flash(f'Error generating report: {str(e)}', 'error')
        return redirect(url_for('daily_reports'))

@app.route('/admin/reports/export/monthly/<int:year>/<int:month>')
@login_required
def export_monthly_report(year, month):
    if not current_user.is_admin:
        flash('Access denied. Admin privileges required.', 'error')
        return redirect(url_for('dashboard'))

    try:
        monthly_record = MonthlyRecord.query.filter_by(year=year, month=month).first()

        if not monthly_record:
            flash('No data found for the selected month.', 'error')
            return redirect(url_for('monthly_reports'))

        # Generate CSV
        output = io.StringIO()
        writer = csv.writer(output)

        # Write header
        writer.writerow(['Year', 'Month', 'Total Shipments', 'Total Revenue', 'Total Weight (kg)', 'Avg Package Value', 'Growth Rate (%)', 'Top Destination'])

        # Write data
        writer.writerow([
            monthly_record.year,
            monthly_record.month,
            monthly_record.total_shipments,
            f"{monthly_record.total_revenue:.2f}",
            f"{monthly_record.total_weight:.2f}",
            f"{monthly_record.avg_package_value:.2f}",
            f"{monthly_record.growth_rate:.2f}",
            monthly_record.top_destination or 'N/A'
        ])

        # Get detailed shipment data for the month
        month_shipments = Shipment.query.filter(
            db.func.extract('year', Shipment.created_at) == year,
            db.func.extract('month', Shipment.created_at) == month
        ).all()

        writer.writerow([])  # Empty row
        writer.writerow(['Detailed Shipment Data'])
        writer.writerow(['Tracking ID', 'Destination', 'Weight (kg)', 'Final Price', 'Weight Type', 'Created At'])

        for shipment in month_shipments:
            writer.writerow([
                shipment.tracking_id,
                shipment.destination_country.name,
                f"{shipment.chargeable_weight:.2f}",
                f"{shipment.final_price:.2f}",
                shipment.weight_type.title(),
                shipment.created_at.strftime('%Y-%m-%d %H:%M:%S')
            ])

        output.seek(0)
        return Response(
            output.getvalue(),
            mimetype='text/csv',
            headers={'Content-disposition': f'attachment; filename=monthly_report_{year}_{month:02d}.csv'}
        )

    except Exception as e:
        flash(f'Error generating report: {str(e)}', 'error')
        return redirect(url_for('monthly_reports'))

@app.route('/admin/shipments')
@login_required
def admin_shipments():
    if not current_user.is_admin:
        flash('Access denied. Admin privileges required.', 'error')
        return redirect(url_for('dashboard'))

    # Get filter parameters
    status_filter = request.args.get('status', '')
    country_filter = request.args.get('country', '')
    search_query = request.args.get('search', '')
    page = request.args.get('page', 1, type=int)
    per_page = 20

    # Build query
    query = Shipment.query.join(Client).join(Country)

    if status_filter:
        query = query.filter(Shipment.status == status_filter)

    if country_filter:
        query = query.filter(Shipment.destination_country_id == country_filter)

    if search_query:
        query = query.filter(
            db.or_(
                Shipment.tracking_id.ilike(f'%{search_query}%'),
                Client.name.ilike(f'%{search_query}%'),
                Client.email.ilike(f'%{search_query}%'),
                Shipment.sender_name.ilike(f'%{search_query}%'),
                Shipment.receiver_name.ilike(f'%{search_query}%')
            )
        )

    # Get pagination
    shipments_paginated = query.order_by(Shipment.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    # Get filter options
    countries = Country.query.filter_by(is_active=True).all()
    statuses = ['booked', 'in_transit', 'delivered', 'cancelled']

    # Calculate summary statistics
    total_shipments = query.count()
    total_revenue = query.with_entities(db.func.sum(Shipment.final_price)).scalar() or 0
    total_weight = query.with_entities(db.func.sum(Shipment.chargeable_weight)).scalar() or 0

    return render_template('admin_shipments.html',
                         shipments=shipments_paginated.items,
                         pagination=shipments_paginated,
                         countries=countries,
                         statuses=statuses,
                         status_filter=status_filter,
                         country_filter=country_filter,
                         search_query=search_query,
                         total_shipments=total_shipments,
                         total_revenue=total_revenue,
                         total_weight=total_weight)

@app.route('/admin/shipments/export')
@login_required
def export_all_shipments():
    if not current_user.is_admin:
        flash('Access denied. Admin privileges required.', 'error')
        return redirect(url_for('dashboard'))

    # Get all shipments with client and country info
    shipments = db.session.query(
        Shipment, Client, Country
    ).join(Client).join(Country).order_by(Shipment.created_at.desc()).all()

    # Generate CSV
    output = io.StringIO()
    writer = csv.writer(output)

    # Write header
    writer.writerow([
        'Tracking ID', 'Client Name', 'Client Email', 'Sender Name', 'Sender Phone',
        'Receiver Name', 'Receiver Phone', 'Destination Country', 'Weight (kg)',
        'Weight Type', 'Package Type', 'Final Price', 'Status', 'Undertaking Accepted',
        'Special Instructions', 'Created At'
    ])

    # Write data
    for shipment, client, country in shipments:
        writer.writerow([
            shipment.tracking_id,
            client.name,
            client.email,
            shipment.sender_name,
            shipment.sender_phone,
            shipment.receiver_name,
            shipment.receiver_phone,
            country.name,
            f"{shipment.chargeable_weight:.2f}",
            shipment.weight_type.title(),
            'Documents' if shipment.document_type == 'docs' else 'Non-Documents',
            f"{shipment.final_price:.2f}",
            shipment.status.title(),
            'Yes' if shipment.undertaking_accepted else 'No',
            shipment.undertaking_text or '',
            shipment.created_at.strftime('%Y-%m-%d %H:%M:%S')
        ])

    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-disposition': 'attachment; filename=all_shipments.csv'}
    )

@app.route('/admin/cleanup-duplicates')
@login_required
def cleanup_duplicates():
    if not current_user.is_admin:
        flash('Access denied. Admin privileges required.', 'error')
        return redirect(url_for('dashboard'))

    cleanup_duplicate_tracking_ids()
    flash('Duplicate tracking IDs have been cleaned up!', 'success')
    return redirect(url_for('admin_shipments'))

# Helper Functions
def calculate_pricing(country_id, length, width, height, weight, weight_type):
    try:
        country = Country.query.get(country_id)
        if not country:
            return {'error': 'Invalid country selected.'}

        volumetric_weight = (length * width * height) / 5000
        chargeable_weight = weight if weight_type == 'actual' else volumetric_weight
        chargeable_weight = max(weight, volumetric_weight)  # Always use the higher weight

        # Find appropriate pricing tier
        pricing_tier = PricingTier.query.filter(
            PricingTier.country_id == country_id,
            PricingTier.min_weight <= chargeable_weight,
            PricingTier.max_weight >= chargeable_weight,
            PricingTier.is_active == True
        ).first()

        if not pricing_tier:
            return {'error': 'No pricing tier found for this weight range.'}

        base_price = (chargeable_weight * pricing_tier.price_per_kg) + pricing_tier.base_fee
        gst_amount = base_price * 0.18  # 18% GST
        final_price = base_price + gst_amount

        return {
            'volumetric_weight': round(volumetric_weight, 2),
            'chargeable_weight': round(chargeable_weight, 2),
            'base_price': round(base_price, 2),
            'gst_amount': round(gst_amount, 2),
            'final_price': round(final_price, 2),
            'currency': country.currency
        }

    except Exception as e:
        return {'error': f'Error calculating pricing: {str(e)}'}

def generate_tracking_id():
    """Generate tracking ID in format: EX-MMM-DD-NNN"""
    now = datetime.now()

    # Get month abbreviation (e.g., SEP, OCT, NOV, DEC)
    month_abbr = now.strftime('%b').upper()

    # Get day of month
    day = now.strftime('%d')

    # Find the highest sequential number for today
    today_start = datetime.combine(now.date(), datetime.min.time())
    today_end = datetime.combine(now.date(), datetime.max.time())

    # Get existing tracking IDs for today with proper pattern
    existing_shipments = Shipment.query.filter(
        Shipment.created_at >= today_start,
        Shipment.created_at <= today_end,
        Shipment.tracking_id.like(f'EX-{month_abbr}-{day}-%')
    ).all()

    # Find the highest sequential number used today
    max_sequential = 0
    for shipment in existing_shipments:
        tracking_parts = shipment.tracking_id.split('-')
        if len(tracking_parts) == 4:
            try:
                seq_num = int(tracking_parts[3])
                max_sequential = max(max_sequential, seq_num)
            except (ValueError, IndexError):
                continue

    # Generate next sequential number
    sequential_num = max_sequential + 1
    sequential_str = f"{sequential_num:03d}"

    tracking_id = f"EX-{month_abbr}-{day}-{sequential_str}"

    # Double-check that this tracking ID doesn't already exist
    existing_count = Shipment.query.filter_by(tracking_id=tracking_id).count()
    if existing_count > 0:
        # If it exists, try incrementing until we find a unique one
        while existing_count > 0:
            sequential_num += 1
            sequential_str = f"{sequential_num:03d}"
            tracking_id = f"EX-{month_abbr}-{day}-{sequential_str}"
            existing_count = Shipment.query.filter_by(tracking_id=tracking_id).count()

    # Debug: Print information about the generation
    print(f"DEBUG: Generated tracking ID: {tracking_id}")
    print(f"DEBUG: Max sequential found: {max_sequential}")
    print(f"DEBUG: Existing shipments today: {len(existing_shipments)}")

    return tracking_id

def update_daily_records():
    """Update daily records for today and yesterday if needed"""
    today = datetime.now().date()

    # Check if today's record exists
    daily_record = DailyRecord.query.filter_by(date=today).first()
    if not daily_record:
        daily_record = DailyRecord(date=today)
        db.session.add(daily_record)

    # Get today's shipments
    today_shipments = Shipment.query.filter(
        db.func.date(Shipment.created_at) == today
    ).all()

    # Calculate statistics
    total_shipments = len(today_shipments)
    total_revenue = sum(s.final_price for s in today_shipments)
    total_weight = sum(s.chargeable_weight for s in today_shipments)

    # Find top destination
    destination_counts = {}
    for shipment in today_shipments:
        dest = shipment.destination_country.name
        destination_counts[dest] = destination_counts.get(dest, 0) + 1

    top_destination = max(destination_counts.items(), key=lambda x: x[1])[0] if destination_counts else None
    avg_package_value = total_revenue / total_shipments if total_shipments > 0 else 0

    # Update record
    daily_record.total_shipments = total_shipments
    daily_record.total_revenue = total_revenue
    daily_record.total_weight = total_weight
    daily_record.avg_package_value = avg_package_value
    daily_record.top_destination = top_destination

    db.session.commit()
    return daily_record

def update_monthly_records():
    """Update monthly records for current month"""
    now = datetime.now()
    current_year = now.year
    current_month = now.month

    # Check if current month's record exists
    monthly_record = MonthlyRecord.query.filter_by(year=current_year, month=current_month).first()
    if not monthly_record:
        monthly_record = MonthlyRecord(year=current_year, month=current_month)
        db.session.add(monthly_record)

    # Get current month's shipments
    current_month_shipments = Shipment.query.filter(
        db.func.extract('year', Shipment.created_at) == current_year,
        db.func.extract('month', Shipment.created_at) == current_month
    ).all()

    # Calculate statistics
    total_shipments = len(current_month_shipments)
    total_revenue = sum(s.final_price for s in current_month_shipments)
    total_weight = sum(s.chargeable_weight for s in current_month_shipments)

    # Find top destination
    destination_counts = {}
    for shipment in current_month_shipments:
        dest = shipment.destination_country.name
        destination_counts[dest] = destination_counts.get(dest, 0) + 1

    top_destination = max(destination_counts.items(), key=lambda x: x[1])[0] if destination_counts else None
    avg_package_value = total_revenue / total_shipments if total_shipments > 0 else 0

    # Calculate growth rate (compared to previous month)
    prev_month = current_month - 1 if current_month > 1 else 12
    prev_year = current_year if current_month > 1 else current_year - 1

    prev_record = MonthlyRecord.query.filter_by(year=prev_year, month=prev_month).first()
    if prev_record and prev_record.total_revenue > 0:
        growth_rate = ((total_revenue - prev_record.total_revenue) / prev_record.total_revenue) * 100
    else:
        growth_rate = 0

    # Update record
    monthly_record.total_shipments = total_shipments
    monthly_record.total_revenue = total_revenue
    monthly_record.total_weight = total_weight
    monthly_record.avg_package_value = avg_package_value
    monthly_record.growth_rate = growth_rate
    monthly_record.top_destination = top_destination

    db.session.commit()
    return monthly_record

def generate_shipment_analytics(shipment_id):
    """Generate analytics data for a shipment"""
    analytics = ShipmentAnalytics(shipment_id=shipment_id)
    db.session.add(analytics)
    db.session.commit()
    return analytics

def cleanup_duplicate_tracking_ids():
    """Clean up duplicate tracking IDs in the database"""
    from sqlalchemy import text

    # Find all duplicate tracking IDs
    duplicates = db.session.execute(
        text("""
        SELECT tracking_id, COUNT(*) as count
        FROM shipment
        GROUP BY tracking_id
        HAVING COUNT(*) > 1
        """)
    ).fetchall()

    if duplicates:
        print(f"Found {len(duplicates)} duplicate tracking IDs:")
        for tracking_id, count in duplicates:
            print(f"  {tracking_id}: {count} occurrences")

        # Remove duplicates, keeping only the first occurrence
        for tracking_id, count in duplicates:
            shipments = Shipment.query.filter_by(tracking_id=tracking_id).order_by(Shipment.id).all()
            # Keep the first one, delete the rest
            for shipment in shipments[1:]:
                print(f"  Deleting duplicate shipment ID {shipment.id} with tracking ID {tracking_id}")
                db.session.delete(shipment)

        db.session.commit()
        print("Duplicate cleanup completed!")
    else:
        print("No duplicate tracking IDs found.")

def load_sample_pricing_data():
    """Load sample pricing data from CSV file"""
    try:
        csv_path = os.path.join(os.path.dirname(__file__), 'sample_pricing.csv')

        if not os.path.exists(csv_path):
            print("Sample pricing CSV file not found!")
            return

        with open(csv_path, 'r') as csvfile:
            reader = csv.DictReader(csvfile)
            success_count = 0
            error_count = 0

            for row in reader:
                try:
                    # Get or create country
                    country = Country.query.filter_by(code=row['country_code'].upper()).first()
                    if not country:
                        country = Country(
                            name=row['country_name'],
                            code=row['country_code'].upper(),
                            currency=row['currency'].upper(),
                            is_active=True
                        )
                        db.session.add(country)
                        db.session.flush()  # Get the country ID

                    # Create pricing tier
                    pricing_tier = PricingTier(
                        country_id=country.id,
                        min_weight=float(row['min_weight']),
                        max_weight=float(row['max_weight']),
                        price_per_kg=float(row['price_per_kg']),
                        base_fee=float(row.get('base_fee', 0)),
                        is_active=True
                    )
                    db.session.add(pricing_tier)
                    success_count += 1

                except Exception as e:
                    print(f"Error processing row {row}: {e}")
                    error_count += 1

            db.session.commit()
            print(f"Sample pricing data loaded successfully! {success_count} records added, {error_count} errors.")

    except Exception as e:
        print(f"Error loading sample pricing data: {str(e)}")
        db.session.rollback()

# Initialize database
def create_tables():
    db.create_all()

    # Create default admin user if not exists
    admin = Client.query.filter_by(email='admin@login.com').first()
    if not admin:
        admin = Client(
            name='Administrator',
            email='admin@login.com',
            phone='0000000000',
            cnic='0000000000000',
            address='Admin Office',
            postal_code='00000',
            is_admin=True
        )
        admin.set_password('admin123')
        db.session.add(admin)
        db.session.commit()

# Create tables when app starts
with app.app_context():
    create_tables()

    # Clean up any duplicate tracking IDs
    cleanup_duplicate_tracking_ids()

    # Load sample pricing data if no countries exist
    if Country.query.count() == 0:
        load_sample_pricing_data()

if __name__ == '__main__':
    app.run(debug=True)
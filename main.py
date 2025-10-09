# Updated to force template reload
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
from reportlab.graphics.barcode import code128
from reportlab.graphics.shapes import Drawing
from reportlab.graphics import renderPDF
import csv
import random

app = Flask(__name__)

# Load configuration from environment variables
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL') or f'sqlite:///{os.path.join(os.getcwd(), "instance", "courier.db")}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.environ.get('UPLOAD_FOLDER', 'uploads')
app.config['MAX_CONTENT_LENGTH'] = int(os.environ.get('MAX_CONTENT_LENGTH', '16777216'))  # 16MB max file size

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Create upload directory if it doesn't exist
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

@login_manager.user_loader
def load_user(user_id):
    return Branch.query.get(int(user_id))

# Database Models
class Branch(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    branch_code = db.Column(db.String(20), unique=True, nullable=False)
    address = db.Column(db.Text, nullable=False)
    postal_code = db.Column(db.String(20), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)
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
    barcode = db.Column(db.String(20), unique=True, nullable=False)
    client_id = db.Column(db.Integer, db.ForeignKey('branch.id'), nullable=False)  # Changed from branch_id to client_id to match existing DB

    # Insurance fields (from existing database)
    insurance_amount = db.Column(db.Float, default=0)
    insurance_selected = db.Column(db.Boolean, default=False)

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
    final_price_pkr = db.Column(db.Float, nullable=False)  # Final price in PKR

    # Status
    status = db.Column(db.String(20), default='booked')  # booked, in_transit, delivered, cancelled

    # Undertaking
    undertaking_accepted = db.Column(db.Boolean, default=False)
    undertaking_text = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    branch = db.relationship('Branch', backref=db.backref('shipments', lazy=True))
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

class BranchRegistrationForm(FlaskForm):
    name = StringField('Branch Name', validators=[DataRequired(), Length(min=2, max=100)])
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired(), Length(min=6)])
    phone = StringField('Phone', validators=[DataRequired(), Length(min=10, max=20)])
    branch_code = StringField('Branch Code', validators=[DataRequired(), Length(min=2, max=20)])
    address = TextAreaField('Address', validators=[DataRequired()])
    postal_code = StringField('Postal Code', validators=[DataRequired()])

    def validate_email(self, email):
        branch = Branch.query.filter_by(email=email.data).first()
        if branch:
            raise ValidationError('Email already registered.')

    def validate_branch_code(self, branch_code):
        branch = Branch.query.filter_by(branch_code=branch_code.data).first()
        if branch:
            raise ValidationError('Branch code already registered.')


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
        branch = Branch.query.filter_by(email=form.email.data).first()
        if branch and branch.check_password(form.password.data):
            login_user(branch)
            flash('Logged in successfully!', 'success')
            return redirect(url_for('dashboard'))
        flash('Invalid email or password.', 'error')

    return render_template('login.html', form=form)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    form = BranchRegistrationForm()
    if form.validate_on_submit():
        branch = Branch(
            name=form.name.data,
            email=form.email.data,
            phone=form.phone.data,
            branch_code=form.branch_code.data,
            address=form.address.data,
            postal_code=form.postal_code.data,
            is_admin=False,
            is_active=True
        )
        branch.set_password(form.password.data)
        db.session.add(branch)
        db.session.commit()

        flash('Branch registration successful! Please log in.', 'success')
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

        # Generate tracking ID and barcode
        tracking_id = generate_tracking_id()

        # Calculate PKR price
        final_price_pkr = convert_to_pkr(pricing_data['final_price'], pricing_data['currency'])

        # Create shipment first (without barcode)
        shipment = Shipment(
            tracking_id=tracking_id,
            barcode='',  # Will be set after creation
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
            final_price_pkr=final_price_pkr,
            undertaking_accepted=form.undertaking_accepted.data,
            undertaking_text=form.undertaking_text.data or None
        )

        db.session.add(shipment)
        db.session.commit()

        # Generate comprehensive barcode with shipment data
        barcode = generate_barcode_with_shipment_data(shipment)
        db.session.commit()  # Commit the barcode update

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

@app.route('/shipment/<int:shipment_id>/update-status', methods=['POST'])
@login_required
def update_shipment_status(shipment_id):
    """Update shipment status"""
    shipment = Shipment.query.get_or_404(shipment_id)

    # Check if user owns the shipment or is admin
    if shipment.client_id != current_user.id and not current_user.is_admin:
        return jsonify({'error': 'Access denied.'}), 403

    new_status = request.json.get('status')
    if not new_status:
        return jsonify({'error': 'Status is required.'}), 400

    # Valid status options
    valid_statuses = ['booked', 'in_transit', 'out_for_delivery', 'delivered', 'cancelled']
    if new_status not in valid_statuses:
        return jsonify({'error': 'Invalid status.'}), 400

    try:
        old_status = shipment.status
        shipment.status = new_status
        db.session.commit()

        # Update analytics if status changed to delivered
        if new_status == 'delivered' and old_status != 'delivered':
            analytics = ShipmentAnalytics.query.filter_by(shipment_id=shipment_id).first()
            if analytics:
                from datetime import datetime
                analytics.processing_time = (datetime.utcnow() - shipment.created_at).total_seconds() / 3600
                analytics.delivery_status = 'delivered'
                db.session.commit()

        return jsonify({
            'success': True,
            'message': f'Shipment status updated to {new_status.title()}',
            'new_status': new_status
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to update status: {str(e)}'}), 500


@app.route('/search-shipments', methods=['GET', 'POST'])
@login_required
def search_shipments():
    """Search shipments with filters and status update functionality"""
    search_query = request.args.get('search', '')
    status_filter = request.args.get('status', '')
    country_filter = request.args.get('country', '')
    page = request.args.get('page', 1, type=int)
    per_page = 20

    # Build query based on user role
    if current_user.is_admin:
        query = Shipment.query.join(Branch).join(Country)
    else:
        query = Shipment.query.join(Country).filter(Shipment.client_id == current_user.id)

    # Apply filters
    if search_query:
        query = query.filter(
            db.or_(
                Shipment.tracking_id.ilike(f'%{search_query}%'),
                Branch.name.ilike(f'%{search_query}%'),
                Shipment.sender_name.ilike(f'%{search_query}%'),
                Shipment.receiver_name.ilike(f'%{search_query}%')
            )
        )

    if status_filter:
        query = query.filter(Shipment.status == status_filter)

    if country_filter:
        query = query.filter(Shipment.destination_country_id == country_filter)

    # Get pagination
    shipments_paginated = query.order_by(Shipment.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    # Get filter options
    countries = Country.query.filter_by(is_active=True).all()
    statuses = ['booked', 'in_transit', 'out_for_delivery', 'delivered', 'cancelled']

    # Calculate summary statistics
    total_shipments = query.count()
    total_revenue = query.with_entities(db.func.sum(Shipment.final_price)).scalar() or 0
    total_weight = query.with_entities(db.func.sum(Shipment.chargeable_weight)).scalar() or 0

    return render_template('search_shipments.html',
                         shipments=shipments_paginated.items,
                         pagination=shipments_paginated,
                         countries=countries,
                         statuses=statuses,
                         search_query=search_query,
                         status_filter=status_filter,
                         country_filter=country_filter,
                         total_shipments=total_shipments,
                         total_revenue=total_revenue,
                         total_weight=total_weight)


@app.route('/shipment/<int:shipment_id>/book-similar', methods=['GET', 'POST'])
@login_required
def book_similar_shipment(shipment_id):
    """Book a new shipment with same sender information"""
    # Get the original shipment to copy sender info
    original_shipment = Shipment.query.get_or_404(shipment_id)

    # Check if user owns the shipment or is admin
    if original_shipment.client_id != current_user.id and not current_user.is_admin:
        flash('Access denied.', 'error')
        return redirect(url_for('dashboard'))

    form = ShipmentForm()
    countries = Country.query.filter_by(is_active=True).all()
    form.destination_country.choices = [(str(c.id), f"{c.name} ({c.currency})") for c in countries]

    if request.method == 'GET':
        # Pre-fill form with sender information from original shipment
        form.sender_name.data = original_shipment.sender_name
        form.sender_phone.data = original_shipment.sender_phone
        form.sender_cnic.data = original_shipment.sender_cnic
        form.sender_address.data = original_shipment.sender_address
        form.sender_postal_code.data = original_shipment.sender_postal_code

        # Set default destination to same as original shipment
        form.destination_country.data = str(original_shipment.destination_country_id)

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

        # Generate tracking ID and barcode
        tracking_id = generate_tracking_id()

        # Calculate PKR price
        final_price_pkr = convert_to_pkr(pricing_data['final_price'], pricing_data['currency'])

        # Create new shipment with same sender info but new receiver/package info
        shipment = Shipment(
            tracking_id=tracking_id,
            barcode='',  # Will be set after creation
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
            final_price_pkr=final_price_pkr,
            undertaking_accepted=form.undertaking_accepted.data,
            undertaking_text=form.undertaking_text.data or None
        )

        db.session.add(shipment)
        db.session.commit()

        # Generate comprehensive barcode with shipment data
        barcode = generate_barcode_with_shipment_data(shipment)
        db.session.commit()  # Commit the barcode update

        # Generate analytics for the shipment
        generate_shipment_analytics(shipment.id)

        # Update daily and monthly records
        update_daily_records()
        update_monthly_records()

        flash(f'Shipment booked successfully! Tracking ID: {tracking_id}', 'success')
        return redirect(url_for('shipment_slip', shipment_id=shipment.id))

    return render_template('book_shipment.html', form=form, prefilled_sender=True)


@app.route('/shipment/<int:shipment_id>/print-undertaking')
@login_required
def print_undertaking(shipment_id):
    """Generate and return undertaking document with shipment details"""
    shipment = Shipment.query.get_or_404(shipment_id)
    if shipment.client_id != current_user.id and not current_user.is_admin:
        flash('Access denied.', 'error')
        return redirect(url_for('dashboard'))

    # Generate undertaking PDF with shipment details
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
    content.append(Paragraph('UNDERTAKING / DECLARATION', styles['Heading2']))
    content.append(Paragraph(f'Shipment ID: {shipment.tracking_id}', styles['Heading3']))
    content.append(Spacer(1, 20))

    # Create undertaking content using simple text with proper formatting
    content.append(Spacer(1, 20))

    # Title
    title_style = ParagraphStyle(
        'UndertakingTitle',
        parent=styles['Heading1'],
        fontSize=18,
        spaceAfter=20,
        alignment=1  # Center alignment
    )
    content.append(Paragraph('DECLARATION AND UNDERTAKING', title_style))
    content.append(Paragraph(f'Shipment ID: {shipment.tracking_id}', styles['Heading3']))
    content.append(Spacer(1, 20))

    # Main declaration text
    declaration_style = ParagraphStyle(
        'DeclarationText',
        parent=styles['Normal'],
        fontSize=11,
        leading=14,
        spaceAfter=12
    )

    content.append(Paragraph(
        f'I, <b>{shipment.sender_name}</b>, holder of CNIC No. <b>{shipment.sender_cnic}</b>, residing at <b>{shipment.sender_address}</b>, do hereby solemnly declare and undertake as follows:',
        declaration_style
    ))

    content.append(Spacer(1, 15))

    # Numbered points
    points = [
        f"That I am the sender of the shipment with Tracking ID <b>{shipment.tracking_id}</b> being sent to <b>{shipment.receiver_name}</b> at <b>{shipment.receiver_address}</b>.",
        "That the contents of the above-mentioned shipment are as declared and do not include any prohibited, illegal, or dangerous items.",
        "That I accept full responsibility for the contents of the shipment and any consequences arising from any misdeclaration.",
        "That I have read and understood all the terms and conditions of PICS Courier Services and agree to abide by them.",
        "That I authorize PICS Courier Services to inspect the shipment if required by law or for security purposes.",
        "That I understand that PICS Courier Services shall not be liable for any loss or damage to the shipment beyond the declared value.",
        "That I declare that the weight and dimensions provided are accurate and I understand that incorrect information may result in additional charges.",
        "That I understand that prohibited items will be confiscated and may result in legal action."
    ]

    for i, point in enumerate(points, 1):
        content.append(Paragraph(f"{i}. {point}", declaration_style))

    content.append(Spacer(1, 20))

    # Information sections
    section_style = ParagraphStyle(
        'SectionHeader',
        parent=styles['Normal'],
        fontSize=12,
        fontName='Helvetica-Bold',
        spaceAfter=8
    )

    info_style = ParagraphStyle(
        'InfoText',
        parent=styles['Normal'],
        fontSize=10,
        leading=12,
        spaceAfter=6
    )

    # Sender Information
    content.append(Paragraph('<b>Sender Information:</b>', section_style))
    sender_info = [
        f"Name: {shipment.sender_name}",
        f"CNIC: {shipment.sender_cnic}",
        f"Phone: {shipment.sender_phone}",
        f"Address: {shipment.sender_address}"
    ]
    for info in sender_info:
        content.append(Paragraph(info, info_style))

    content.append(Spacer(1, 15))

    # Receiver Information
    content.append(Paragraph('<b>Receiver Information:</b>', section_style))
    receiver_info = [
        f"Name: {shipment.receiver_name}",
        f"CNIC: {shipment.receiver_cnic}",
        f"Phone: {shipment.receiver_phone}",
        f"Address: {shipment.receiver_address}"
    ]
    for info in receiver_info:
        content.append(Paragraph(info, info_style))

    content.append(Spacer(1, 15))

    # Package Information
    content.append(Paragraph('<b>Package Information:</b>', section_style))
    package_info = [
        f"Weight: {shipment.chargeable_weight} kg",
        f"Dimensions: {shipment.length} × {shipment.width} × {shipment.height} cm",
        f"Destination: {shipment.destination_country.name}",
        f"Value: {shipment.destination_country.currency} {shipment.final_price}"
    ]
    for info in package_info:
        content.append(Paragraph(info, info_style))

    content.append(Spacer(1, 20))

    # Final declaration
    content.append(Paragraph(
        'I hereby declare that the above information is true and correct to the best of my knowledge and belief.',
        declaration_style
    ))

    content.append(Spacer(1, 20))

    # Date and signature
    date_style = ParagraphStyle(
        'DateStyle',
        parent=styles['Normal'],
        fontSize=11,
        alignment=1,  # Center alignment
        spaceAfter=10
    )

    signature_style = ParagraphStyle(
        'SignatureStyle',
        parent=styles['Normal'],
        fontSize=11,
        alignment=1,  # Center alignment
        spaceAfter=30
    )

    content.append(Paragraph(f'<b>Date: {shipment.created_at.strftime("%Y-%m-%d")}</b>', date_style))
    content.append(Paragraph('___________________________', signature_style))
    content.append(Paragraph("<b>Sender's Signature</b>", signature_style))

    # Footer
    content.append(Paragraph(f'Date: {shipment.created_at.strftime("%Y-%m-%d %H:%M")}', styles['Normal']))
    content.append(Paragraph('Thank you for choosing PICS!', styles['Italic']))

    doc.build(content)

    buffer.seek(0)
    return send_file(
        buffer,
        as_attachment=True,
        download_name=f'undertaking-{shipment.tracking_id}.pdf',
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
    total_branches = Branch.query.filter_by(is_admin=False).count()
    active_countries = Country.query.filter_by(is_active=True).count()
    total_revenue = db.session.query(db.func.sum(Shipment.final_price)).scalar() or 0

    return render_template('admin.html',
                         total_shipments=total_shipments,
                         total_branches=total_branches,
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
    query = Shipment.query.join(Branch).join(Country)

    if status_filter:
        query = query.filter(Shipment.status == status_filter)

    if country_filter:
        query = query.filter(Shipment.destination_country_id == country_filter)

    if search_query:
        query = query.filter(
            db.or_(
                Shipment.tracking_id.ilike(f'%{search_query}%'),
                Branch.name.ilike(f'%{search_query}%'),
                Branch.email.ilike(f'%{search_query}%'),
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

    # Get all shipments with branch and country info
    shipments = db.session.query(
        Shipment, Branch, Country
    ).join(Branch).join(Country).order_by(Shipment.created_at.desc()).all()

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
    for shipment, branch, country in shipments:
        writer.writerow([
            shipment.tracking_id,
            branch.name,
            branch.email,
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










@app.route('/parcel-management')
@login_required
def parcel_management():
    """Enhanced parcel management for branch users"""
    # Get filter parameters
    search_query = request.args.get('search', '')
    status_filter = request.args.get('status', '')
    country_filter = request.args.get('country', '')
    page = request.args.get('page', 1, type=int)
    per_page = 20

    # Build query for current user's shipments
    query = Shipment.query.filter_by(client_id=current_user.id).join(Country)

    # Apply filters
    if search_query:
        query = query.filter(
            db.or_(
                Shipment.tracking_id.ilike(f'%{search_query}%'),
                Shipment.sender_name.ilike(f'%{search_query}%'),
                Shipment.receiver_name.ilike(f'%{search_query}%'),
                Shipment.sender_phone.ilike(f'%{search_query}%')
            )
        )

    if status_filter:
        query = query.filter(Shipment.status == status_filter)

    if country_filter:
        query = query.filter(Shipment.destination_country_id == country_filter)

    # Get pagination
    shipments_paginated = query.order_by(Shipment.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    # Get filter options
    countries = Country.query.filter_by(is_active=True).all()
    statuses = ['booked', 'in_transit', 'out_for_delivery', 'delivered', 'cancelled']

    # Calculate summary statistics
    total_shipments = Shipment.query.filter_by(client_id=current_user.id).count()
    total_revenue = db.session.query(db.func.sum(Shipment.final_price)).filter_by(client_id=current_user.id).scalar() or 0
    total_weight = db.session.query(db.func.sum(Shipment.chargeable_weight)).filter_by(client_id=current_user.id).scalar() or 0

    # Status breakdown
    status_counts = {}
    for status in statuses:
        status_counts[status] = Shipment.query.filter_by(client_id=current_user.id, status=status).count()

    return render_template('parcel_management.html',
                         shipments=shipments_paginated.items,
                         pagination=shipments_paginated,
                         countries=countries,
                         statuses=statuses,
                         search_query=search_query,
                         status_filter=status_filter,
                         country_filter=country_filter,
                         total_shipments=total_shipments,
                         total_revenue=total_revenue,
                         total_weight=total_weight,
                         status_counts=status_counts)



@app.route('/admin/parcel-management')
@login_required
def admin_parcel_management():
    if not current_user.is_admin:
        flash('Access denied. Admin privileges required.', 'error')
        return redirect(url_for('dashboard'))

    # Get filter parameters
    search_query = request.args.get('search', '')
    status_filter = request.args.get('status', '')
    country_filter = request.args.get('country', '')
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)

    # Build query
    query = db.session.query(
        Shipment, Branch, Country
    ).join(Branch).join(Country)

    # Apply filters
    if search_query:
        query = query.filter(
            db.or_(
                Shipment.tracking_id.ilike(f'%{search_query}%'),
                Branch.name.ilike(f'%{search_query}%'),
                Shipment.sender_name.ilike(f'%{search_query}%'),
                Shipment.sender_phone.ilike(f'%{search_query}%')
            )
        )

    if status_filter:
        query = query.filter(Shipment.status == status_filter)

    if country_filter:
        query = query.filter(Shipment.destination_country_id == country_filter)

    if date_from:
        query = query.filter(db.func.date(Shipment.created_at) >= date_from)

    if date_to:
        query = query.filter(db.func.date(Shipment.created_at) <= date_to)

    # Get pagination
    shipments_paginated = query.order_by(Shipment.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    # Format data for template
    parcels = []
    for shipment, branch, country in shipments_paginated.items:
        parcels.append({
            'id': shipment.id,
            'tracking_id': shipment.tracking_id,
            'barcode': shipment.barcode,
            'client_name': branch.name,
            'sender_phone': shipment.sender_phone,
            'destination_country': country.name,
            'chargeable_weight': shipment.chargeable_weight,
            'weight_type': shipment.weight_type,
            'final_price': shipment.final_price,
            'final_price_pkr': shipment.final_price_pkr,
            'status': shipment.status,
            'created_at': shipment.created_at,
            'created_date': shipment.created_at.strftime('%Y-%m-%d'),
            'created_time': shipment.created_at.strftime('%H:%M')
        })

    # Calculate statistics
    total_parcels = query.count()
    in_transit_count = query.filter(Shipment.status == 'in_transit').count()
    delivered_count = query.filter(Shipment.status == 'delivered').count()
    total_weight = query.with_entities(db.func.sum(Shipment.chargeable_weight)).scalar() or 0

    # Get countries for filter dropdown
    countries = Country.query.filter_by(is_active=True).all()

    return render_template('admin_parcel_management.html',
                         parcels=parcels,
                         pagination=shipments_paginated,
                         countries=countries,
                         search_query=search_query,
                         status_filter=status_filter,
                         country_filter=country_filter,
                         date_from=date_from,
                         date_to=date_to,
                         total_parcels=total_parcels,
                         in_transit_count=in_transit_count,
                         delivered_count=delivered_count,
                         total_weight=total_weight)

@app.route('/api/parcels/filter')
@login_required
def api_filter_parcels():
    if not current_user.is_admin:
        return jsonify({'error': 'Access denied. Admin privileges required.'}), 403

    # Get filter parameters
    search_query = request.args.get('search', '')
    status_filter = request.args.get('status', '')
    country_filter = request.args.get('country', '')
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)

    # Build query
    query = db.session.query(
        Shipment, Branch, Country
    ).join(Branch).join(Country)

    # Apply filters
    if search_query:
        query = query.filter(
            db.or_(
                Shipment.tracking_id.ilike(f'%{search_query}%'),
                Branch.name.ilike(f'%{search_query}%'),
                Shipment.sender_name.ilike(f'%{search_query}%'),
                Shipment.sender_phone.ilike(f'%{search_query}%')
            )
        )

    if status_filter:
        query = query.filter(Shipment.status == status_filter)

    if country_filter:
        query = query.filter(Shipment.destination_country_id == country_filter)

    if date_from:
        query = query.filter(db.func.date(Shipment.created_at) >= date_from)

    if date_to:
        query = query.filter(db.func.date(Shipment.created_at) <= date_to)

    # Get pagination
    shipments_paginated = query.order_by(Shipment.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    # Format data for API response
    parcels = []
    for shipment, branch, country in shipments_paginated.items:
        parcels.append({
            'id': shipment.id,
            'tracking_id': shipment.tracking_id,
            'barcode': shipment.barcode,
            'client_name': branch.name,
            'sender_phone': shipment.sender_phone,
            'destination_country': country.name,
            'chargeable_weight': float(shipment.chargeable_weight),
            'weight_type': shipment.weight_type,
            'final_price': float(shipment.final_price),
            'final_price_pkr': float(shipment.final_price_pkr),
            'status': shipment.status,
            'created_date': shipment.created_at.strftime('%Y-%m-%d'),
            'created_time': shipment.created_at.strftime('%H:%M')
        })

    # Calculate statistics
    total_parcels = query.count()
    in_transit_count = query.filter(Shipment.status == 'in_transit').count()
    delivered_count = query.filter(Shipment.status == 'delivered').count()
    total_weight = float(query.with_entities(db.func.sum(Shipment.chargeable_weight)).scalar() or 0)

    return jsonify({
        'parcels': parcels,
        'pagination': {
            'page': page,
            'per_page': per_page,
            'total': total_parcels,
            'pages': shipments_paginated.pages,
            'has_next': shipments_paginated.has_next,
            'has_prev': shipments_paginated.has_prev
        },
        'statistics': {
            'total_parcels': total_parcels,
            'in_transit_count': in_transit_count,
            'delivered_count': delivered_count,
            'total_weight': round(total_weight, 2)
        }
    })

@app.route('/api/parcels/bulk-update', methods=['POST'])
@login_required
def bulk_update_parcels():
    if not current_user.is_admin:
        return jsonify({'error': 'Access denied. Admin privileges required.'}), 403

    data = request.get_json()
    if not data or 'parcel_ids' not in data or 'action' not in data:
        return jsonify({'error': 'Invalid data provided.'}), 400

    parcel_ids = data['parcel_ids']
    action = data['action']

    # Validate action
    valid_actions = ['mark_in_transit', 'mark_out_for_delivery', 'mark_delivered', 'cancel']
    if action not in valid_actions:
        return jsonify({'error': 'Invalid action.'}), 400

    # Map actions to status
    status_map = {
        'mark_in_transit': 'in_transit',
        'mark_out_for_delivery': 'out_for_delivery',
        'mark_delivered': 'delivered',
        'cancel': 'cancelled'
    }

    new_status = status_map[action]

    try:
        # Update all selected parcels
        updated_count = Shipment.query.filter(
            Shipment.id.in_(parcel_ids)
        ).update({
            'status': new_status
        }, synchronize_session=False)

        db.session.commit()

        return jsonify({
            'success': True,
            'message': f'Successfully updated {updated_count} parcels to {new_status}.',
            'updated_count': updated_count
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to update parcels: {str(e)}'}), 500

@app.route('/api/barcode/decode/<barcode>')
@login_required
def decode_barcode_api(barcode):
    """Decode barcode and return shipment information"""
    barcode_info = decode_barcode(barcode)

    if not barcode_info:
        return jsonify({'error': 'Invalid barcode format'}), 400

    # Find shipment by barcode
    shipment = Shipment.query.filter_by(barcode=barcode).first()

    if not shipment:
        return jsonify({
            'error': 'Shipment not found',
            'barcode_info': barcode_info
        }), 404

    # Return comprehensive information
    return jsonify({
        'success': True,
        'barcode_info': barcode_info,
        'shipment': {
            'id': shipment.id,
            'tracking_id': shipment.tracking_id,
            'sender_name': shipment.sender_name,
            'sender_phone': shipment.sender_phone,
            'receiver_name': shipment.receiver_name,
            'receiver_phone': shipment.receiver_phone,
            'destination': shipment.destination_country.name,
            'weight': float(shipment.chargeable_weight),
            'status': shipment.status,
            'created_at': shipment.created_at.strftime('%Y-%m-%d %H:%M:%S')
        }
    })

@app.route('/barcode-info/<barcode>')
@login_required
def barcode_info_page(barcode):
    """Display barcode information page"""
    barcode_info = decode_barcode(barcode)
    shipment = Shipment.query.filter_by(barcode=barcode).first()

    if not shipment:
        flash('Shipment not found for this barcode.', 'error')
        return redirect(url_for('dashboard'))

    return render_template('barcode_info.html',
                         barcode=barcode,
                         barcode_info=barcode_info,
                         shipment=shipment)

@app.route('/api/barcode/validate/<barcode>')
@login_required
def validate_barcode_api(barcode):
    """Validate barcode and return basic information"""
    barcode_info = decode_barcode(barcode)

    if not barcode_info:
        return jsonify({
            'valid': False,
            'error': 'Invalid barcode format'
        })

    # Find shipment by barcode
    shipment = Shipment.query.filter_by(barcode=barcode).first()

    return jsonify({
        'valid': True,
        'barcode_info': barcode_info,
        'shipment_exists': shipment is not None,
        'tracking_id': shipment.tracking_id if shipment else None,
        'status': shipment.status if shipment else None
    })

@app.route('/api/parcels/export')
@login_required
def export_filtered_parcels():
    if not current_user.is_admin:
        return jsonify({'error': 'Access denied. Admin privileges required.'}), 403

    # Get filter parameters
    search_query = request.args.get('search', '')
    status_filter = request.args.get('status', '')
    country_filter = request.args.get('country', '')
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')

    # Build query
    query = db.session.query(
        Shipment, Branch, Country
    ).join(Branch).join(Country)

    # Apply filters
    if search_query:
        query = query.filter(
            db.or_(
                Shipment.tracking_id.ilike(f'%{search_query}%'),
                Branch.name.ilike(f'%{search_query}%'),
                Shipment.sender_name.ilike(f'%{search_query}%'),
                Shipment.sender_phone.ilike(f'%{search_query}%')
            )
        )

    if status_filter:
        query = query.filter(Shipment.status == status_filter)

    if country_filter:
        query = query.filter(Shipment.destination_country_id == country_filter)

    if date_from:
        query = query.filter(db.func.date(Shipment.created_at) >= date_from)

    if date_to:
        query = query.filter(db.func.date(Shipment.created_at) <= date_to)

    # Get all matching shipments
    shipments = query.order_by(Shipment.created_at.desc()).all()

    # Generate CSV
    output = io.StringIO()
    writer = csv.writer(output)

    # Write header
    writer.writerow([
        'Tracking ID', 'Barcode', 'Customer Name', 'Customer Email', 'Sender Name', 'Sender Phone',
        'Receiver Name', 'Receiver Phone', 'Destination Country', 'Weight (kg)',
        'Weight Type', 'Package Type', 'Final Price', 'Final Price (PKR)', 'Status', 'Created At'
    ])

    # Write data
    for shipment, branch, country in shipments:
        writer.writerow([
            shipment.tracking_id,
            shipment.barcode,
            branch.name,
            branch.email,
            shipment.sender_name,
            shipment.sender_phone,
            shipment.receiver_name,
            shipment.receiver_phone,
            country.name,
            f"{shipment.chargeable_weight:.2f}",
            shipment.weight_type.title(),
            'Documents' if shipment.document_type == 'docs' else 'Non-Documents',
            f"{shipment.final_price:.2f}",
            f"{shipment.final_price_pkr:.2f}",
            shipment.status.title(),
            shipment.created_at.strftime('%Y-%m-%d %H:%M:%S')
        ])

    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-disposition': 'attachment; filename=filtered_parcels.csv'}
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

def generate_barcode_number(shipment_data=None):
    """Generate a comprehensive barcode that encodes shipment information"""
    import json
    import base64
    import hashlib

    # Create a unique barcode that includes shipment information
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    random_component = str(random.randint(1000, 9999))

    # Create barcode data structure
    barcode_info = {
        'version': '1.0',
        'timestamp': timestamp,
        'random': random_component,
        'shipment_id': '',  # Will be filled when shipment is created
        'sender_phone': shipment_data.get('sender_phone', '')[:10] if shipment_data else '',
        'receiver_phone': shipment_data.get('receiver_phone', '')[:10] if shipment_data else '',
        'weight': str(shipment_data.get('weight', ''))[:5] if shipment_data else '',
        'destination': shipment_data.get('destination_code', '')[:3] if shipment_data else '',
        'type': 'PICS'  # PICS Courier
    }

    # Convert to JSON and encode
    json_data = json.dumps(barcode_info, separators=(',', ':'))
    encoded_data = base64.b64encode(json_data.encode('utf-8')).decode('utf-8')

    # Create readable barcode (remove special characters for barcode compatibility)
    clean_encoded = encoded_data.replace('/', '_').replace('+', '-').replace('=', '')

    # Create final barcode format: PICS + timestamp + encoded data (truncated)
    barcode = f"PICS{timestamp}{clean_encoded[:20]}{random_component}"

    # Ensure uniqueness by checking database
    max_attempts = 10
    attempts = 0

    while Shipment.query.filter_by(barcode=barcode).count() > 0 and attempts < max_attempts:
        # Regenerate with new random component if barcode exists
        random_component = str(random.randint(1000, 9999))
        barcode_info['random'] = random_component
        json_data = json.dumps(barcode_info, separators=(',', ':'))
        encoded_data = base64.b64encode(json_data.encode('utf-8')).decode('utf-8')
        clean_encoded = encoded_data.replace('/', '_').replace('+', '-').replace('=', '')
        barcode = f"PICS{timestamp}{clean_encoded[:20]}{random_component}"
        attempts += 1

    if attempts >= max_attempts:
        # Fallback to simple unique barcode if we can't generate a unique encoded one
        fallback_timestamp = datetime.now().strftime('%H%M%S%f')[:10]
        barcode = f"PICS{fallback_timestamp}{random.randint(1000, 9999)}"

        # Final uniqueness check
        while Shipment.query.filter_by(barcode=barcode).count() > 0:
            barcode = f"PICS{fallback_timestamp}{random.randint(1000, 9999)}"

    return barcode

def decode_barcode(barcode):
    """Decode barcode to extract shipment information"""
    try:
        if not barcode.startswith('PICS'):
            return None

        # Extract encoded part (after PICS and before final random digits)
        encoded_part = barcode[4:-4]  # Remove PICS prefix and last 4 random digits

        # Restore base64 characters
        encoded_part = encoded_part.replace('_', '/').replace('-', '+')
        # Add padding if needed
        missing_padding = len(encoded_part) % 4
        if missing_padding:
            encoded_part += '=' * (4 - missing_padding)

        # Decode
        json_data = base64.b64decode(encoded_part).decode('utf-8')
        barcode_info = json.loads(json_data)

        return barcode_info

    except Exception as e:
        print(f"Error decoding barcode {barcode}: {e}")
        return None

def generate_barcode_with_shipment_data(shipment):
    """Generate barcode using actual shipment data"""
    shipment_data = {
        'sender_phone': shipment.sender_phone,
        'receiver_phone': shipment.receiver_phone,
        'weight': str(shipment.chargeable_weight),
        'destination_code': shipment.destination_country.code if shipment.destination_country else '',
    }

    # Generate barcode with shipment data
    barcode = generate_barcode_number(shipment_data)

    # Update shipment with the new barcode
    shipment.barcode = barcode

    return barcode

def generate_branch_code():
    """Generate a unique branch code for customers"""
    # Generate a 6-character branch code
    # Format: BR + 4 random digits
    random_digits = str(random.randint(1000, 9999))
    branch_code = f"BR{random_digits}"

    # Ensure uniqueness
    while Branch.query.filter_by(branch_code=branch_code).count() > 0:
        random_digits = str(random.randint(1000, 9999))
        branch_code = f"BR{random_digits}"

    return branch_code

def create_barcode_drawing(barcode_data):
    """Create a barcode drawing for PDF reports"""
    barcode = code128.Code128(barcode_data)
    drawing = Drawing(200, 50)
    drawing.add(barcode)

    # Position the barcode in the center
    barcode.move(100, 0)  # Center horizontally

    return drawing

def convert_to_pkr(amount, from_currency='USD'):
    """Convert foreign currency to PKR"""
    # Exchange rates (you can update these as needed)
    exchange_rates = {
        'USD': 278.50,  # 1 USD = 278.50 PKR
        'EUR': 295.00,  # 1 EUR = 295.00 PKR
        'GBP': 345.00,  # 1 GBP = 345.00 PKR
        'AED': 76.00,   # 1 AED = 76.00 PKR
        'SAR': 74.00,   # 1 SAR = 74.00 PKR
    }

    if from_currency in exchange_rates:
        return amount * exchange_rates[from_currency]
    else:
        # Default conversion rate if currency not found
        return amount * 278.50  # Default to USD rate

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

def test_barcode_system():
    """Test the barcode generation and decoding system"""
    print("Testing Enhanced Barcode System...")

    # Test data
    test_shipment_data = {
        'sender_phone': '03111234567',
        'receiver_phone': '03119876543',
        'weight': '2.5',
        'destination_code': 'PK'
    }

    # Generate barcode
    barcode = generate_barcode_number(test_shipment_data)
    print(f"Generated Barcode: {barcode}")

    # Decode barcode
    decoded_info = decode_barcode(barcode)
    print(f"Decoded Info: {decoded_info}")

    # Verify the barcode contains expected information
    if decoded_info:
        print("✓ Barcode generation and decoding successful!")
        print(f"✓ Encoded sender phone: {decoded_info.get('sender_phone', 'N/A')}")
        print(f"✓ Encoded receiver phone: {decoded_info.get('receiver_phone', 'N/A')}")
        print(f"✓ Encoded weight: {decoded_info.get('weight', 'N/A')}")
        print(f"✓ Destination code: {decoded_info.get('destination', 'N/A')}")
    else:
        print("✗ Barcode decoding failed!")

    return barcode

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
    admin = Branch.query.filter_by(email='admin@login.com').first()
    if not admin:
        admin = Branch(
            name='Administrator',
            email='admin@login.com',
            phone='0000000000',
            branch_code='ADMIN',
            address='Admin Office',
            postal_code='00000',
            is_admin=True
        )
        admin.set_password('admin123')
        db.session.add(admin)
        db.session.commit()

# Database initialization function
def initialize_database():
    """Initialize database tables and sample data"""
    try:
        with app.app_context():
            # Only create tables if they don't exist
            try:
                create_tables()
                print("Database tables created successfully!")
            except Exception as e:
                print(f"Note: Tables may already exist: {e}")

            # Clean up any duplicate tracking IDs
            try:
                cleanup_duplicate_tracking_ids()
            except Exception as e:
                print(f"Note: Could not cleanup duplicates: {e}")

            # Load sample pricing data if no countries exist
            try:
                if Country.query.count() == 0:
                    load_sample_pricing_data()
                    print("Sample pricing data loaded!")
            except Exception as e:
                print(f"Note: Could not load pricing data: {e}")

            # Create sample customers for testing if no customers exist
            try:
                if Branch.query.filter_by(is_admin=False).count() == 0:
                    create_sample_customers()
                    print("Sample customers created!")
            except Exception as e:
                print(f"Note: Could not create sample customers: {e}")

            # Test the enhanced barcode system
            try:
                test_barcode_system()
                print("Enhanced barcode system test completed!")
            except Exception as e:
                print(f"Note: Could not test barcode system: {e}")

            print("Database initialization completed!")
            return True
    except Exception as e:
        print(f"Database initialization failed: {e}")
        return False


def create_sample_shipments():
    """Create sample shipments with different senders for testing"""
    try:
        # Get or create a test admin user
        admin = Branch.query.filter_by(email='admin@login.com').first()
        if not admin:
            return

        # Get a destination country
        pakistan = Country.query.filter_by(code='PK').first()
        if not pakistan:
            pakistan = Country(
                name='Pakistan',
                code='PK',
                currency='PKR',
                is_active=True
            )
            db.session.add(pakistan)
            db.session.flush()  # Flush to get the ID without committing

        # Sample shipment data
        sample_shipments = [
            {
                'sender_name': 'Ahmed Hassan',
                'sender_phone': '03111234567',
                'sender_cnic': '3520112345671',
                'sender_address': '123 Main Street, Lahore, Pakistan',
                'sender_postal_code': '54000',
                'receiver_name': 'Sara Ahmed',
                'receiver_phone': '03111234568',
                'receiver_cnic': '3520112345674',
                'receiver_address': '456 Business Ave, Karachi, Pakistan',
                'receiver_postal_code': '75500'
            },
            {
                'sender_name': 'Fatima Khan',
                'sender_phone': '03219876543',
                'sender_cnic': '3520112345672',
                'sender_address': '456 Garden Road, Karachi, Pakistan',
                'sender_postal_code': '75500',
                'receiver_name': 'Omar Khan',
                'receiver_phone': '03219876544',
                'receiver_cnic': '3520112345675',
                'receiver_address': '789 Mall Road, Lahore, Pakistan',
                'receiver_postal_code': '54000'
            },
            {
                'sender_name': 'Usman Ali',
                'sender_phone': '03331234567',
                'sender_cnic': '3520112345673',
                'sender_address': '789 Business District, Islamabad, Pakistan',
                'sender_postal_code': '44000',
                'receiver_name': 'Ayesha Usman',
                'receiver_phone': '03331234568',
                'receiver_cnic': '3520112345676',
                'receiver_address': '321 Lake View, Islamabad, Pakistan',
                'receiver_postal_code': '44000'
            },
            {
                'sender_name': 'Ahmed Hassan',  # Repeat customer
                'sender_phone': '03111234567',
                'sender_cnic': '3520112345671',
                'sender_address': '123 Main Street, Lahore, Pakistan',
                'sender_postal_code': '54000',
                'receiver_name': 'Zahra Ahmed',
                'receiver_phone': '03111234569',
                'receiver_cnic': '3520112345677',
                'receiver_address': '654 Park Lane, Faisalabad, Pakistan',
                'receiver_postal_code': '38000'
            }
        ]

        shipments_created = 0
        for shipment_data in sample_shipments:
            # Check if similar shipment already exists
            existing = Shipment.query.filter_by(
                sender_phone=shipment_data['sender_phone'],
                receiver_phone=shipment_data['receiver_phone']
            ).first()

            if not existing:
                # Generate tracking ID and barcode
                tracking_id = generate_tracking_id()

                # Calculate pricing (using default values)
                pricing_data = calculate_pricing(
                    pakistan.id, 10, 10, 10, 1.0, 'actual'
                )

                if 'error' not in pricing_data:
                    final_price_pkr = convert_to_pkr(pricing_data['final_price'], 'USD')

                    shipment = Shipment(
                        tracking_id=tracking_id,
                        barcode='',  # Will be set after creation
                        client_id=admin.id,
                        sender_name=shipment_data['sender_name'],
                        sender_phone=shipment_data['sender_phone'],
                        sender_cnic=shipment_data['sender_cnic'],
                        sender_address=shipment_data['sender_address'],
                        sender_postal_code=shipment_data['sender_postal_code'],
                        receiver_name=shipment_data['receiver_name'],
                        receiver_phone=shipment_data['receiver_phone'],
                        receiver_cnic=shipment_data['receiver_cnic'],
                        receiver_address=shipment_data['receiver_address'],
                        receiver_postal_code=shipment_data['receiver_postal_code'],
                        destination_country_id=pakistan.id,
                        length=10,
                        width=10,
                        height=10,
                        actual_weight=1.0,
                        weight_type='actual',
                        document_type='non_docs',
                        volumetric_weight=pricing_data['volumetric_weight'],
                        chargeable_weight=pricing_data['chargeable_weight'],
                        base_price=pricing_data['base_price'],
                        gst_amount=pricing_data['gst_amount'],
                        final_price=pricing_data['final_price'],
                        final_price_pkr=final_price_pkr,
                        status='delivered'  # Mark as delivered so they appear in history
                    )

                    db.session.add(shipment)
                    shipments_created += 1

        db.session.commit()

        # Generate comprehensive barcodes for all created shipments
        for shipment_data in sample_shipments[:shipments_created]:
            existing = Shipment.query.filter_by(
                sender_phone=shipment_data['sender_phone'],
                receiver_phone=shipment_data['receiver_phone']
            ).first()

            if existing and not existing.barcode:
                generate_barcode_with_shipment_data(existing)

        db.session.commit()
        print(f"Created {shipments_created} sample shipments for testing!")

    except Exception as e:
        print(f"Error creating sample shipments: {e}")
        db.session.rollback()

def update_database_schema():
    """Update database schema to add new columns"""
    try:
        with app.app_context():
            # Check if barcode column exists
            try:
                db.session.execute(db.text("SELECT barcode FROM shipment LIMIT 1"))
                print("✓ Barcode column already exists")
            except Exception:
                print("Adding barcode column to shipment table...")
                try:
                    db.session.execute(db.text("ALTER TABLE shipment ADD COLUMN barcode VARCHAR(20)"))
                    print("✓ Added barcode column")
                except Exception as e:
                    print(f"Note: Could not add barcode column: {e}")

            # Check if final_price_pkr column exists
            try:
                db.session.execute(db.text("SELECT final_price_pkr FROM shipment LIMIT 1"))
                print("✓ Final price PKR column already exists")
            except Exception:
                print("Adding final_price_pkr column to shipment table...")
                try:
                    db.session.execute(db.text("ALTER TABLE shipment ADD COLUMN final_price_pkr FLOAT"))
                    print("✓ Added final_price_pkr column")
                except Exception as e:
                    print(f"Note: Could not add final_price_pkr column: {e}")

            # Check if branch_id column exists (new structure)
            try:
                db.session.execute(db.text("SELECT branch_id FROM shipment LIMIT 1"))
                print("✓ Branch ID column already exists")
            except Exception:
                print("Note: Branch ID column not found - using existing structure")

            db.session.commit()
            print("Database schema check completed!")
            return True

    except Exception as e:
        print(f"Error checking database schema: {e}")
        return False

def update_existing_shipments():
    """Update existing shipments with barcodes and PKR pricing"""
    try:
        with app.app_context():
            # Find shipments without barcodes - use a simpler query to avoid column issues
            try:
                # Try with branch_id first (new structure)
                shipments_without_barcode = Shipment.query.filter(
                    db.or_(Shipment.barcode.is_(None), Shipment.barcode == '')
                ).all()
            except Exception:
                # If that fails, try with client_id (old structure)
                shipments_without_barcode = Shipment.query.filter(
                    db.or_(Shipment.barcode.is_(None), Shipment.barcode == '')
                ).all()

            if shipments_without_barcode:
                print(f"Updating {len(shipments_without_barcode)} shipments with enhanced barcodes...")
                for shipment in shipments_without_barcode:
                    # Generate comprehensive barcode with shipment data if missing
                    if not shipment.barcode:
                        generate_barcode_with_shipment_data(shipment)

                    # Calculate PKR price if missing
                    if not shipment.final_price_pkr or shipment.final_price_pkr == 0:
                        shipment.final_price_pkr = convert_to_pkr(shipment.final_price, shipment.destination_country.currency)

                db.session.commit()
                print(f"✓ Updated {len(shipments_without_barcode)} existing shipments with enhanced barcodes")
            else:
                print("All shipments already have barcodes and PKR pricing")

            return True

    except Exception as e:
        print(f"Error updating existing shipments: {e}")
        # Don't rollback here as it might cause context issues
        return False

# Initialize database only when running directly (not when imported)
if __name__ == '__main__':
    print("Starting PICS Courier Application...")
    print("Checking and updating database schema...")

    # First update schema if needed
    schema_updated = update_database_schema()

    if schema_updated:
        print("Updating existing shipments with new features...")
        update_existing_shipments()

        print("Initializing database...")
        if initialize_database():
            print("Application ready!")
            print("Access the application at: http://localhost:5000")
            app.run(debug=True)
        else:
            print("Failed to initialize database. Please check the error messages above.")
            exit(1)
    else:
        print("Failed to update database schema.")
        exit(1)

if __name__ == '__main__':
    app.run(debug=True)
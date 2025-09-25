# PICS Courier Services

A complete Python web application for courier services with advanced features including weight-based pricing, client authentication, and PDF receipt generation.

## Features

- **User Authentication**: Complete client registration and login system
- **Dual Weight System**: Choose between actual weight and volumetric weight for pricing
- **Country-Based Pricing**: Dynamic pricing based on destination country and weight tiers
- **Real-time Price Calculation**: Live pricing updates as you enter package details
- **PDF Receipt Generation**: Professional PDF receipts with all shipment details
- **Admin Panel**: Upload pricing data and manage system settings
- **Responsive Design**: Modern, mobile-friendly interface using Tailwind CSS

## Installation

1. **Clone or download** this project to your local machine

2. **Install Python dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Set up the database**:
   ```bash
   python app.py
   ```
   The application will automatically create the database and default admin user.

4. **Access the application**:
   - Open your browser and go to `http://localhost:5000`
   - Default admin login:
     - Email: `admin@pics.com`
     - Password: `admin123`

## Usage

### For Clients

1. **Register** a new account or **login** with existing credentials
2. **Book a shipment**:
   - Fill in sender and receiver information
   - Select destination country
   - Choose weight type (actual or volumetric)
   - Enter package dimensions and weight
   - Review calculated pricing
   - Submit to generate receipt
3. **Download PDF receipt** for your records
4. **Track shipments** from your dashboard

### For Administrators

1. **Login** with admin credentials
2. **Upload pricing data**:
   - Go to Admin Panel → Upload Pricing Data
   - Use the provided CSV format
   - Upload sample_pricing.csv to get started
3. **Manage system** settings and view analytics

## CSV Pricing Format

The system accepts CSV files with the following columns:

- `country_code`: 3-letter ISO country code (e.g., USA, GBR, PAK)
- `country_name`: Full country name
- `currency`: 3-letter currency code (e.g., USD, GBP, PKR)
- `min_weight`: Minimum weight for this tier (kg)
- `max_weight`: Maximum weight for this tier (kg)
- `price_per_kg`: Price per kilogram
- `base_fee`: Optional base fee (defaults to 0)

Example:
```csv
country_code,country_name,currency,min_weight,max_weight,price_per_kg,base_fee
USA,United States,USD,0,5,15.50,2.00
USA,United States,USD,5,10,12.00,2.00
PAK,Pakistan,PKR,0,2,500.00,50.00
```

## Weight Calculation

### Volumetric Weight
```
Volumetric Weight = (Length × Width × Height) ÷ 5000
```

### Chargeable Weight
The system uses the higher of actual weight or volumetric weight for pricing calculations.

### Pricing Formula
```
Base Price = (Chargeable Weight × Price per KG) + Base Fee
GST = Base Price × 18%
Final Price = Base Price + GST
```

## File Structure

```
├── app.py                 # Main Flask application
├── requirements.txt       # Python dependencies
├── sample_pricing.csv     # Sample pricing data
├── templates/             # HTML templates
│   ├── base.html         # Base template
│   ├── index.html        # Homepage
│   ├── login.html        # Login page
│   ├── register.html     # Registration page
│   ├── dashboard.html    # User dashboard
│   ├── book_shipment.html # Shipment booking form
│   ├── receipt.html      # Shipment receipt
│   ├── admin.html        # Admin panel
│   └── upload_pricing.html # Pricing upload page
└── uploads/              # Uploaded files (created automatically)
```

## Technologies Used

- **Backend**: Python Flask
- **Database**: SQLite (SQLAlchemy ORM)
- **Frontend**: HTML, CSS, JavaScript
- **Styling**: Tailwind CSS
- **PDF Generation**: ReportLab
- **Authentication**: Flask-Login
- **Forms**: Flask-WTF

## Security Features

- Password hashing with Werkzeug
- CSRF protection on forms
- User session management
- File upload validation
- Input sanitization

## Development

To run in development mode:
```bash
python app.py
```

The application will start on `http://localhost:5000` with debug mode enabled.

## Production Deployment

1. Set `SECRET_KEY` environment variable
2. Configure production database URI
3. Set `FLASK_ENV=production`
4. Use a production WSGI server (e.g., Gunicorn)

## Support

For issues or questions:
1. Check the application logs
2. Verify all dependencies are installed
3. Ensure the database is properly initialized
4. Check file permissions for uploads directory

## License

This project is created for demonstration purposes.
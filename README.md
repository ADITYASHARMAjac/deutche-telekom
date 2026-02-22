# Email Sender Web UI

A simple Flask web application for sending emails in bulk with templates and live status tracking.

## Features

- Upload CSV with email addresses
- Review and manage email list
- Pre-built email templates (Service Notice, Maintenance, Welcome, Incident Alert, Newsletter)
- Sequential email sending with timed delays
- Live progress tracking
- Template customization with tokens

## Local Setup

1. Clone the repository
2. Create a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Create a `.env` file with your SMTP credentials:
   ```
   SENDER_EMAIL=your-email@gmail.com
   APP_PASSWORD=your-app-password
   SMTP_SERVER=smtp.gmail.com
   SMTP_PORT=587
   ```

5. Run the application:
   ```bash
   python emailssender.py
   ```

6. Open your browser and go to `http://localhost:5000`

## Environment Variables

- `SENDER_EMAIL` - Email address to send from
- `APP_PASSWORD` - SMTP authentication password
- `SMTP_SERVER` - SMTP server hostname (default: smtp.gmail.com)
- `SMTP_PORT` - SMTP port (default: 587)

## Deployment on Render

1. Push your code to GitHub
2. Connect your GitHub repository to Render
3. Create a new Web Service
4. Set environment variables in Render dashboard:
   - `SENDER_EMAIL`
   - `APP_PASSWORD`
5. Render will automatically detect and use the Procfile

## Security Notes

- **Store credentials in environment variables, never in code**
- Use GitHub to store only templates and code, never secrets
- For Google account, use an [App Password](https://support.google.com/accounts/answer/185833)

## File Structure

```
.
├── emailssender.py      # Main Flask application
├── requirements.txt     # Python dependencies
├── Procfile            # Render deployment configuration
├── render.yaml         # Alternative Render config format
├── .gitignore          # Git ignore rules
├── .env                # Environment variables (DO NOT COMMIT)
├── emails.csv          # Email list (example)
├── static/
│   └── style.css       # CSS styling
└── templates/
    ├── home.html
    ├── index.html
    └── templates.html
```

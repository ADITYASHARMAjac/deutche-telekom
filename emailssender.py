"""
Web UI email sender
-------------------
Single-file Flask app that lets you upload a CSV, review the email list, and
trigger a timed, sequential send with live status. Designed for quick, local
use. Keep credentials in environment variables, not in source.
"""

import csv
import io
import os
import random
import smtplib
import threading
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from flask import Flask, jsonify, render_template, request


def load_env_file(path: str = ".env"):
        """Load simple KEY=VALUE lines from a .env file if present (no extras)."""
        if not os.path.isfile(path):
                return
        try:
                with open(path, "r", encoding="utf-8") as f:
                        for raw in f:
                                line = raw.strip()
                                if not line or line.startswith("#") or "=" not in line:
                                        continue
                                key, val = line.split("=", 1)
                                key = key.strip()
                                if not key or key in os.environ:
                                        continue
                                os.environ[key] = val.strip().strip('"').strip("'")
        except Exception:
                pass  # fail-safe: do not block app start on env file errors


# Load .env before reading defaults
load_env_file()

# =====================
# ENV / DEFAULTS
# =====================
DEFAULT_SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
DEFAULT_SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
LOCAL_SENDER_EMAIL = os.getenv("LOCAL_SENDER_EMAIL", "")
LOCAL_APP_PASSWORD = os.getenv("LOCAL_APP_PASSWORD", "")
DEFAULT_SENDER_EMAIL = os.getenv("SENDER_EMAIL") or LOCAL_SENDER_EMAIL
DEFAULT_APP_PASSWORD = os.getenv("APP_PASSWORD") or LOCAL_APP_PASSWORD

DEFAULT_SUBJECT = "Deutsche Telekom | Service Notice"
DEFAULT_BODY = """
Dear {{customer_name}},

We are sharing a short service update from Deutsche Telekom regarding your account {{account_id}}.

Summary
- Request/Case: {{case_reference}}
- Affected service: {{service_name}}
- Status: {{status}}
- ETA/Next step: {{eta}}

If there is anything urgent, reply to this email and our team will prioritise your ticket. You can also reach us via the service desk with your reference number.

Thank you for your patience and for choosing Deutsche Telekom.

Best regards,
Deutsche Telekom Service Desk
"""

# =====================
# APP / STATE
# =====================
app = Flask(__name__, static_folder="static", template_folder="templates")

DELAY_MIN_SECONDS = 5.0
DELAY_MAX_SECONDS = 9.0

state_lock = threading.Lock()
state = {
        "emails": [],
        "in_progress": False,
        "sent": 0,
        "failed": [],
        "started_at": None,
        "finished_at": None,
        "last_error": None,
        "log": [],
        "current": None,
        "config": {},
}

templates_lock = threading.Lock()
templates_store = [
        {
                "name": "Service Notice",
                "category": "Service",
                "type": "Transactional",
                "source": "Standard",
                "subject": "Deutsche Telekom | Service Notice",
                "body": DEFAULT_BODY.strip(),
                "tokens": ["{{customer_name}}", "{{account_id}}", "{{case_reference}}", "{{service_name}}", "{{eta}}"],
        },
        {
                "name": "Planned Maintenance",
                "category": "Maintenance",
                "type": "Operational",
                "source": "Standard",
                "subject": "Deutsche Telekom | Planned Maintenance",
                "body": "We will perform planned maintenance on {{service_name}} between {{maintenance_window}}. Impact: {{impact}}. Reference: {{case_reference}}.",
                "tokens": ["{{service_name}}", "{{maintenance_window}}", "{{impact}}", "{{case_reference}}"],
        },
        {
                "name": "Welcome",
                "category": "Onboarding",
                "type": "Lifecycle",
                "source": "Standard",
                "subject": "Welcome to Deutsche Telekom",
                "body": "Welcome aboard {{customer_name}}. Your account {{account_id}} is active. Next steps: {{eta}}.",
                "tokens": ["{{customer_name}}", "{{account_id}}", "{{eta}}"],
        },
        {
                "name": "Incident Alert",
                "category": "Incident",
                "type": "Operational",
                "source": "Standard",
                "subject": "Deutsche Telekom | Incident {{case_reference}}",
                "body": "We detected an incident impacting {{service_name}}. Status: {{status}}. Next update by {{eta}}. Reference: {{case_reference}}.",
                "tokens": ["{{service_name}}", "{{status}}", "{{eta}}", "{{case_reference}}"],
        },
        {
                "name": "Newsletter",
                "category": "Announcement",
                "type": "Marketing",
                "source": "Standard",
                "subject": "Deutsche Telekom | Monthly Update",
                "body": "Hello {{customer_name}}, here are the latest highlights: {{highlights}}. For questions, reach us with reference {{case_reference}}.",
                "tokens": ["{{customer_name}}", "{{highlights}}", "{{case_reference}}"],
        },
]


def reset_state(emails=None):
        with state_lock:
                state["emails"] = emails or []
                state["in_progress"] = False
                state["sent"] = 0
                state["failed"] = []
                state["started_at"] = None
                state["finished_at"] = None
                state["last_error"] = None
                state["log"] = []
                state["current"] = None
                state["config"] = {}


def normalize_email(value):
        return (value or "").strip()


def is_basic_email(value):
        return "@" in value and "." in value


def parse_tokens(raw):
        if isinstance(raw, list):
                return [str(t).strip() for t in raw if str(t).strip()]
        if isinstance(raw, str):
                pieces = [p.strip() for p in raw.replace("\n", ",").split(",")]
                return [p for p in pieces if p]
        return []


def extract_emails_from_csv(file_storage):
        text = file_storage.read()
        if isinstance(text, bytes):
                text = text.decode("utf-8", errors="ignore")
        reader = csv.DictReader(io.StringIO(text))
        emails = []
        for row in reader:
                email = normalize_email(row.get("email") or row.get("Email"))
                if email:
                        emails.append(email)
        return emails


def append_log(message):
        with state_lock:
                state["log"].append({
                        "timestamp": time.time(),
                        "message": message,
                })
                # keep log reasonably small
                if len(state["log"]) > 500:
                        state["log"] = state["log"][-500:]


def send_email(server, sender_email, receiver_email, subject, body):
        msg = MIMEMultipart()
        msg["From"] = sender_email
        msg["To"] = receiver_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))
        server.sendmail(sender_email, receiver_email, msg.as_string())


def send_worker(config):
        sender_email = config["sender_email"]
        app_password = config["app_password"]
        smtp_server = config["smtp_server"]
        smtp_port = config["smtp_port"]
        subject = config["subject"]
        body = config["body"]
        delay_min = config["delay_min"]
        delay_max = config["delay_max"]

        with state_lock:
                emails = list(state["emails"])
                state["in_progress"] = True
                state["started_at"] = time.time()
                state["finished_at"] = None
                state["sent"] = 0
                state["failed"] = []
                state["last_error"] = None
                state["config"] = config

        server = None
        try:
                server = smtplib.SMTP(smtp_server, smtp_port)
                server.starttls()
                server.login(sender_email, app_password)

                total = len(emails)
                for idx, recipient in enumerate(emails):
                        slot_number = idx + 1
                        with state_lock:
                                state["current"] = recipient

                        try:
                                body_with_slot = body.replace("{{Match Name}}", f"Slot {slot_number}/{total}")
                                if "{{Match Name}}" not in body:
                                        body_with_slot = f"Slot {slot_number}/{total}\n\n{body}"
                                send_email(server, sender_email, recipient, subject, body_with_slot)
                                append_log(f"Sent slot {slot_number}/{total} to {recipient}")
                                with state_lock:
                                        state["sent"] += 1
                        except Exception as exc:  # catch individual send errors and continue
                                append_log(f"Failed slot {slot_number}/{total} to {recipient}: {exc}")
                                with state_lock:
                                        state["failed"].append({"email": recipient, "error": str(exc)})

                        time.sleep(random.uniform(delay_min, delay_max))

        except Exception as exc:  # connection / auth errors
                append_log(f"Fatal error: {exc}")
                with state_lock:
                        state["last_error"] = str(exc)
        finally:
                if server:
                        server.quit()
                with state_lock:
                        state["finished_at"] = time.time()
                        state["in_progress"] = False
                        state["current"] = None


@app.route("/")
def index():
        return render_template(
                "index.html",
                active_page="dashboard",
                default_subject=DEFAULT_SUBJECT,
                default_body=DEFAULT_BODY,
                default_sender=DEFAULT_SENDER_EMAIL,
                default_delay=DELAY_MIN_SECONDS,
                delay_min=DELAY_MIN_SECONDS,
                delay_max=DELAY_MAX_SECONDS,
                default_smtp=DEFAULT_SMTP_SERVER,
                default_port=DEFAULT_SMTP_PORT,
        )


@app.route("/templates")
def templates_page():
        with templates_lock:
                templates = list(templates_store)
        return render_template(
                "templates.html",
                active_page="templates",
                templates=templates,
                default_smtp=DEFAULT_SMTP_SERVER,
                default_port=DEFAULT_SMTP_PORT,
        )


@app.route("/api/templates", methods=["GET"])
def api_list_templates():
        with templates_lock:
                templates = list(templates_store)
        return jsonify({"templates": templates})


@app.route("/api/templates/save", methods=["POST"])
def api_save_template():
        data = request.get_json(force=True)
        name = (data.get("name") or "").strip()
        category = (data.get("category") or "Uncategorized").strip()
        email_type = (data.get("type") or "General").strip()
        source = (data.get("source") or "Custom").strip()
        subject = (data.get("subject") or "").strip()
        body = (data.get("body") or "").strip()
        tokens = parse_tokens(data.get("tokens"))

        if not name:
                return jsonify({"error": "Name is required"}), 400
        if not subject or not body:
                return jsonify({"error": "Subject and body are required"}), 400

        with templates_lock:
                existing = None
                for tpl in templates_store:
                        if tpl["name"].lower() == name.lower():
                                existing = tpl
                                break
                if not existing:
                        return jsonify({"error": "Template not found; creation disabled"}), 404

                existing.update({
                        "name": name,
                        "category": category or existing.get("category") or "Uncategorized",
                        "type": email_type or existing.get("type") or "General",
                        "source": source or existing.get("source") or "Standard",
                        "subject": subject,
                        "body": body,
                        "tokens": tokens,
                })

                templates = list(templates_store)

        return jsonify({"status": "ok", "template": existing, "templates": templates})


@app.route("/upload", methods=["POST"])
def upload_csv():
        if "file" not in request.files:
                return jsonify({"error": "CSV file is required"}), 400

        file = request.files["file"]
        if not file.filename.lower().endswith(".csv"):
                return jsonify({"error": "Please upload a .csv file"}), 400

        emails = extract_emails_from_csv(file)
        reset_state(emails)
        return jsonify({"count": len(emails), "emails": emails})


@app.route("/start", methods=["POST"])
def start_sending():
        data = request.get_json(force=True)

        with state_lock:
                if state["in_progress"]:
                        return jsonify({"error": "Already sending"}), 409
                if not state["emails"]:
                        return jsonify({"error": "Upload a CSV first"}), 400

        # Force using backend-provided sender to avoid client tampering
        sender_email = normalize_email(DEFAULT_SENDER_EMAIL)
        app_password = DEFAULT_APP_PASSWORD  # use backend-provided secret only
        smtp_server = data.get("smtp_server") or DEFAULT_SMTP_SERVER
        smtp_port = int(data.get("smtp_port") or DEFAULT_SMTP_PORT)
        subject = data.get("subject") or DEFAULT_SUBJECT
        body = data.get("body") or DEFAULT_BODY
        if not sender_email or not app_password:
                return jsonify({"error": "Server is missing sender credentials"}), 500

        config = {
                "sender_email": sender_email,
                "app_password": app_password,
                "smtp_server": smtp_server,
                "smtp_port": smtp_port,
                "subject": subject,
                "body": body,
                "delay_min": DELAY_MIN_SECONDS,
                "delay_max": DELAY_MAX_SECONDS,
        }

        thread = threading.Thread(target=send_worker, args=(config,), daemon=True)
        thread.start()

        return jsonify({"status": "started"})


@app.route("/status")
def status():
        with state_lock:
                total = len(state["emails"])
                elapsed = time.time() - state["started_at"] if state["started_at"] else 0
                result = {
                        "in_progress": state["in_progress"],
                        "sent": state["sent"],
                        "failed": state["failed"],
                        "total": total,
                        "started_at": state["started_at"],
                        "finished_at": state["finished_at"],
                        "last_error": state["last_error"],
                        "current": state["current"],
                        "elapsed_seconds": elapsed,
                        "log": state["log"][-50:],  # return last 50 entries for brevity
                }
        return jsonify(result)


@app.route("/add_email", methods=["POST"])
def add_email():
        data = request.get_json(force=True)
        email = normalize_email(data.get("email"))
        if not email or not is_basic_email(email):
                return jsonify({"error": "Valid email is required"}), 400

        with state_lock:
                if state["in_progress"]:
                        return jsonify({"error": "Cannot modify list while sending"}), 409
                if email in state["emails"]:
                        return jsonify({"error": "Email already in list"}), 409
                state["emails"].append(email)
                append_log(f"Added manual email {email}")
                total = len(state["emails"])
                tail = state["emails"][-50:]

        return jsonify({"status": "added", "total": total, "emails": tail})


if __name__ == "__main__":
        # Run the Flask dev server. For production, use a proper WSGI server.
        app.run(host="0.0.0.0", port=5000, debug=True)

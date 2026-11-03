# EduSpare — Project Ordering Website

Flask + SQLite responsive website with customer order intake, admin quotations, 50% advance, ₹500 urgency surcharge, UPI proof upload, admin verification, order status, and customer tracking.

## Local setup

```bash
cd eduspare
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Set environment variables (do not use `.env.example` values as real secrets):

```bash
export SECRET_KEY='a-long-random-secret'
export ADMIN_USER='admin'
export ADMIN_PASSWORD='your-strong-password'
python app.py
```

Windows PowerShell: `$env:SECRET_KEY='...'`, `$env:ADMIN_USER='admin'`, `$env:ADMIN_PASSWORD='...'`, then `python app.py`.

Open http://127.0.0.1:5000 and admin at /login.

## Workflow

1. Customer submits requirements, gets an order ID.
2. Admin opens `/admin`, sets base quote and status `Quoted`.
3. Customer revisits `/track/ORDER-ID`, verifies their phone and accepts quotation.
4. Customer pays 50% to `computerbaazi@axl`, uploads transaction reference and proof.
5. Admin verifies the actual UPI receipt, checks Advance Verified, changes status to In Progress.
6. Admin updates progress. Verify remaining payment before setting Delivered.

## Important deployment notes

- WhatsApp button opens a prefilled message; it **does not automatically send**. Automated messages require approved WhatsApp Business API integration.
- UPI payment is **manual**, not verified by screenshot alone. Confirm funds in the receiving account.
- The initial admin account is created only when `ADMIN_PASSWORD` is set and the admin table is empty. Change password in database via a secure process if needed.
- This is a deployable starter, **not production-hardened**: add HTTPS, persistent database/storage, backup/restore, rate limiting, email/OTP customer verification, audit logs, secure upload content inspection, CSRF-safe operational procedures, transactional notifications, legal policy pages, and payment reconciliation before public launch.
- Customer access currently uses matching order ID and phone number, not OTP; do not store sensitive identity documents or confidential files until authentication is upgraded.
- Uploaded payment proof is admin-only via authenticated route; uploads folder should remain private and be persisted securely.
- Run `gunicorn app:app` behind HTTPS reverse proxy on Linux hosting; ensure `SECRET_KEY`, `ADMIN_PASSWORD` are set, and persistent volumes for database and uploads.
- Legacy Google Form: https://forms.gle/2Y6YPVmRd1zcFMSS8 (reference only; the new order form is integrated directly).
- Delivery and refund terms should be reviewed for compliance with applicable Indian consumer laws.

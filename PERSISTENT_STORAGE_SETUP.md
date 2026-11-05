# Persistent orders on Vercel (Neon PostgreSQL)

This branch fixes disappearing orders and payment proofs caused by storing SQLite and uploads under Vercel's temporary filesystem.

## Required deployment steps

1. In Vercel, open the **eduspare-order** project -> **Storage / Marketplace** and connect a Neon PostgreSQL database to the project.
2. In Vercel -> Project -> Settings -> Environment Variables, ensure `DATABASE_URL` is populated with the Neon PostgreSQL connection string for **Production** (and Preview if testing preview deployments). Some integrations create `POSTGRES_URL` instead; the app accepts either. **Do not put the connection string in GitHub or send it in chat.**
3. Keep `SECRET_KEY`, `ADMIN_USER`, `ADMIN_PASSWORD`, and existing SMTP variables set. Set a long, randomly generated `SECRET_KEY` and keep it stable between deployments.
4. Deploy this branch as a **Preview** and inspect runtime logs. The app automatically creates tables on startup.
5. Test an order using non-sensitive test information and a dummy payment-proof file (do not make a real payment). Confirm it appears in admin, confirm download of the proof, update status, refresh, and test another deployment. Also test customer tracking.
6. When Preview tests pass, merge the pull request and confirm the new Production deployment is **Ready**. Make a fresh test order and verify persistence.

**Safety guard:** Vercel deployments of this branch fail rather than accepting orders into nonpersistent SQLite if no PostgreSQL URL is configured. Connect Neon before merging.

## Data and limitations

- Orders, status history, admin login hashes, and uploaded proof bytes now use PostgreSQL when a URL is present.
- Payment-proof uploads are capped by the Flask request limit (5 MiB). PostgreSQL storage is suitable for the current low-volume project; for larger-scale uploads, migrate proof files to private object storage.
- Existing SQLite records are **not migrated automatically**. Older ephemeral Vercel records may no longer be available. Recover order details from confirmation emails or backups, if present.
- Local development still uses SQLite. A fresh Neon database initializes an admin using `ADMIN_USER` and `ADMIN_PASSWORD` at first startup; changing those environment variables later does not reset an existing database password.
- Enable automated database backups and verify retention in the Neon console.

## Suggested checks

Run locally:
```bash
python -m pip install -r requirements.txt
python -m compileall -q app.py
```
In a secure shell with `DATABASE_URL` and admin credentials set, launch Flask and use the normal order and admin flows.

## Caution

Do not merge before Neon is connected. If the temporary SQLite database still contains data, export it first. This patch does not delete existing Vercel variables or change the live deployment until it is merged.

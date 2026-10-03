# Remote Skills Exchange (Flask + Jinja + Bootstrap 5 + JavaScript)

Connect Skills. Discover Services. Get Things Done.

Your original project's models, seed data, lockout and booking rules are kept. The React/Vite frontend and JSON API were replaced by
server-rendered Flask pages (Jinja2 templates, Bootstrap 5, Bootstrap Icons, custom CSS, vanilla JavaScript). There is **no Node/npm step**.

## Run it
    pip install -r backend/requirements.txt
    cp .env.example backend/.env        # edit SECRET_KEY etc.
    cd backend && python seed.py && cd ..   # creates tables, 12 categories, admin, demo data
    python app.py                       # http://127.0.0.1:5000        (production: gunicorn wsgi:app)
    python test_flow.py                 # 76 end-to-end checks on a throwaway database

## Accounts
* **Admin:** created by `seed.py` from `ADMIN_EMAIL` / `ADMIN_PASSWORD` (dev default `admin@example.com` / `Admin@12345` only when `FLASK_ENV` is not production;
  in production `ADMIN_PASSWORD` is required). Nobody can register as admin.
* **Demo (dev only, `SEED_DEMO=0` to skip):** provider1-3@example.com `Provider@123`, customer1-5@example.com `Customer@123`.
* **Real users:** /register, choose Customer or Service Provider.

## Layout
    app.py / wsgi.py            entry points            backend/seed.py   schema + demo data
    backend/app/models.py       SQLAlchemy models       backend/app/routes/{main,auth,bookings,provider,admin}.py
    backend/app/templates/      Jinja pages (+ admin/, provider/)       backend/app/static/{css,js}
Where JavaScript is used: confirmation modals for destructive actions, client-side form validation, loading/double-submit guard,
image preview, show-password, and a live unread-notification badge (polls `/notifications/count`). All rules are enforced server-side.

## Production notes
Set `FLASK_ENV=production`, `SECRET_KEY`, `ADMIN_PASSWORD`, `PUBLIC_APP_URL`, `PRODUCTION` HTTPS, and a persistent disk (or `DATABASE_URL` for MySQL/Postgres) plus
persistent storage for `backend/app/static/uploads`. Deploy with the `Procfile` (`gunicorn wsgi:app`) on Render/Railway/Fly/PythonAnywhere.
Password reset links are written to the server log (no SMTP is configured); in debug mode they are also shown on screen.

## Hero photo slider
Three photos fade in and out every 4 seconds with a slow zoom (pure CSS, no JavaScript). Put your photos in **`public/images/`** with these exact names:
`student-tech-1.jpg`, `student-tech-2.jpg`, `student-tech-3.jpg` (served at `/images/...`). Landscape, ~1920x1080, under 500 KB each.
The markup is in `backend/app/templates/home.html` (look for the "PHOTO 1 / 2 / 3" comments); the animation is at the bottom of `backend/app/static/css/style.css`.

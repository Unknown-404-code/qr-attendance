# Put the app online (free)

The app runs on Render's free plan, and the attendance data lives in a free Supabase database. Students and the
doctor open one address, `https://<service-name>.onrender.com`, from any phone or laptop. No card is needed for
either service.

What the free plan means in class:

- **The site sleeps after 15 minutes without visitors.** The first visit after that takes about a minute while it
  wakes up. Open the course page a few minutes before class.
- **Each check-in takes about a second**, because a free server gets a tenth of a CPU.
- **Supabase pauses a free database after 7 days without use.** After a long break, open your Supabase project and
  click **Restore project**, then wait a minute.

## 1. Make the database (Supabase)

1. Sign in at [supabase.com](https://supabase.com) and click **New project** in your organization.
2. Name it (for example `attendance`), choose the region **East US (North Virginia)**, turn **Enable Data API** off
   and **Enable RLS on new tables automatically** on. The app talks to the database directly, so it doesn't need the
   Data API, and turning it off keeps student data from being reachable through it.
3. Set a **database password made of letters and numbers only**. Characters like `@ : / # ? %` break the
   connection link. Save the password, then click **Create new project**.
4. When the project is ready, click **Connect** → **Direct** → **Session pooler**, and copy the connection string:
   `postgresql://postgres.<project-ref>:[YOUR-DATABASE-PASSWORD]@aws-0-us-east-1.pooler.supabase.com:5432/postgres`
   Replace `[YOUR-DATABASE-PASSWORD]` (brackets included) with your password. This full line is your `DATABASE_URL`.

Use the **Session pooler** string. The "Direct connection" one doesn't work from Render. The app creates its own
tables on first start.

## 2. Put the code on GitHub

Render deploys from a GitHub repository. Create an empty private repository on your GitHub account, then from this
folder:

```powershell
git remote add mine https://github.com/<your-account>/<repo-name>.git
```

```powershell
git push -u mine main
```

## 3. Make the web service (Render)

1. Sign in at [render.com](https://render.com) with GitHub, click **New** → **Web Service**, connect GitHub, and pick
   your repository. Render sees the `Dockerfile` and picks **Docker** by itself.
2. Region **Virginia (US East)**, next to the database. Instance type **Free**.
3. Add these environment variables:

| Name | Value |
|---|---|
| `DATABASE_URL` | the full line from step 1.4 |
| `GA_SECRET` | click **Generate**. Keep it the same forever: changing it signs everyone out. |
| `ADMIN_EMAIL` | the email you'll sign in with |
| `ADMIN_PASSWORD` | your admin password, at least 8 characters |
| `TZ` | your campus time zone, for example `Asia/Dubai` |

4. Under **Advanced**, set **Health Check Path** to `/login`.
5. Click **Deploy web service**. The first build takes 10-15 minutes. Later pushes to `main` redeploy on their own.

## 4. Sign in and make the doctor's account

1. Open `https://<service-name>.onrender.com/login` and sign in with `ADMIN_EMAIL` and `ADMIN_PASSWORD`.
2. Click **Accounts**, then add the doctor's name and email. Leave the password empty to get a random one.
3. Send the doctor the address, their email and the password. They can change it under **Password**.

## If something goes wrong

- **Forgot the admin password:** add the environment variable `ADMIN_RESET_PASSWORD` = `1`, set `ADMIN_PASSWORD` to
  a new password, and save (Render redeploys). After you sign in, delete `ADMIN_RESET_PASSWORD`.
- **The log says "Hosted mode needs these secrets":** `DATABASE_URL` or `GA_SECRET` is missing or misspelled.
- **Errors mentioning the database:** check that `DATABASE_URL` is the Session pooler string with your real password
  in it, and that the Supabase project isn't paused.
- **The service restarts during check-ins with "out of memory":** the free plan has 512 MB and the app uses about
  300 MB. If it happens, Render's Starter plan (512 MB, more CPU) or Google Cloud Run (see below) fixes it.

## Other hosts

- **Google Cloud Run** (free tier, needs a card on the billing account, faster):
  `.\scripts\deploy_cloudrun.ps1 -Project <your-project-id> -AdminEmail you@example.com`. The script explains the
  three secrets it expects in Secret Manager.
- **Hugging Face Spaces:** Docker Spaces now need a paid PRO plan. `scripts/deploy_space.py` still uploads the app.
- **Your laptop:** `start.bat` runs everything locally with a temporary Cloudflare link. The laptop has to stay on
  during class.

## Privacy

Selfies are checked in memory and never saved. The database stores names, student IDs, check-in times and a
512-number face code per student. A doctor can delete a student's face code with **Reset** on the course page.
The face model (InsightFace) is licensed for non-commercial research use only.

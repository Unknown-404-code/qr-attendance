# Put the app online (free)

The app runs on a free Hugging Face Space, and the attendance data lives in a free Supabase database.
Students and the doctor open one address, `https://<your-name>-<space-name>.hf.space`, from any phone or laptop.

You need about 30 minutes, a Hugging Face account and a Supabase account. Both are free.

## 1. Make the database (Supabase)

1. Sign in at [supabase.com](https://supabase.com) and click **New project**.
2. Pick a name (for example `attendance`) and a region close to you. Set a **database password** and save it
   somewhere safe. You need it in a minute.
3. Wait until the project is ready (about 2 minutes), then click **Connect** at the top of the project page.
4. Under **Session pooler**, copy the connection string. It looks like this:
   `postgresql://postgres.abcdefgh:[YOUR-PASSWORD]@aws-0-eu-central-1.pooler.supabase.com:5432/postgres`
5. Replace `[YOUR-PASSWORD]` with the database password from step 2. This full line is your `DATABASE_URL`.

Use the **Session pooler** string. The "Direct connection" one doesn't work from Hugging Face.
You don't need to create any tables; the app makes them on first start.

## 2. Make the Space (Hugging Face)

1. Sign in at [huggingface.co](https://huggingface.co) and go to **New Space**.
2. Name it (for example `attendance`). Choose **Docker** → **Blank**, hardware **CPU basic (free)**, and make it
   **Public**. Students must be able to open it without a Hugging Face account. The code is already public on
   GitHub; your secrets stay private.
3. Open the Space's **Settings** → **Variables and secrets** and add four **secrets**:

| Secret | Value |
|---|---|
| `DATABASE_URL` | the full line from step 1.5 |
| `GA_SECRET` | 40 or more random characters. Make some with `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `ADMIN_EMAIL` | your email. You sign in with it. |
| `ADMIN_PASSWORD` | your admin password, at least 8 characters |

Also add a **variable** (not a secret) named `TZ` with your campus time zone, for example `Asia/Dubai` or
`Asia/Riyadh`. Without it, times in the Excel files are in UTC.

Keep `GA_SECRET` the same forever. Changing it signs everyone out.

## 3. Upload the app

On your own computer, from this folder:

```powershell
pip install huggingface_hub
```

```powershell
huggingface-cli login
```

Paste a token with **Write** access from [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens).

```powershell
python scripts/deploy_space.py --space your-name/attendance
```

The Space builds for 5-10 minutes the first time. Watch the **Logs** tab on the Space page. When the status says
**Running**, the app is live.

Run the same command again whenever you change the code.

## 4. Sign in and make the doctor's account

1. Open `https://<your-name>-<space-name>.hf.space/login`. Use this address, not the huggingface.co page: inside
   that page, sign-in and the camera don't work.
2. Sign in with `ADMIN_EMAIL` and `ADMIN_PASSWORD`.
3. Click **Accounts**, then add the doctor's name and email. Leave the password empty to get a random one.
4. Send the doctor the address, their email and the password. They can change it under **Password**.

## Before each class

- **Open the site 2 minutes early.** A free Space goes to sleep after 48 hours without visitors and takes 1-2
  minutes to wake up.
- **After a long break**, Supabase pauses a free database that isn't used for 7 days. If the app shows an error,
  open your Supabase project and click **Restore project**, then wait a minute.

## If something goes wrong

- **Forgot the admin password:** add a secret `ADMIN_RESET_PASSWORD` with the value `1`, set `ADMIN_PASSWORD` to a
  new password, and restart the Space (Settings → Restart). After you sign in, delete `ADMIN_RESET_PASSWORD`.
- **The Space shows "Hosted mode needs these secrets":** one of the secrets in step 2.3 is missing or misspelled.
- **Errors mentioning the database:** check that `DATABASE_URL` is the Session pooler string with your real
  password in it, and that the Supabase project isn't paused.

## Privacy

Selfies are checked in memory and never saved. The database stores names, student IDs, check-in times and a
512-number face code per student. A doctor can delete a student's face code with **Reset** on the course page.
The face model (InsightFace) is licensed for non-commercial research use only.

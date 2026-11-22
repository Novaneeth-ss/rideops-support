# Hosting on Streamlit Community Cloud

You need a GitHub account, a Streamlit Community Cloud account (free, sign in with GitHub) and a PostgreSQL database.

1. **Database.** Create a free PostgreSQL database (Supabase, Neon or Railway) and copy its connection string, in the form
   `postgresql://USER:PASSWORD@HOST:5432/DBNAME?sslmode=require`. The app creates its tables on first start.
2. **GitHub.** Create a *private* repository and push this folder to it (`.gitignore` already keeps `store/`, secrets and caches out).
3. **Deploy.** share.streamlit.io > Create app > pick the repository, branch `main`, main file `app.py`.
   Under *Advanced settings* choose Python 3.11 or 3.12 and paste the secrets from `.streamlit/secrets.toml.example`
   with your real `DATABASE_URL` and `RIDEOPS_REQUIRE_LOGIN = "1"`.
4. **First visit.** Open the app yourself before sharing the link: the first visitor creates the administrator account.
   Then add everyone else on the Users page.
5. **Share** the app link only with the people you added. Set the app to *private* in the app's sharing settings if you also want
   Streamlit's own sign-in in front of it.

What to expect: the free tier puts the app to sleep after a few days without visits (it wakes on the next visit; your data is in the database, not on the app's disk).
The light/dark toggle needs to edit a file in the installed Streamlit package; if the host does not allow it, the app still works with Streamlit's own theme menu.
Scheduled API refresh (`python refresh.py`) cannot run on Streamlit Cloud; use a GitHub Action or any cron host with the same `DATABASE_URL`.

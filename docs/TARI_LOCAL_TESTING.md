# Testing Rudo on your Mac

This guide runs Rudo on your own MacBook in **demo mode**. You don't need any passwords or keys.

**What demo mode is:**
- **Made-up data only.** The patients, conversations, orders, referrals and staff are all invented. They live in a temporary database on your Mac, and that database is deleted when you stop Rudo.
- **No connection to real systems.** Nothing connects to the real Rudo database, Supabase, Firebase or WhatsApp. Sending a reply only saves it in the demo; no message leaves your Mac.
- **You'll always know you're in the demo.** A yellow bar across the top of every page says **SYNTHETIC DEMO**. If you don't see that bar, you are not in the demo.

You'll use the **Terminal** app (Applications → Utilities → Terminal). Type or paste each command and press **Return**.

---

## 1. Install the tools (one time, about 10 minutes)

1. **Apple's developer tools.** These include `git`.
   ```sh
   xcode-select --install
   ```
   If a window opens, click **Install**. If the message says they're already installed, that's fine.

2. **Homebrew.** This is the standard installer for Mac tools. Paste the official command from https://brew.sh:
   ```sh
   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
   ```
   When it finishes, it prints **"Next steps"** with two or three commands. Run them, because they make the `brew` command work. Then close Terminal and open it again.

3. **Python 3.12 and PostgreSQL 17:**
   ```sh
   brew install python@3.12 postgresql@17
   ```
   You don't need to start PostgreSQL yourself. Rudo's demo starts its own temporary copy.

Check that everything is there. Each command should print a version number:
```sh
git --version
brew --version
"$(brew --prefix python@3.12)/bin/python3.12" --version
"$(brew --prefix postgresql@17)/bin/postgres" --version
```

You do **not** need Docker.

## 2. Get the code

```sh
cd ~/Documents
git clone -b supabase-full-migration https://github.com/Samuel04-png/Chatbot.git rudo
cd rudo
```

This copies the project into `~/Documents/rudo` and opens that folder in Terminal. Later, to open the project folder again, run `cd ~/Documents/rudo`.

To get the latest version on another day:
```sh
cd ~/Documents/rudo
git pull
```

## 3. Start Rudo

```sh
scripts/demo_mac.sh
```

**The first time,** it sets up Python and installs the exact pinned packages, which takes a minute or two. **Every time,** it then:
1. starts a temporary database;
2. fills it with made-up data;
3. starts Rudo.

When it's ready, you'll see:
```
Rudo SYNTHETIC DEMO running: open http://127.0.0.1:5051/observer.html  (Ctrl+C to stop)
```
Leave this Terminal window open while you test.

**Safe environment.** You don't create a `.env` file for the demo. The script starts Rudo with an **empty environment**, so even if your Mac has tokens or database addresses saved, the demo ignores them.

## 4. Open the dashboard

In Safari or Chrome, go to **http://127.0.0.1:5051/observer.html**.

## 5. Choose who you are (the demo "sign-in")

The demo has no password screen. Use the **Viewing as** menu in the yellow bar to switch between demo staff:

| Viewing as | What you should see |
|---|---|
| **Operator · Facility A** (start here) | Conversations, orders and referrals for Facility A only. Can reply. |
| **Admin · all facilities + Staff** | Everything, plus the **Staff** page |
| **Analyst · analytics only** | Analytics only. Conversations, orders and referrals say "not permitted". |
| **Operator · Facility B** | A different facility's records only |
| **Operator · no records** | Empty lists, which correctly say there's nothing to show |
| **Not staff (pending)** | No records. The page says access is waiting for an administrator. |

You can also open a page directly as someone by adding `?as=` to the address, for example http://127.0.0.1:5051/observer.html?as=admin.

## 6. What to test

1. **Conversations** (as Operator):
   - Open a conversation and read its history.
   - Search by phone number, and try the filters.
   - **Reply.** In the Facility A conversation that ends with "can I visit the clinic today?", type a reply and send it.
     - It should appear in the conversation, labelled with the staff member's name.
     - Nothing is sent to WhatsApp.
     - Replies only work within 24 hours of the patient's last message. Older conversations correctly show the reply box as unavailable.
2. **Orders** and **Referrals:** the lists show exactly what the bot recorded. Missing values say "Unknown / not recorded".
3. **Analytics** (as Operator, then as Analyst): totals for users, conversations, messages, orders and referrals.
4. **Permissions:**
   - Switch to Operator · Facility B and confirm you can't see Facility A's patients.
   - Switch to Analyst and confirm only Analytics works.
5. **Staff management** (as Admin, on the **Staff** page, or at http://127.0.0.1:5051/staff.html?as=admin):
   - See staff, roles, facilities and the activity log.
   - **Invite and approve:**
     1. As Admin, create an invitation for `unknown@example.test` with role **operator** and one facility.
     2. Switch to **Not staff (pending)** and load a page. That person now appears as a pending sign-in.
     3. Switch back to Admin and **Approve** it.
     4. Switch to **Not staff (pending)** again. They now see that one facility's records.
   - Change a role, suspend and reactivate someone, and edit their facilities.

**Starting over:** stop Rudo (step 7) and start it again. Each start reloads fresh made-up data and undoes everything you changed.

## 7. Stop Rudo

Click the Terminal window that is running Rudo and press **Control + C**. It prints `Stopping and deleting the throwaway database`, which means everything is cleaned up.

## 8. Troubleshooting

| What you see | What to do |
|---|---|
| `zsh: permission denied: scripts/demo_mac.sh` | Run `chmod +x scripts/demo_mac.sh`, then try again. |
| `Homebrew is not installed` or `brew: command not found` | Do step 1.2 again, including the "Next steps" commands, then reopen Terminal. |
| `PostgreSQL 17 not found` | `brew install postgresql@17` |
| `Python 3.12 not found` | `brew install python@3.12` |
| `Something else is using port 55439` | Another database is using that port. Usually it's an earlier demo that didn't stop properly: close all Terminal windows, open a new one, and try again. |
| `Address already in use` (port 5051) | Rudo is already running in another Terminal window. Use that one, or stop it with Control + C. |
| Browser says it can't connect | Make sure the Terminal still shows `Rudo SYNTHETIC DEMO running`, and use `http://127.0.0.1:5051/...`, not `https`. |
| No yellow bar at the top | You're not on the demo. Check that the address starts with `http://127.0.0.1:5051/`. |
| Package installation fails | Check your internet connection. Then delete the Python environment with `rm -rf .venv` and run `scripts/demo_mac.sh` again. |
| A page says "source unavailable" | The temporary database stopped. Stop Rudo (Control + C) and start it again. |

## What the demo does not cover

These need the real system, and an administrator has to set them up. They are **not** part of local testing:
- **Real login.** Signing in with a real Rudo staff account (Supabase Auth: email confirmation, password reset, Google sign-in) only works on the deployed dashboard.
- **Real patient data:** real conversations, orders and referrals from the WhatsApp bot.
- **Real sending:** replies that actually reach patients on WhatsApp.
- **The WhatsApp bot itself:** it runs separately and isn't part of this dashboard.

**Never** put production passwords, database addresses, service keys, WhatsApp tokens, backups or Firebase exports on a testing Mac. The demo needs none of them.

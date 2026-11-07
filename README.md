# Job Hacker for Windows

A job-hunt workbench that runs on your own PC. Paste a link, get the job saved, move it through your pipeline, and have Claude tailor your resume and cover letter for it.

- **Add from a link.** Reads LinkedIn (public view), MyCareersFuture, and most job boards and company career pages. If a site won't share its details, paste the post's text and Claude fills in the fields.
- **Pipeline:** Saved → Applied → Interviewing → Offer → Closed, in a sortable table.
- **Fit check:** a 1–10 score against your resume and what you're looking for, with strengths, gaps and keywords.
- **Tailored resume and cover letter** per job: copy the text, edit it, or download a Word file.
- **Overnight list:** tick jobs in the Tonight column and their resumes are made at a time you choose.
- **Backup:** download everything as one file and import it on another PC.

Everything stays on your computer. The only thing sent out is the job and resume text Claude needs, sent to Anthropic when you use an AI feature.

## Install

1. Download **JobHacker.exe** from the [latest release](../../releases/latest).
2. Double-click it. Windows may say **"Windows protected your PC"** because the app isn't signed: click **More info**, then **Run anyway**. You only need to do this once.
3. Job Hacker opens in your browser. A Job Hacker icon appears in the system tray (bottom right, near the clock; it may be under the **^** arrow).

Put the exe somewhere permanent, for example `Documents\Job Hacker`, before turning on "Start when Windows starts".

## Turn on Claude

The AI features need a Claude API key. You pay Anthropic directly for what you use; a tailored resume costs a few cents.

1. Go to [console.anthropic.com](https://console.anthropic.com/settings/keys) and sign in or create an account.
2. Under **Billing**, add some credit (US$5 lasts a long time).
3. Under **API keys**, click **Create Key** and copy it.
4. In Job Hacker, open **Settings** (the gear, top right), paste the key under **Claude API key** and click **Save key**.

The key is checked with Anthropic, then stored only on this PC. Without a key you can still save and track jobs.

## Everyday use

- **Open it:** double-click JobHacker.exe again, or click the tray icon.
- **Close it:** right-click the tray icon → **Quit Job Hacker**. Closing the browser tab leaves it running in the tray.
- **Start with Windows:** right-click the tray icon → **Start when Windows starts**. It then starts quietly in the tray when you log in, which overnight runs need.
- **Overnight runs** only happen while Job Hacker is running and the PC is awake. If it was closed at the set time, the run happens the next time it starts that day.

## Your data

Everything is in `%LOCALAPPDATA%\JobHacker` (paste that into the Explorer address bar, or use the tray menu → **Open data folder**):

- `jobhacker.db`: your jobs, resumes and settings
- `jobhacker.log`: what the app did, useful if something goes wrong

To move to a new PC, use **Settings → Download backup**, then **Import backup** on the new one. The API key isn't in the backup; paste it again on the new PC.

To uninstall, quit from the tray, turn off "Start when Windows starts" first if you turned it on, then delete JobHacker.exe and the `%LOCALAPPDATA%\JobHacker` folder.

## Troubleshooting

- **Nothing happens when I double-click.** It may already be running: look for the tray icon. Otherwise check `jobhacker.log`.
- **Antivirus removed or blocked the exe.** Apps packaged this way are sometimes flagged by mistake. Restore it from quarantine or add an exception.
- **"Anthropic didn't accept that key."** Copy the key again and paste the whole thing; it starts with `sk-ant-`. Check there's credit on the account.

---

## For developers

The app is FastAPI + SQLite with a plain-JavaScript front end (`app/`, `static/`). `desktop/launcher.py` runs it on `127.0.0.1`, opens the browser and adds the tray icon; PyInstaller bundles it into one exe.

Run it from source (any OS; no tray icon outside Windows):

```sh
pip install -r requirements.txt -r desktop/requirements.txt
python desktop/launcher.py
```

Tests: `pip install pytest && pytest -q`

**Builds.** Every push to `main` runs the tests, builds `JobHacker.exe` on Windows, and checks it starts (`JobHacker.exe --check`). The exe is under the run's **Artifacts** in the Actions tab. To publish a release with a download link, either push a version tag (`git tag v1.0.1 && git push origin v1.0.1`) or go to **Actions → Build Windows app → Run workflow** and enter the version, e.g. `v1.0.1`.

Settings can be overridden with environment variables: `ANTHROPIC_API_KEY` (instead of pasting it in Settings), `CLAUDE_MODEL`, `DATA_DIR`, `TZ_NAME`.

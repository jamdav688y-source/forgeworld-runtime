# Next Right Move

A private, offline-first tool for a moment of mental overload. It walks you
through separating **what happened** from **what you're telling
yourself**, names the urge without acting on it, lists real options, and
helps you land on one small next step.

**This is not therapy, medical treatment, diagnosis, a sobriety score, or a
crisis system.** It only organizes your own thinking and reflects it back
to you — it never tells you what's true or what you should do. If you are
in immediate danger, contact local emergency services or a crisis line for
your area.

Full detail: [`docs/PRODUCT_SPEC.md`](docs/PRODUCT_SPEC.md) ·
[`docs/UX_SPEC.md`](docs/UX_SPEC.md) ·
[`docs/PRIVACY_MODEL.md`](docs/PRIVACY_MODEL.md) ·
[`docs/PRIVACY_AUDIT.md`](docs/PRIVACY_AUDIT.md) ·
[`docs/TEST_REPORT.md`](docs/TEST_REPORT.md) ·
[`RELEASE_REPORT.md`](RELEASE_REPORT.md)

## What this app stores, in one paragraph

Everything you type stays in your browser's `sessionStorage` for this
page only — never a server, never `localStorage`, never a cookie. It's
automatically erased by the browser when you close the tab/app, and you
can erase it yourself any time with the **Clear session** button at the
top of the screen. The only way anything leaves your device is if you
tap **Export as text**, which saves a plain-text file locally — nothing
is ever sent over the network. Full detail in
[`docs/PRIVACY_MODEL.md`](docs/PRIVACY_MODEL.md).

## Refresh vs. close — what to expect

- **Refreshing the page** (or accidentally reloading) keeps your progress
  — you'll land back on the same step with what you'd typed still there.
- **Closing the tab, closing the installed app, or force-closing the
  browser** erases everything immediately — this is the browser doing it,
  not a bug.
- **Clear session** erases everything immediately and takes you back to
  the start, on demand.

## Project structure

```
next-right-move/
├── index.html          the whole app shell (all screens)
├── styles.css           all styling, light + dark mode
├── app.js                all application logic (vanilla JS, no dependencies)
├── manifest.json        PWA manifest (installable to a home screen)
├── service-worker.js    offline caching of the app's own files
├── assets/               generated icons (192px, 512px)
├── docs/                  specs, privacy model/audit, test report
├── tests/                 adversarial test script (Playwright)
└── RELEASE_REPORT.md
```

Zero dependencies. Zero build step. Zero frameworks. Four files
(`index.html`, `styles.css`, `app.js`, `manifest.json` +
`service-worker.js`) are the entire application, which is deliberate — see
`docs/PRODUCT_SPEC.md` §7 for why.

## Running it in Termux (local demo, on your own phone)

This app is static files — any lightweight local HTTP server works. From
inside the `next-right-move` folder on your phone:

```bash
pkg install python -y        # first time only, if Python isn't already installed
cd next-right-move
python -m http.server 8080
```

Then open, in a browser **on the same phone**:

```
http://localhost:8080/index.html
```

Stop the server with `Ctrl+C` in Termux when you're done.

### Opening it on your phone (local demo)

If you're already on the phone running Termux, just open the URL above in
Chrome (or your default browser) on that same device. To install it to
your home screen like an app: open the page, then use your browser's menu
→ **Add to Home screen** / **Install app**.

**Important — this only works on the same phone.** `localhost` refers to
the device it's running on, so classroom neighbors on other phones
**cannot** reach `http://localhost:8080` from their own devices, even on
the same Wi-Fi. That requires a real shareable deployment — see below.

## Turning it into a shareable URL (public deployment)

Local demo mode (above) is for testing on one device. For a URL that
**other phones in the classroom can open**, put the static files on any
static-file host — no server code, no database, no environment variables
required, since this is a purely static site. Two easy free options:

1. **GitHub Pages** — push this folder's contents to a repo and enable
   Pages for it in the repo settings. You'll get a URL like
   `https://<username>.github.io/<repo>/`.
2. **Any static host** (Netlify, Vercel, Cloudflare Pages, etc.) — drag
   the `next-right-move/` folder in, or connect the repo. All of these
   serve static files with no configuration for an app like this one.

Once you have a real URL, put it here for the class:

```
SHAREABLE URL: <fill in after deployment>
```

### QR code

Most phone cameras can scan a QR code straight into the browser. Generate
one for your shareable URL with any QR generator once you have the URL
above — for example, from Termux:

```bash
pkg install qrencode -y
qrencode -t ansiutf8 "https://<your-shareable-url>"
```

This prints a scannable code directly in the terminal — no image file, no
network service needed beyond the `qrencode` package itself, and nothing
about your session data touches it (it's just a picture of a URL string).

## Browser support

Any modern mobile or desktop browser (Chrome, Firefox, Safari, Edge).
Offline support after first load requires Service Worker support, which
all of the above have. Tested primarily against Chromium at a 360×740
viewport to match a common low-end Android screen.

## License / attribution

No third-party code, fonts, or assets are used. Icons in `assets/` were
generated locally for this project.

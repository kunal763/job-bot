"""Persistent Playwright browser manager with stealth, CDP connection, and cookie sync."""

import asyncio
import shutil
import urllib.request
from pathlib import Path
from playwright.async_api import Browser, BrowserContext, Page, async_playwright
from job_bot.config import config
from job_bot.utils.logger import logger

SYSTEM_CHROME_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/152.0.7977.82 Safari/537.36"
)


class BrowserManager:
    """Manages persistent browser contexts or attaches to existing user Chrome via CDP."""

    def __init__(
        self,
        user_data_dir: Path | None = None,
        headless: bool | None = None,
        slow_mo: int | None = None,
        cdp_url: str | None = None,
    ):
        self.user_data_dir = user_data_dir or config.browser_context_dir
        self.headless = headless if headless is not None else config.headless
        self.slow_mo = slow_mo if slow_mo is not None else config.slow_mo_ms
        self.cdp_url = cdp_url or config.cdp_url
        self._playwright = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._is_cdp: bool = False

    async def start(self) -> BrowserContext:
        """Starts a persistent Chromium browser context or connects to existing Chrome via CDP."""
        if self._context:
            return self._context

        self._playwright = await async_playwright().start()

        # 1. Check if CDP URL is configured or if port 9222 is alive
        target_cdp = self.cdp_url or self._check_local_cdp_port(9222)

        if target_cdp:
            try:
                logger.info(f"Connecting to your real Chrome browser over CDP: {target_cdp}...")
                self._browser = await self._playwright.chromium.connect_over_cdp(target_cdp)
                self._context = self._browser.contexts[0] if self._browser.contexts else await self._browser.new_context()
                self._is_cdp = True
                logger.info("Successfully connected to your real Chrome browser!")
                return self._context
            except Exception as e:
                logger.warning(f"Could not connect to Chrome via CDP ({target_cdp}): {e}. Launching persistent Chrome instead.")

        # 2. Sync authentic cookies from user's primary Google Chrome profile if available
        self.user_data_dir.mkdir(parents=True, exist_ok=True)

        args = [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--disable-infobars",
            "--no-first-run",
            "--no-default-browser-check",
            "--window-size=1280,800",
        ]

        # In PRoot on Android containers, add single-process flags to prevent fork/zygote crashes
        if self._is_proot_or_android():
            args.extend([
                "--single-process",
                "--no-zygote",
            ])

        logger.info(
            f"Launching browser (headless={self.headless}, context_dir='{self.user_data_dir}')..."
        )

        # Detect system Google Chrome / Chromium executable (including Ubuntu/Debian ARM64 & PRoot)
        executable_path = self._detect_browser_executable()
        if executable_path:
            logger.info(f"Using system browser executable: {executable_path}")
        else:
            logger.info("No system Chromium detected; using Playwright bundled browser.")

        self._context = await self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(self.user_data_dir),
            executable_path=executable_path,
            headless=self.headless,
            slow_mo=self.slow_mo,
            args=args,
            ignore_default_args=["--enable-automation"],
            ignore_https_errors=True,
            user_agent=SYSTEM_CHROME_UA,
            viewport={"width": 1280, "height": 800},
            accept_downloads=True,
            locale="en-US",
            extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
        )

        # Inject stealth scripts into all new pages
        await self._context.add_init_script(
            """
            // Overwrite languages property
            Object.defineProperty(navigator, 'languages', {
              get: () => ['en-US', 'en'],
            });
            // Overwrite webdriver property
            Object.defineProperty(navigator, 'webdriver', {
              get: () => undefined,
            });
            """
        )

        # 2. Inject active authenticated LinkedIn session cookie
        active_cookie = self._get_live_chrome_cookie() or config.linkedin_cookie
        if active_cookie:
            await self.inject_linkedin_cookie(self._context, active_cookie)

        return self._context

    async def get_page(self) -> Page:
        """Returns the primary active page or creates a new one."""
        ctx = await self.start()
        if ctx.pages:
            return ctx.pages[0]
        return await ctx.new_page()

    async def close(self) -> None:
        """Closes the context and Playwright instance cleanly."""
        if self._is_cdp and self._browser:
            await self._browser.close()
            self._browser = None
        elif self._context:
            await self._context.close()
            self._context = None

        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
        logger.info("Browser session closed cleanly.")

    def _get_live_chrome_cookie(self) -> str | None:
        """Dynamically retrieves and decrypts the active LinkedIn li_at cookie from Chrome Safe Storage."""
        try:
            import sqlite3
            import secretstorage
            from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
            from cryptography.hazmat.primitives import hashes
            from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

            src_cookies = Path.home() / ".config" / "google-chrome" / "Default" / "Cookies"
            if not src_cookies.exists():
                return None

            bus = secretstorage.dbus_init()
            collection = secretstorage.get_default_collection(bus)
            secret = None
            for item in collection.get_all_items():
                if item.get_label() == "Chrome Safe Storage":
                    secret = item.get_secret()
                    break

            if not secret:
                return None

            kdf = PBKDF2HMAC(algorithm=hashes.SHA1(), length=16, salt=b"saltysalt", iterations=1)
            key = kdf.derive(secret)

            tmp_db = Path("/tmp/chrome_cookies_sync.db")
            shutil.copyfile(src_cookies, tmp_db)
            conn = sqlite3.connect(tmp_db)
            c = conn.cursor()
            rows = c.execute("SELECT encrypted_value FROM cookies WHERE host_key LIKE '%linkedin.com%' AND name='li_at'").fetchall()
            conn.close()
            tmp_db.unlink(missing_ok=True)

            for (enc_val,) in rows:
                if enc_val and enc_val[:3] == b"v11":
                    cipher = Cipher(algorithms.AES(key), modes.CBC(b" " * 16))
                    decryptor = cipher.decryptor()
                    dec = decryptor.update(enc_val[3:]) + decryptor.finalize()
                    idx = dec.find(b"AQED")
                    if idx != -1:
                        val = dec[idx:].rstrip(b"\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b\x0c\r\x0e\x0f\x10").decode("utf-8", errors="ignore")
                        if len(val) > 50:
                            logger.info("Successfully extracted active LinkedIn session token from your Google Chrome profile!")
                            return val
        except Exception as e:
            logger.debug(f"Could not extract live Chrome cookie: {e}")
        return None

    @staticmethod
    def _check_local_cdp_port(port: int = 9222) -> str | None:
        """Quickly check if Chrome remote debugging port is open on localhost."""
        url = f"http://127.0.0.1:{port}"
        try:
            req = urllib.request.Request(f"{url}/json/version", method="GET")
            with urllib.request.urlopen(req, timeout=0.5) as resp:
                if resp.status == 200:
                    return url
        except Exception:
            pass
        return None

    @staticmethod
    async def inject_linkedin_cookie(context: BrowserContext, li_at_cookie: str):
        """Injects li_at session cookie cleanly to avoid duplicate domain clashes."""
        clean_cookie = li_at_cookie.strip().strip('"').strip("'")
        await context.add_cookies([
            {
                "name": "li_at",
                "value": clean_cookie,
                "domain": ".www.linkedin.com",
                "path": "/",
                "httpOnly": True,
                "secure": True,
                "sameSite": "None",
            }
        ])

    @staticmethod
    def _is_proot_or_android() -> bool:
        """Detect whether running inside an Android PRoot container or Termux."""
        try:
            if Path("/data/data/com.termux").exists():
                return True
            proc_ver_path = Path("/proc/version")
            if proc_ver_path.exists():
                txt = proc_ver_path.read_text().lower()
                if "android" in txt or "lineage" in txt:
                    return True
        except Exception:
            pass
        return False

    @staticmethod
    def _is_real_browser(candidate: str | Path | None) -> bool:
        """Verify candidate is a real binary and not Ubuntu's dummy Snap wrapper."""
        if not candidate:
            return False
        p = Path(candidate)
        if not p.is_file():
            return False
        try:
            # Check if it's the Ubuntu snap stub script (<20KB text file with snap instructions)
            if p.stat().st_size < 20000:
                content = p.read_bytes()
                if b"snap install" in content or b"requires the chromium snap" in content:
                    return False
        except Exception:
            pass
        return True

    @classmethod
    def _detect_browser_executable(cls) -> str | None:
        """Detect system Google Chrome / Chromium executable, filtering out fake Snap wrappers."""
        for path_candidate in [
            "/usr/bin/google-chrome",
            "/usr/bin/google-chrome-stable",
            "/opt/google/chrome/chrome",
            "/usr/bin/chromium",
            shutil.which("google-chrome"),
            shutil.which("chromium"),
            shutil.which("google-chrome-stable"),
            "/usr/bin/chromium-browser",
            shutil.which("chromium-browser"),
        ]:
            if path_candidate and cls._is_real_browser(path_candidate):
                return str(path_candidate)
        return None

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

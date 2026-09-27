"""CLI interface for Job Bot."""

import asyncio
from pathlib import Path
from typing import Optional
import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from job_bot.config import config
from job_bot.copilot.llm import AICopilot
from job_bot.db.repository import JobRepository
from job_bot.engine.browser import BrowserManager
from job_bot.engine.platforms import LinkedInPlatform, WellfoundPlatform
from job_bot.engine.salary_parser import evaluate_salary
from job_bot.models import ApplicationStatus, JobListing
from job_bot.utils.logger import console, logger, print_jobs_table
from job_bot.vault.profile_vault import ProfileVault

app = typer.Typer(
    name="job-bot",
    help="🤖 Autonomous Multi-Site Job Seeker & Application Agent (12+ LPA Filter)",
    add_completion=False,
)
db_app = typer.Typer(help="Database management & tracking commands")
app.add_typer(db_app, name="db")


@app.command()
def login(
    platform: str = typer.Option("linkedin", "--platform", "-p", help="Target platform (linkedin)"),
    cdp: bool = typer.Option(False, "--cdp", help="Connect to already open Chrome via remote debugging (port 9222)"),
):
    """Open an interactive browser to log into your account and persist session cookies."""
    console.print(Panel(
        f"[bold cyan]Opening browser session for {platform.upper()}...[/bold cyan]\n\n"
        "• If logging in with [bold]Email & Password[/bold]: Enter credentials and solve any captcha.\n"
        "• If Google login says [yellow]'browser not secure'[/yellow]: Use LinkedIn Email/Password directly,\n"
        "  or use your [bold]li_at[/bold] cookie with [cyan]job-bot set-cookie <COOKIE>[/cyan],\n"
        "  or launch your real Chrome using [cyan]job-bot launch-chrome[/cyan]!\n\n"
        "Once logged in, press [bold green]ENTER[/bold green] in this terminal to save session cookies.",
        title="🔑 Session Login",
        border_style="cyan",
    ))

    async def _login():
        mgr = BrowserManager(headless=False, slow_mo=50, cdp_url="http://127.0.0.1:9222" if cdp else None)
        async with mgr:
            page = await mgr.get_page()
            if platform.lower() == "wellfound":
                url = "https://wellfound.com/login"
            elif platform.lower() == "linkedin":
                url = "https://www.linkedin.com/login"
            else:
                url = "https://www.google.com"
            logger.info(f"Navigating to {url}...")
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)

            input("\nPress ENTER after you have logged in and reached your feed/dashboard: ")
            console.print("[green]Session saved to persistent storage![/green]")

    asyncio.run(_login())


@app.command("launch-chrome")
def launch_chrome():
    """Launch Google Chrome with remote debugging on port 9222 so Job Bot can connect to it."""
    import subprocess
    console.print(Panel(
        "[bold cyan]Launching Google Chrome with Remote Debugging (port 9222)...[/bold cyan]\n\n"
        "1. Chrome will open in a clean dedicated session without any automation flags.\n"
        "2. Log into LinkedIn (supports Google SSO, Email/Pass, 2FA with zero 'not secure' warnings!).\n"
        "3. Keep this Chrome window open while running Job Bot search and apply commands.",
        title="🌐 Chrome Remote Debugging",
        border_style="green",
    ))
    bot_profile = Path.home() / ".config" / "google-chrome-bot"
    cmd = [
        "/usr/bin/google-chrome",
        "--remote-debugging-port=9222",
        f"--user-data-dir={bot_profile}",
        "https://www.linkedin.com/login",
    ]
    subprocess.Popen(cmd)
    console.print(f"[bold green]Chrome launched![/bold green] Debugger active at [cyan]http://localhost:9222[/cyan].")


@app.command("set-cookie")
def set_cookie(
    cookie_value: str = typer.Argument(..., help="Value of the LinkedIn 'li_at' cookie from your browser"),
):
    """Save your LinkedIn 'li_at' session cookie to .env for instant passwordless authentication."""
    env_path = Path(".env")
    env_content = ""
    if env_path.exists():
        env_content = env_path.read_text(encoding="utf-8")

    lines = env_content.splitlines()
    found = False
    new_lines = []
    for line in lines:
        if line.startswith("LINKEDIN_COOKIE="):
            new_lines.append(f"LINKEDIN_COOKIE={cookie_value.strip()}")
            found = True
        else:
            new_lines.append(line)

    if not found:
        new_lines.append(f"LINKEDIN_COOKIE={cookie_value.strip()}")

    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    console.print(Panel(
        "[bold green]LinkedIn session cookie saved successfully to .env![/bold green]\n"
        "Job Bot will now automatically authenticate using your active session with zero login prompts.",
        title="🍪 Cookie Configured",
        border_style="green",
    ))


@app.command()
def profile(
    profile_file: Optional[Path] = typer.Option(None, "--profile", "-f", help="Path to profile JSON"),
):
    """Validate and display the candidate profile vault."""
    vault = ProfileVault(profile_file)
    try:
        prof = vault.load()
    except Exception as e:
        console.print(f"[bold red]Profile validation failed:[/bold red] {e}")
        raise typer.Exit(code=1)

    table = Table(title="👤 Candidate Profile Vault", border_style="blue")
    table.add_column("Category", style="bold cyan")
    table.add_column("Details", style="white")

    table.add_row("Name", f"{prof.personal.first_name} {prof.personal.last_name}")
    table.add_row("Contact", f"{prof.personal.email} | {prof.personal.phone}")
    table.add_row("Location", prof.personal.location)
    table.add_row("Current Role", f"{prof.career.current_title} ({prof.career.total_years_experience} yrs exp)")
    table.add_row("Compensation", f"Current: {prof.career.current_ctc_lpa or 'N/A'} LPA | Expected: {prof.career.expected_ctc_lpa} LPA")
    table.add_row("Notice Period", f"{prof.career.notice_period_days} days")
    table.add_row("Education", f"{prof.education.degree} ({prof.education.field_of_study}), {prof.education.university}")
    table.add_row("Resume PDF", f"[green]{prof.documents.resume_path}[/green]")
    table.add_row("Skills", ", ".join(prof.career.skills[:8]) + ("..." if len(prof.career.skills) > 8 else ""))

    console.print(table)


def is_tech_role(title: str) -> bool:
    """Filter out clearly non-tech or non-software roles."""
    t = title.lower()
    non_tech_terms = [
        "sales", "recruiter", "talent acquisition", "hr ", "human resources",
        "accountant", "accounting", "marketing", "content writer", "telecaller",
        "bpo", "customer support", "campus ambassador", "graphic designer",
        "video editor", "creative design", "business development", "receptionist",
    ]
    for term in non_tech_terms:
        if term in t:
            return False
    return True


@app.command()
def search(
    keywords: list[str] = typer.Option(["Python", "Developer"], "--keyword", "-k", help="Search keywords"),
    location: str = typer.Option("India", "--location", "-l", help="Target location"),
    min_lpa: float = typer.Option(config.min_salary_lpa, "--min-lpa", "-m", help="Minimum salary threshold in LPA"),
    allow_unlisted: bool = typer.Option(config.allow_unlisted_salary, "--allow-unlisted", help="Include listings without salary"),
    limit: int = typer.Option(10, "--limit", "-n", help="Max jobs to scrape per keyword"),
    headless: bool = typer.Option(config.headless, "--headless", help="Run browser in headless mode"),
    platform: str = typer.Option("all", "--platform", "-p", help="Platform to search ('all', 'linkedin', 'wellfound')"),
    separate_keywords: bool = typer.Option(True, "--separate/--combined", help="Search each keyword separately instead of joining them"),
):
    """Search job listings, apply salary filtering (13+ LPA), and store matches in DB."""
    repo = JobRepository()

    async def _search():
        mgr = BrowserManager(headless=headless)
        async with mgr:
            page = await mgr.get_page()
            vault_profile = ProfileVault().profile
            copilot_instance = AICopilot(vault_profile)

            plat_list = []
            if platform.lower() in ["all", "linkedin"]:
                plat_list.append(LinkedInPlatform(page, vault_profile, copilot_instance, repo))
            if platform.lower() in ["all", "wellfound"]:
                plat_list.append(WellfoundPlatform(page, vault_profile, copilot_instance, repo))

            all_jobs = []
            matched_jobs = []
            keyword_batches = [[kw] for kw in keywords] if separate_keywords and len(keywords) > 1 else [keywords]

            for kw_group in keyword_batches:
                kw_label = " ".join(kw_group)
                console.print(f"\n[bold cyan]🔍 Scouting jobs for keyword: '{kw_label}' in {location}...[/bold cyan]")
                for p in plat_list:
                    try:
                        jobs = await p.search_jobs(keywords=kw_group, location=location, limit=limit)
                        all_jobs.extend(jobs)
                        for j in jobs:
                            meets, info = evaluate_salary(j.salary_raw, threshold_lpa=min_lpa, allow_unlisted=allow_unlisted)
                            j.salary_info = info
                            tech_match = is_tech_role(j.title)
                            status = ApplicationStatus.QUEUED if (meets and tech_match) else ApplicationStatus.FILTERED_OUT
                            repo.save_job(j, initial_status=status)
                            if meets and tech_match:
                                matched_jobs.append(j)
                    except Exception as e:
                        logger.error(f"Error searching on {p.__class__.__name__} for {kw_label}: {e}")

            console.print(f"\n[bold green]Found {len(all_jobs)} total jobs, {len(matched_jobs)} match tech & >= {min_lpa} LPA criteria.[/bold green]")

    asyncio.run(_search())


@app.command()
def apply(
    job_id: Optional[str] = typer.Option(None, "--job-id", "-j", help="Specific job ID from DB to apply to"),
    platform: Optional[str] = typer.Option(None, "--platform", "-p", help="Filter by platform ('linkedin', 'wellfound')"),
    dry_run: bool = typer.Option(True, "--dry-run/--live", help="Dry run tests form filling without final submission"),
    headless: bool = typer.Option(config.headless, "--headless", help="Run browser in headless mode"),
    limit: Optional[int] = typer.Option(None, "--limit", "-n", help="Max jobs to process (default: all queued)"),
    min_lpa: Optional[float] = typer.Option(None, "--min-lpa", "-m", help="Minimum salary in LPA to apply to"),
    allow_unlisted: bool = typer.Option(False, "--allow-unlisted", help="Include listings without salary"),
):
    """Apply to queued jobs with form filling and AI copilot."""
    repo = JobRepository()
    vault = ProfileVault()
    profile_data = vault.profile
    copilot = AICopilot(profile_data)

    async def _apply():
        mgr = BrowserManager(headless=headless)
        async with mgr:
            page = await mgr.get_page()
            linkedin_platform = LinkedInPlatform(page, profile_data, copilot, repo)
            wellfound_platform = WellfoundPlatform(page, profile_data, copilot, repo)

            if job_id:
                apps = [a for a in repo.get_applications() if a["id"] == job_id]
            else:
                apps = repo.get_applications(status=ApplicationStatus.QUEUED)
                if platform:
                    apps = [a for a in apps if a.get("platform") == platform.lower()]

            if min_lpa is not None:
                filtered_apps = []
                for a in apps:
                    meets, _ = evaluate_salary(a.get("salary_raw"), threshold_lpa=min_lpa, allow_unlisted=allow_unlisted)
                    if meets:
                        filtered_apps.append(a)
                    else:
                        repo.update_application_status(
                            job_id=a["id"],
                            status=ApplicationStatus.FILTERED_OUT,
                            notes=f"Below {min_lpa} LPA threshold ({a.get('salary_raw')})",
                        )
                apps = filtered_apps

            if not apps:
                target_desc = f" for platform '{platform}'" if platform else ""
                sal_desc = f" matching >= {min_lpa} LPA" if min_lpa else ""
                console.print(f"[yellow]No queued jobs available to apply to{target_desc}{sal_desc}. Run 'job-bot search' first![/yellow]")
                return

            if not job_id and limit and limit > 0:
                apps = apps[:limit]

            console.print(f"[bold cyan]Processing {len(apps)} job(s) (Dry Run = {dry_run})...[/bold cyan]")

            for a in apps:
                from job_bot.models import JobListing, SalaryInfo
                job = JobListing(
                    id=a["id"],
                    platform=a.get("platform", "linkedin"),
                    external_job_id=a["external_job_id"],
                    title=a["title"],
                    company=a["company"],
                    location=a.get("location"),
                    salary_raw=a.get("salary_raw"),
                    url=a["url"],
                    easy_apply=bool(a.get("easy_apply", 1)),
                )

                console.print(f"\n[bold]Targeting ({job.platform.upper()}):[/bold] {job.title} at {job.company}")
                active_platform = wellfound_platform if job.platform == "wellfound" else linkedin_platform
                try:
                    success, message = await active_platform.apply_to_job(job, dry_run=dry_run)
                except Exception as e:
                    logger.error(f"Error applying to {job.title}: {e}")
                    success, message = False, f"Error: {e}"

                if "Skipped" in message or "skipped" in message:
                    new_status = ApplicationStatus.SKIPPED
                    result_badge = "[bold yellow]SKIPPED[/bold yellow]"
                elif success:
                    new_status = ApplicationStatus.APPLIED if not dry_run else ApplicationStatus.QUEUED
                    result_badge = "[bold green]SUCCESS[/bold green]"
                else:
                    new_status = ApplicationStatus.FAILED
                    result_badge = "[bold red]FAILED[/bold red]"
                
                # Retrieve custom answers log
                answers = getattr(active_platform, "answers_log", None) or (
                    getattr(getattr(active_platform, "form_filler", None), "answers_log", None) or {}
                )
                repo.update_application_status(
                    job_id=job.id,
                    status=new_status,
                    notes=f"{'[DRY RUN] ' if dry_run else ''}{message}",
                    error_message=None if success else message,
                    custom_answers=answers,
                )

                console.print(f"Result: {result_badge} - {message}")

    asyncio.run(_apply())


@app.command()
def run(
    keywords: list[str] = typer.Option(["Python", "Backend"], "--keyword", "-k", help="Keywords"),
    location: str = typer.Option("India", "--location", "-l", help="Location"),
    min_lpa: float = typer.Option(config.min_salary_lpa, "--min-lpa", "-m", help="Minimum salary in LPA"),
    allow_unlisted: bool = typer.Option(config.allow_unlisted_salary, "--allow-unlisted", help="Allow unlisted salary"),
    dry_run: bool = typer.Option(True, "--dry-run/--live", help="Dry run mode for safe form verification"),
    headless: bool = typer.Option(config.headless, "--headless", help="Run browser in headless mode"),
    limit: int = typer.Option(10, "--limit", "-n", help="Max jobs to search"),
    platform: str = typer.Option("all", "--platform", "-p", help="Target platform ('all', 'linkedin', 'wellfound')"),
    separate_keywords: bool = typer.Option(True, "--separate/--combined", help="Search each keyword separately instead of joining them"),
):
    """End-to-end pipeline: search, filter (>= 13 LPA), deduplicate, and apply."""
    console.print(Panel(
        f"[bold green]Starting Autonomous Job Search & Application Cycle[/bold green]\n"
        f"Platform: {platform.upper()} | Keywords: {keywords} | Location: {location}\n"
        f"Filter: >= {min_lpa} LPA (Allow unlisted: {allow_unlisted})\n"
        f"Mode: {'[yellow]DRY RUN (Safe Verification)[/yellow]' if dry_run else '[bold red]LIVE APPLY[/bold red]'}",
        title="🚀 Job Bot Runner",
        border_style="green",
    ))

    # Step 1: Search and Filter
    search(
        keywords=keywords,
        location=location,
        min_lpa=min_lpa,
        allow_unlisted=allow_unlisted,
        limit=limit,
        headless=headless,
        platform=platform,
        separate_keywords=separate_keywords,
    )

    # Step 2: Apply
    apply(
        platform=None if platform.lower() == "all" else platform.lower(),
        dry_run=dry_run,
        headless=headless,
        limit=limit,
        min_lpa=min_lpa,
        allow_unlisted=allow_unlisted,
    )


@db_app.command("list")
def db_list(
    status: Optional[str] = typer.Option(None, "--status", "-s", help="Filter by status (QUEUED, APPLIED, etc.)"),
):
    """List jobs and their tracking status from SQLite database."""
    repo = JobRepository()
    st = ApplicationStatus(status) if status else None
    jobs = repo.get_applications(status=st)
    print_jobs_table(jobs)


@db_app.command("stats")
def db_stats():
    """Show database summary statistics."""
    repo = JobRepository()
    jobs = repo.get_applications()

    status_counts = {}
    for j in jobs:
        st = j.get("status", "UNKNOWN")
        status_counts[st] = status_counts.get(st, 0) + 1

    table = Table(title="📊 Job Bot Database Statistics", border_style="magenta")
    table.add_column("Status", style="bold")
    table.add_column("Count", justify="right", style="cyan")

    for st, count in status_counts.items():
        table.add_row(st, str(count))
    table.add_row("[bold]Total Jobs[/bold]", f"[bold]{len(jobs)}[/bold]")

    console.print(table)


@app.command("apply-external")
def apply_external(
    url: str = typer.Argument(..., help="External job application URL (Greenhouse, Lever, Ashby, Workday, etc.)"),
    dry_run: bool = typer.Option(True, "--dry-run/--live", help="Dry run tests form filling without final submission"),
    headless: bool = typer.Option(False, "--headless/--no-headless", help="Run browser in headless mode (default: False to watch live)"),
):
    """Autonomously fill any external job application using Groq AI Copilot."""
    from job_bot.engine.external_filler import ExternalFormFiller
    repo = JobRepository()
    vault = ProfileVault()
    profile_data = vault.profile
    copilot = AICopilot(profile_data)

    console.print(Panel(
        f"[bold cyan]Launching Universal AI Form Filler for External Application[/bold cyan]\n\n"
        f"URL: [underline]{url}[/underline]\n"
        f"AI Engine: [bold green]Groq ({config.groq_model})[/bold green]\n"
        f"Mode: {'[yellow]DRY RUN (Safe verification)[/yellow]' if dry_run else '[bold red]LIVE APPLY[/bold red]'}\n"
        f"Browser: {'[cyan]Headless[/cyan]' if headless else '[green]Interactive / Visible[/green]'}",
        title="🌐 External Application Copilot",
        border_style="cyan",
    ))

    async def _fill():
        mgr = BrowserManager(headless=headless, slow_mo=config.slow_mo_ms)
        async with mgr:
            page = await mgr.get_page()
            logger.info(f"Navigating to external job: {url}...")
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            filler = ExternalFormFiller(page, profile_data, copilot, repo)
            success, message = await filler.fill_and_submit(dry_run=dry_run)
            console.print(f"\nResult: {'[bold green]SUCCESS[/bold green]' if success else '[bold red]FAILED[/bold red]'} - {message}")
            if success:
                page_title = (await page.title()) or "External Job Application"
                import hashlib
                url_hash = hashlib.md5(url.encode()).hexdigest()[:10]
                job_record = JobListing(
                    id=f"external_{url_hash}",
                    platform="external",
                    external_job_id=url_hash,
                    title=page_title,
                    company="External Company",
                    url=url,
                    easy_apply=False,
                )
                repo.save_job(job_record, initial_status=ApplicationStatus.QUEUED)
                repo.update_application_status(
                    job_id=job_record.id,
                    status=ApplicationStatus.APPLIED if not dry_run else ApplicationStatus.QUEUED,
                    notes=f"{'[DRY RUN] ' if dry_run else ''}{message}",
                    custom_answers=filler.answers_log,
                )
            if not headless:
                await asyncio.sleep(4.0)

    asyncio.run(_fill())


@app.command("update-wellfound-profile")
def update_wellfound_profile_cmd(
    headless: bool = typer.Option(True, "--headless/--no-headless", help="Run browser in headless mode (default: True)"),
):
    """Automatically populate and optimize Wellfound profile (Bio, Socials, Brag sheet, Work experiences, Skills, Projects)."""
    from job_bot.engine.wellfound_profile_updater import optimize_wellfound_profile
    console.print(Panel(
        "[bold cyan]Optimizing and Completing Wellfound Profile[/bold cyan]\n\n"
        "• Elevator Pitch Bio\n"
        "• Social Links (LinkedIn, GitHub, Website)\n"
        "• 'What I've Built' Brag Sheet (All Projects & ICPC)\n"
        "• Work Experiences (Humming Bird L2, Tarana Wireless, ZF Group, Sphyzee)\n"
        "• Core Skills (C++, FastAPI, Redis, Docker, Spring Boot, PostGIS, REST APIs)",
        title="🌟 Wellfound Profile Optimizer",
        border_style="cyan",
    ))
    asyncio.run(optimize_wellfound_profile())
    console.print("[bold green]✔ Wellfound profile optimization complete![/bold green]")


def main():
    app()



if __name__ == "__main__":
    main()

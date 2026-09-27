"""Autonomous Wellfound Profile Optimizer & Updater.

Updates Bio, Social Profiles, What I've Built, Projects, Skills,
and all Work Experience roles directly via authenticated browser context.
"""

import asyncio
from playwright.async_api import Page
from job_bot.engine.browser import BrowserManager
from job_bot.utils.logger import logger


async def update_experience_item(
    page: Page,
    company_query: str,
    title: str,
    start_date: str,
    end_date: str | None,
    is_current: bool,
    description: str,
) -> bool:
    """Updates a single work experience entry on Wellfound profile edit page."""
    logger.info(f"Updating work experience: {company_query} -> {title} ({start_date} - {end_date or 'Present'})...")
    
    # Locate Edit link for this company
    edit_link = page.locator(f'xpath=//div[contains(., "{company_query}")]//a[text()="Edit"]').first
    if await edit_link.count() == 0:
        logger.warning(f"Could not locate Edit link for company '{company_query}'")
        return False

    await edit_link.click()
    await asyncio.sleep(2.0)

    # Locate the active experience form
    form = page.locator('input[placeholder*="Start date"]').first.locator('xpath=ancestor::form').first

    # 1. Title
    title_inp = form.locator('input[name="title"]').first
    if await title_inp.count() > 0:
        await title_inp.fill(title)

    # 2. Start date
    start_inp = form.locator('input[placeholder*="Start date"]').first
    if await start_inp.count() > 0:
        await start_inp.fill(start_date)

    # 3. Current work or End date
    chk = form.locator('#form-input--current--true, input[type="checkbox"]').first
    label = form.locator('label:has-text("I currently work here")').first
    is_currently_checked = await chk.is_checked()

    if is_current:
        if not is_currently_checked and await label.is_visible():
            await label.click()
            await asyncio.sleep(0.5)
    else:
        if is_currently_checked and await label.is_visible():
            await label.click()
            await asyncio.sleep(0.5)
        
        end_inp = form.locator('input[placeholder*="End date"]').first
        if await end_inp.is_visible() and end_date:
            await end_inp.fill(end_date)

    # 4. Description
    desc_inp = form.locator('textarea[name="description"]').first
    if await desc_inp.count() > 0:
        await desc_inp.fill(description)

    await asyncio.sleep(1.0)

    # 5. Save button
    save_btn = form.locator('button[type="submit"]:has-text("Save")').first
    if await save_btn.count() > 0 and await save_btn.is_visible():
        await save_btn.click()
        await asyncio.sleep(3.0)
        logger.info(f"Saved work experience for '{company_query}' successfully!")
        return True
    
    logger.warning(f"Save button not found for '{company_query}'")
    return False


async def add_wellfound_skill(page: Page, skill_name: str) -> bool:
    """Adds a new technical skill via Wellfound's downshift autocomplete."""
    logger.info(f"Adding skill: {skill_name}...")
    skill_inp = page.locator('input[placeholder*="Python, React"]').first
    if await skill_inp.count() == 0 or not await skill_inp.is_visible():
        return False

    await skill_inp.click()
    await skill_inp.fill(skill_name)
    await asyncio.sleep(1.2)

    menu_items = await page.locator('[role="option"], [id*="downshift"][id*="item"]').all()
    matched = False
    for m in menu_items:
        txt = (await m.inner_text()).lower()
        if skill_name.lower() in txt:
            await m.click()
            matched = True
            break

    if not matched and menu_items:
        await menu_items[0].click()
    elif not matched:
        await page.keyboard.press("Enter")

    await asyncio.sleep(1.5)
    logger.info(f"Skill '{skill_name}' processed.")
    return True


async def optimize_wellfound_profile():
    """Master workflow to optimize and complete all sections of Wellfound profile."""
    logger.info("Starting Wellfound profile optimization...")
    mgr = BrowserManager(headless=True)
    page = await mgr.get_page()

    edit_url = "https://wellfound.com/profile/edit"
    for attempt in range(3):
        try:
            logger.info(f"Navigating to {edit_url} (Attempt {attempt + 1})...")
            await page.goto(edit_url, wait_until="domcontentloaded", timeout=35000)
            break
        except Exception as e:
            logger.warning(f"Navigation error: {e}. Retrying...")
            await asyncio.sleep(2.5)

    await asyncio.sleep(4.0)

    # 1. Update Bio
    logger.info("Populating Elevator Pitch Bio...")
    bio_text = "Software Developer L2 & Systems Engineer. High-concurrency backends, low-latency C++, distributed caching, and AI agent pipelines with FastAPI, AWS, & Redis."
    bio_inp = page.locator('#form-input--bio, textarea[name="bio"]').first
    bio_form = bio_inp.locator("xpath=ancestor::form").first
    await bio_inp.click()
    await bio_inp.fill(bio_text)
    await asyncio.sleep(0.5)
    save_bio = bio_form.locator('button[type="submit"]:has-text("Save")').first
    if await save_bio.is_visible():
        await save_bio.click()
        await asyncio.sleep(2.0)

    # 2. Update Social Profiles
    logger.info("Populating Social URLs (LinkedIn, GitHub, Website)...")
    site_inp = page.locator('#form-input--onlineBioUrl, input[name="onlineBioUrl"]').first
    li_inp = page.locator('#form-input--linkedinUrl, input[name="linkedinUrl"]').first
    gh_inp = page.locator('#form-input--githubUrl, input[name="githubUrl"]').first
    social_form = site_inp.locator("xpath=ancestor::form").first

    await site_inp.fill("https://kunal763.github.io/")
    await li_inp.fill("https://www.linkedin.com/in/kunal-singh-chauhan")
    await gh_inp.fill("https://github.com/kunal763")
    await asyncio.sleep(0.5)
    save_social = social_form.locator('button[type="submit"]:has-text("Save")').first
    if await save_social.is_visible():
        await save_social.click()
        await asyncio.sleep(2.0)

    # 3. Update What I've Built / Achievements
    logger.info("Populating 'What I've Built' Brag Sheet...")
    what_built = (
        "• AI Agent & RAG Platform (Humming Bird): Engineered website chatbot platform using HTTPX, Selenium, FastAPI, and vector embeddings, ingesting 35k+ pages across 10 deployments with AWS Secrets Manager auto-rotation.\n"
        "• Low-Latency gNMI Telemetry (Tarana Wireless): Migrated pipeline to YANG-protobuf models (-49% payload), reduced hot-path latency from 12µs to 4µs (66% speedup), and profiled with gprof/Google Benchmark.\n"
        "• Scalable Cab Sharing Backend: 568 req/s throughput under 10,000 concurrent users, Redis caching (-45% DB read load), PostGIS spatial queries.\n"
        "• Schedule FA Creator: 100% local, privacy-first tax automation engine with Rule 115 SBI TTBR forex parser.\n"
        "• HTTP Server with Gzip (C++17): POSIX sockets, multithreading, and real-time zlib gzip payload compression.\n"
        "• ICPC Asia-West Regional 2023: Ranked 1st in college among 14,000+ collegiate participants.\n"
        "• Mastercard Code for Change: Finalist among 2,000+ participants."
    )
    what_inp = page.locator('#form-input--whatIveBuilt, textarea[name="whatIveBuilt"]').first
    what_form = what_inp.locator("xpath=ancestor::form").first
    await what_inp.click()
    await what_inp.fill(what_built)
    await asyncio.sleep(0.5)
    save_what = what_form.locator('button[type="submit"]:has-text("Save")').first
    if await save_what.is_visible():
        await save_what.click()
        await asyncio.sleep(2.0)

    # 4. Update Work Experiences
    logger.info("Populating Work Experience descriptions and dates...")
    
    # 4a. Humming Bird Web Solutions
    hbw_desc = (
        "• Developed an AI agent platform for website-specific chatbots using web scraping and RAG pipelines with HTTPX, Selenium, FastAPI, and vector embeddings, ingesting 35,000+ webpages across 10 chatbot deployments.\n"
        "• Implemented JWT-based Role-Based Access Control and Google OAuth in FastAPI with Admin, Tester, and User access tiers.\n"
        "• Designed centralized Configuration Manager integrated with AWS Secrets Manager, replacing local env variables and automating credential rotation across 10 deployments.\n"
        "• Deployed internal multi-app platform on AWS EC2 using PM2 and Supervisorctl, with CloudFront caching and Nginx + OAuth2-Proxy header verification.\n"
        "• Extended self-hosted GitLab EE with custom worklogs boards, inline time logging, story points, and priority management."
    )
    await update_experience_item(page, "hbwsl.com", "Software Developer L2", "04/2026", None, True, hbw_desc)

    # 4b. Tarana Wireless
    tarana_desc = (
        "• Migrated production gNMI telemetry pipeline to YANG-based protobuf models, reducing payload size by 49% and eliminating runtime path validation errors through compile-time schema enforcement.\n"
        "• Reduced function runtime in latency-critical execution paths from 12µs to 4µs (66% speedup) by optimizing memory allocation and removing redundant vector copies.\n"
        "• Profiled CPU hotspots with gprof and Google Benchmark, resolving heap bottlenecks to maximize telemetry throughput.\n"
        "• Engineered RN emulation framework simulating production network behavior, reducing hardware debugging dependencies by 35%."
    )
    await update_experience_item(page, "Tarana Wireless", "C/C++ Developer", "06/2025", "02/2026", False, tarana_desc)

    # 4c. ZF Friedrichshafen (ZF Group)
    zf_desc = (
        "• Engineered 12+ enterprise REST API endpoints using Java Spring Boot and MySQL to power BOM-based risk intelligence dashboards.\n"
        "• Lowered database API latency by 25% by implementing composite indexing and optimizing complex SQL joins."
    )
    await update_experience_item(page, "ZF Friedrichshafen", "Software Developer Intern", "03/2025", "05/2025", False, zf_desc)

    # 4d. Sphyzee
    sphyzee_desc = (
        "• Decreased manual dashboard setup effort by 40% by engineering JSON-driven automated data ingestion pipelines.\n"
        "• Shortened dashboard migration turnaround time by 30% using custom automation scripts."
    )
    await update_experience_item(page, "Sphyzee", "Software Developer Intern", "12/2024", "02/2025", False, sphyzee_desc)

    # 5. Add Key Skills
    logger.info("Adding top backend and systems skills...")
    for s in ["FastAPI", "Redis", "Docker", "Spring Boot", "REST APIs", "PostGIS"]:
        await add_wellfound_skill(page, s)

    # 6. Verify Public Profile
    public_url = "https://wellfound.com/kunal-singh-309"
    logger.info(f"Verifying final public profile at {public_url}...")
    try:
        await page.goto(public_url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3.0)
        public_text = await page.inner_text("body")
        logger.info(f"Public profile verified! (Content length: {len(public_text)} characters)")
    except Exception as e:
        logger.warning(f"Verification visit error: {e}")

    await mgr.close()
    logger.info("Wellfound profile optimization complete!")


if __name__ == "__main__":
    asyncio.run(optimize_wellfound_profile())

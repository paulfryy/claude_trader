"""
Email the end-of-day report to the user's inbox.

Uses Gmail SMTP with an app password. Configured via .env:
  GMAIL_EMAIL, GMAIL_APP_PASSWORD — sender credentials
  NOTIFY_EMAIL — where to send reports (can be same as sender)

If any are missing, emailing is silently skipped.
"""

import logging
import os
import smtplib
from email.message import EmailMessage
from pathlib import Path

import markdown

logger = logging.getLogger(__name__)


def send_eod_report_email(report_path: Path, mode: str) -> bool:
    """
    Send an EOD report markdown file as an HTML email.

    Returns True if sent successfully, False otherwise.
    """
    gmail_email = os.environ.get("GMAIL_EMAIL", "")
    gmail_password = os.environ.get("GMAIL_APP_PASSWORD", "")
    notify_email = os.environ.get("NOTIFY_EMAIL", "")

    if not (gmail_email and gmail_password and notify_email):
        logger.info(
            "Email not configured (GMAIL_EMAIL, GMAIL_APP_PASSWORD, NOTIFY_EMAIL) — skipping"
        )
        return False

    if not report_path or not report_path.exists():
        logger.warning("EOD report file not found at %s, skipping email", report_path)
        return False

    try:
        content = report_path.read_text(encoding="utf-8")
    except Exception as e:
        logger.error("Failed to read EOD report for email: %s", e)
        return False

    # Build the email
    date_str = report_path.stem
    mode_label = "LIVE" if mode == "live" else "PAPER"
    subject = f"[{mode_label}] Trading Agent — {date_str}"

    # Render markdown to HTML with some basic styling
    html_body = markdown.markdown(content, extensions=["tables", "fenced_code"])
    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
          max-width: 800px; margin: 20px auto; padding: 0 20px; color: #2d3748; line-height: 1.6; }}
  h1 {{ color: #1a202c; border-bottom: 2px solid #e2e8f0; padding-bottom: 8px; }}
  h2 {{ color: #2d3748; margin-top: 30px; border-bottom: 1px solid #edf2f7; padding-bottom: 4px; }}
  h3 {{ color: #4a5568; }}
  table {{ border-collapse: collapse; width: 100%; margin: 15px 0; font-size: 14px; }}
  th, td {{ border: 1px solid #e2e8f0; padding: 8px 12px; text-align: left; }}
  th {{ background: #f7fafc; font-weight: 600; }}
  tr:nth-child(even) {{ background: #f9fafb; }}
  blockquote {{ border-left: 3px solid #4299e1; padding: 10px 15px; margin: 10px 0;
               background: #ebf8ff; color: #2c5282; font-style: italic; }}
  code {{ background: #edf2f7; padding: 2px 6px; border-radius: 3px; font-family: monospace; }}
  ul {{ margin: 10px 0 10px 20px; }}
  li {{ margin: 4px 0; }}
  .footer {{ margin-top: 40px; padding-top: 20px; border-top: 1px solid #e2e8f0;
             color: #718096; font-size: 12px; }}
</style>
</head>
<body>
{html_body}
<div class="footer">
  Sent by your Claude Trading Agent. View the full dashboard at your EC2 instance.
</div>
</body>
</html>"""

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = gmail_email
    msg["To"] = notify_email

    # Plain text fallback = raw markdown
    msg.set_content(content)
    msg.add_alternative(html, subtype="html")

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(gmail_email, gmail_password)
            server.send_message(msg)
        logger.info("EOD report emailed to %s", notify_email)
        return True
    except Exception as e:
        logger.error("Failed to send EOD report email: %s", e)
        return False

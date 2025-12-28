import smtplib
from email.message import EmailMessage
import os

class EmailService:
    def __init__(self):
        self.smtp_server = "smtp.gmail.com"
        self.smtp_port = 587
        self.smtp_username = os.getenv("SMTP_USERNAME")
        self.smtp_password = os.getenv("SMTP_PASSWORD")

    def send_verification_email(self, email_id: str, verification_code: str, user_id: str):
        msg = EmailMessage()
        link = f"http://localhost:8080/auth/verify-email?verification_code={verification_code}&user_id={user_id}"
        msg.set_content(f"Welcome to the ReadMyBook platform. Please click on the link to verify your email: {link}")
        msg["Subject"] = "Verification Code"
        msg["From"] = self.smtp_username
        msg["To"] = email_id
        with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
            server.starttls()
            server.login(self.smtp_username, self.smtp_password)
            server.send_message(msg)
            print("Verification email sent successfully")
    
    def send_verification_success_email(self, email_id):
        subject = "Verification Success"
        body = "Your email has been verified successfully. You can now login to your account."  
        msg = EmailMessage()
        msg.set_content(body)
        msg["Subject"] = subject
        msg["From"] = self.smtp_username
        msg["To"] = email_id
        with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
            server.starttls()
            server.login(self.smtp_username, self.smtp_password)
            server.send_message(msg)
"""
通知模块

支持 Webhook 和邮件通知
"""

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

import requests

logger = logging.getLogger(__name__)


class Notifier:
    """通知发送器"""

    def __init__(self, config: dict):
        """
        初始化通知器

        Args:
            config: 配置字典
        """
        self.config = config.get("notify", {})
        self.enabled = self.config.get("enabled", False)
        self.webhook_url = self.config.get("webhook_url")
        self.webhook_method = self.config.get("webhook_method", "POST")
        self.email_config = self.config.get("email", {})

        if not self.enabled:
            logger.info("通知功能已禁用")
            return

        logger.info("通知功能已启用")

    def send(self, title: str, message: str) -> bool:
        """
        发送通知

        Args:
            title: 通知标题
            message: 通知内容

        Returns:
            是否发送成功
        """
        if not self.enabled:
            return False

        success = True

        # 发送 Webhook
        if self.webhook_url:
            try:
                if self._send_webhook(title, message):
                    logger.info("Webhook 通知发送成功")
                else:
                    logger.warning("Webhook 通知发送失败")
                    success = False
            except Exception as e:
                logger.error(f"Webhook 通知异常: {e}")
                success = False

        # 发送邮件
        recipients = self.email_config.get("recipients", [])
        if recipients:
            try:
                if self._send_email(title, message, recipients):
                    logger.info(f"邮件通知发送成功，发送给 {len(recipients)} 个收件人")
                else:
                    logger.warning("邮件通知发送失败")
                    success = False
            except Exception as e:
                logger.error(f"邮件通知异常: {e}")
                success = False

        return success

    def _send_webhook(self, title: str, message: str) -> bool:
        """
        发送 Webhook 通知

        Args:
            title: 标题
            message: 内容

        Returns:
            是否成功
        """
        if not self.webhook_url:
            return False

        payload = {
            "title": title,
            "message": message,
        }

        try:
            if self.webhook_method.upper() == "POST":
                response = requests.post(
                    self.webhook_url,
                    json=payload,
                    timeout=30,
                )
            else:
                response = requests.get(
                    self.webhook_url,
                    params=payload,
                    timeout=30,
                )

            response.raise_for_status()
            return True

        except requests.RequestException as e:
            logger.warning(f"Webhook 请求失败: {e}")
            return False

    def _send_email(self, title: str, message: str, recipients: list) -> bool:
        """
        发送邮件通知

        Args:
            title: 标题
            message: 内容
            recipients: 收件人列表

        Returns:
            是否成功
        """
        smtp_host = self.email_config.get("smtp_host")
        smtp_port = self.email_config.get("smtp_port", 587)
        sender = self.email_config.get("sender")
        password = self.email_config.get("password")

        if not all([smtp_host, sender, password]):
            logger.warning("邮件配置不完整，跳过邮件通知")
            return False

        try:
            # 创建邮件
            msg = MIMEMultipart("alternative")
            msg["Subject"] = title
            msg["From"] = sender
            msg["To"] = ", ".join(recipients)

            # 纯文本版本
            text_part = MIMEText(message, "plain", "utf-8")
            msg.attach(text_part)

            # HTML版本（可选）
            html_content = f"""
            <html>
            <body>
                <h2>{title}</h2>
                <pre style="font-family: Arial, sans-serif;">{message}</pre>
            </body>
            </html>
            """
            html_part = MIMEText(html_content, "html", "utf-8")
            msg.attach(html_part)

            # 发送邮件
            with smtplib.SMTP(smtp_host, smtp_port) as server:
                server.starttls()
                server.login(sender, password)
                server.sendmail(sender, recipients, msg.as_string())

            return True

        except smtplib.SMTPException as e:
            logger.error(f"SMTP 错误: {e}")
            return False
        except Exception as e:
            logger.error(f"邮件发送异常: {e}")
            return False

    def send_video_complete(self, bv_id: str, title: str, summary_file: Path) -> bool:
        """
        发送视频处理完成通知

        Args:
            bv_id: BV号
            title: 视频标题
            summary_file: 总结文件路径

        Returns:
            是否成功
        """
        title_text = f"视频处理完成: {title}"
        message = f"""
B站视频处理已完成

BV号: {bv_id}
标题: {title}
总结文件: {summary_file}

---
此消息由 B站视频总结系统 v2.0 自动发送
"""
        return self.send(title_text, message)

    def send_batch_complete(self, total: int, success: int, failed: int) -> bool:
        """
        发送批量处理完成通知

        Args:
            total: 总数
            success: 成功数
            failed: 失败数

        Returns:
            是否成功
        """
        title_text = f"批量处理完成: {success}/{total}"
        message = f"""
B站视频批量处理已完成

总计: {total}
成功: {success}
失败: {failed}
成功率: {success/total*100:.1f}%

---
此消息由 B站视频总结系统 v2.0 自动发送
"""
        return self.send(title_text, message)

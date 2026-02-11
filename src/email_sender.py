"""
Модуль для отправки электронных писем

Ключевые особенности:
1. Асинхронная отправка через SMTP (aiosmtplib)
2. Автоматическая конвертация Markdown в HTML
3. Multipart/alternative формат (plain text + HTML)
4. Поддержка вложений
5. Тестовый режим для разработки

Почему Markdown → HTML?
------------------------
Email-клиенты НЕ поддерживают Markdown напрямую. Они поддерживают:
- Plain text (без форматирования)
- HTML (с форматированием)

Поэтому мы:
1. Конвертируем Markdown в HTML (markdown.markdown())
2. Отправляем ОБЕ версии (multipart/alternative):
   - Plain text: исходный Markdown
   - HTML: красиво отформатированный текст
3. Email-клиент получателя выбирает лучшую версию

Пример:
    Вы пишете: "**Важно!** Прочти это"
    Получатель видит: жирный текст "Важно!" в HTML

Настройка:
----------
1. Заполните smtp_config.py авторизационными данными
2. Измените TEST_MODE = False для реальной отправки
3. Для Gmail используйте App Password, не обычный пароль!
"""

import asyncio
import logging
import mimetypes
import random
from dataclasses import dataclass
from datetime import datetime
from email import encoders
from email.mime.application import MIMEApplication
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Callable, Dict, List, Optional

import aiosmtplib
import markdown

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.FileHandler('email_sender.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('EmailSender')

# Регистрация MIME типов для офисных документов
# Некоторые системы могут не знать эти расширения
mimetypes.add_type('application/vnd.openxmlformats-officedocument.wordprocessingml.document', '.docx')
mimetypes.add_type('application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', '.xlsx')
mimetypes.add_type('application/vnd.openxmlformats-officedocument.presentationml.presentation', '.pptx')
mimetypes.add_type('application/msword', '.doc')
mimetypes.add_type('application/vnd.ms-excel', '.xls')
mimetypes.add_type('application/vnd.ms-powerpoint', '.ppt')
mimetypes.add_type('application/pdf', '.pdf')
mimetypes.add_type('application/zip', '.zip')
mimetypes.add_type('application/x-rar-compressed', '.rar')

try:
    from smtp_config import (GMAIL_EMAIL, GMAIL_PASSWORD, OUTLOOK_EMAIL,
                             OUTLOOK_PASSWORD, TEST_MODE, YANDEX_EMAIL,
                             YANDEX_PASSWORD)
except ImportError:
    # Значения по умолчанию, если конфиг не найден
    TEST_MODE = True
    GMAIL_EMAIL = GMAIL_PASSWORD = ""
    YANDEX_EMAIL = YANDEX_PASSWORD = ""
    OUTLOOK_EMAIL = OUTLOOK_PASSWORD = ""


@dataclass
class SMTPConfig:
    """Конфигурация SMTP сервера"""
    host: str
    port: int
    use_tls: bool
    email: str = ""
    password: str = ""


def get_smtp_servers() -> Dict[str, SMTPConfig]:
    """Получить конфигурацию SMTP серверов с данными из smtp_config.py"""
    return {
        "Gmail": SMTPConfig(
            host="smtp.gmail.com",
            port=465,
            use_tls=True,
            email=GMAIL_EMAIL,
            password=GMAIL_PASSWORD
        ),
        "Yandex": SMTPConfig(
            host="smtp.yandex.ru",
            port=465,
            use_tls=True,
            email=YANDEX_EMAIL,
            password=YANDEX_PASSWORD
        ),
        "Outlook": SMTPConfig(
            host="smtp.office365.com",
            port=587,
            use_tls=True,
            email=OUTLOOK_EMAIL,
            password=OUTLOOK_PASSWORD
        )
    }


@dataclass
class EmailTask:
    """Задача на отправку письма"""
    task_id: str
    recipients: List[str]
    subject: str
    body: str
    attachments: List[str]
    server: str
    status: str = "waiting"  # waiting, sending, success, error


class EmailSender:
    """Класс для управления отправкой писем"""
    
    def __init__(self, status_callback: Optional[Callable] = None, test_mode: Optional[bool] = None):
        """
        Args:
            status_callback: Колбэк для обновления статуса отправки
                            Сигнатура: callback(notification_id: str, status: str)
            test_mode: Если True, использует симуляцию отправки; если False, реальную SMTP отправку.
                      Если None, берется значение из smtp_config.TEST_MODE
        """
        self.status_callback = status_callback
        self.email_queue: List[EmailTask] = []
        self.active_tasks = {}
        self.test_mode = test_mode if test_mode is not None else TEST_MODE
        self.smtp_servers = get_smtp_servers()
        
        mode_str = "TEST (simulation)" if self.test_mode else "PRODUCTION (real SMTP)"
        logger.info(f"EmailSender initialized in {mode_str} mode")
        
        if not self.test_mode:
            # Проверяем конфигурацию при инициализации
            for server_name, config in self.smtp_servers.items():
                if config.email and config.password:
                    logger.info(f"✓ {server_name}: configured ({config.email})")
                else:
                    logger.warning(f"✗ {server_name}: NOT configured (missing credentials)")
    
    def add_to_queue(self, task: EmailTask) -> None:
        """Добавить задачу в очередь"""
        self.email_queue.append(task)
        logger.info(f"Task {task.task_id} added to queue: {len(task.recipients)} recipient(s), server: {task.server}")
    
    async def worker(self) -> None:
        """Worker процесс для обработки очереди писем"""
        while True:
            # Проверяем очередь каждые 0.5 секунды
            await asyncio.sleep(0.5)
            
            # Запускаем новые задачи из очереди
            tasks_to_start = []
            for task in self.email_queue[:]:  # Копия списка
                task_key = task.task_id
                
                # Если задача еще не запущена
                if task_key not in self.active_tasks:
                    # Создаем асинхронную задачу для отправки
                    async_task = asyncio.create_task(self.send_email_task(task))
                    self.active_tasks[task_key] = async_task
                    tasks_to_start.append(task)
            
            # Удаляем из очереди задачи, которые начали обрабатываться
            for task in tasks_to_start:
                if task in self.email_queue:
                    self.email_queue.remove(task)
            
            # Очищаем завершенные задачи
            completed_tasks = [key for key, task in self.active_tasks.items() if task.done()]
            for key in completed_tasks:
                del self.active_tasks[key]
    
    async def send_email_task(self, task: EmailTask) -> None:
        """Асинхронная отправка письма всем получателям"""
        # Создаем задачи для каждого получателя параллельно
        recipient_tasks = []
        for recipient in task.recipients:
            recipient_task = asyncio.create_task(
                self.send_to_recipient(task.task_id, recipient, task)
            )
            recipient_tasks.append(recipient_task)
        
        # Ждем завершения всех отправок
        await asyncio.gather(*recipient_tasks)
    
    async def send_to_recipient(self, task_id: str, recipient: str, task: EmailTask) -> None:
        """
        Отправка письма одному получателю
        """
        # Заменяем недопустимые символы в ID для уведомлений
        safe_recipient = recipient.replace("@", "_at_").replace(".", "_")
        notif_id = f"{task_id}_{safe_recipient}"
        
        logger.info(f"[{task_id}] Starting send to {recipient}")
        
        # Обновляем статус на "sending"
        if self.status_callback:
            self.status_callback(notif_id, "sending")
        
        try:
            if self.test_mode:
                # Тестовый режим - симуляция отправки
                logger.debug(f"[{task_id}] TEST MODE: Simulating send to {recipient}")
                delay = random.uniform(2, 5)
                await asyncio.sleep(delay)
                # Случайно определяем результат (85% успех, 15% ошибка)
                success = random.random() > 0.15
                if success:
                    logger.info(f"[{task_id}] ✓ TEST: Successfully sent to {recipient} (simulated, {delay:.1f}s)")
                else:
                    logger.warning(f"[{task_id}] ✗ TEST: Failed to send to {recipient} (simulated)")
            else:
                # Реальная отправка через SMTP
                logger.info(f"[{task_id}] SMTP: Sending to {recipient} via {task.server}")
                success = await self._send_via_smtp(recipient, task)
                
                if success:
                    logger.info(f"[{task_id}] ✓ SMTP: Successfully sent to {recipient}")
                else:
                    logger.error(f"[{task_id}] ✗ SMTP: Failed to send to {recipient}")
            
            # Обновляем статус
            status = "success" if success else "error"
            if self.status_callback:
                self.status_callback(notif_id, status)
                
        except Exception as e:
            # В случае ошибки обновляем статус на error
            logger.exception(f"[{task_id}] ✗ EXCEPTION: Error sending to {recipient}: {e}")
            if self.status_callback:
                self.status_callback(notif_id, "error")
    
    async def _send_via_smtp(self, recipient: str, task: EmailTask) -> bool:
        """
        Реальная отправка письма через SMTP
        
        Args:
            recipient: Email получателя
            task: Задача с данными письма
            
        Returns:
            True если отправка успешна, False иначе
        """
        try:
            logger.debug(f"[{task.task_id}] SMTP: Preparing email for {recipient}")
            
            # Получаем конфигурацию сервера
            smtp_config = self.smtp_servers.get(task.server)
            if not smtp_config:
                available_servers = ", ".join(self.smtp_servers.keys())
                logger.error(f"[{task.task_id}] Unknown server: '{task.server}' (type: {type(task.server).__name__})")
                logger.error(f"[{task.task_id}] Available servers: {available_servers}")
                return False
            
            # Проверяем, что заполнены авторизационные данные
            if not smtp_config.email or not smtp_config.password:
                logger.error(f"[{task.task_id}] SMTP credentials not configured for {task.server}")
                logger.error(f"[{task.task_id}] Please fill in email and password in smtp_config.py")
                return False
            
            logger.debug(f"[{task.task_id}] SMTP Config: {smtp_config.host}:{smtp_config.port}, from: {smtp_config.email}")
            
            # Создаем сообщение в формате multipart/alternative
            # Это позволяет отправить две версии письма:
            # 1. Plain text (для старых клиентов)
            # 2. HTML (для современных клиентов с поддержкой форматирования)
            message = MIMEMultipart('alternative')
            message['From'] = smtp_config.email
            message['To'] = recipient
            message['Subject'] = task.subject
            
            # Конвертируем Markdown в HTML
            # Email-клиенты не поддерживают Markdown, только HTML или plain text
            # Используем расширения:
            # - extra: таблицы, сноски, атрибуты
            # - nl2br: переводы строк преобразуются в <br>
            # - sane_lists: улучшенная обработка списков
            html_body = markdown.markdown(
                task.body,
                extensions=['extra', 'nl2br', 'sane_lists']
            )
            
            # Оборачиваем HTML в стандартный шаблон для лучшей совместимости
            html_body = self._wrap_html_template(html_body)
            
            # Добавляем обе версии письма
            # Порядок важен: сначала plain text, потом HTML
            # Email-клиент выберет наиболее подходящую версию
            text_part = MIMEText(task.body, 'plain', 'utf-8')
            html_part = MIMEText(html_body, 'html', 'utf-8')
            message.attach(text_part)
            message.attach(html_part)
            
            # Добавляем вложения
            if task.attachments:
                logger.info(f"[{task.task_id}] Processing {len(task.attachments)} attachment(s)")
                attached_count = 0
                
                for file_path in task.attachments:
                    try:
                        path = Path(file_path)
                        if not path.exists():
                            logger.warning(f"[{task.task_id}] ✗ Attachment not found: {file_path}")
                            logger.warning(f"[{task.task_id}]   This file will be skipped, email will be sent without it")
                            continue
                        
                        file_size = path.stat().st_size
                        file_size_mb = file_size / (1024 * 1024)
                        
                        # Предупреждение о больших файлах (многие серверы имеют лимит 25MB)
                        if file_size_mb > 25:
                            logger.warning(f"[{task.task_id}] ⚠️  Large file: {path.name} ({file_size_mb:.2f} MB)")
                            logger.warning(f"[{task.task_id}]   Many email servers have 25MB limit. This may fail!")
                        else:
                            logger.info(f"[{task.task_id}] ✓ Attaching: {path.name} ({file_size_mb:.2f} MB)")
                        
                        # Определяем MIME тип файла
                        mime_type, _ = mimetypes.guess_type(file_path)
                        if mime_type is None:
                            mime_type = 'application/octet-stream'
                        
                        logger.debug(f"[{task.task_id}] MIME type for {path.name}: {mime_type}")
                        
                        # Читаем файл и создаем вложение
                        with open(file_path, 'rb') as attachment_file:
                            file_data = attachment_file.read()
                            
                            # Разбиваем MIME тип на основной тип и подтип
                            maintype, subtype = mime_type.split('/', 1) if '/' in mime_type else ('application', 'octet-stream')
                            
                            # Создаем MIME часть с правильным типом
                            part = MIMEBase(maintype, subtype)
                            part.set_payload(file_data)
                            encoders.encode_base64(part)
                            
                            # Добавляем заголовок с именем файла
                            # Используем RFC 2231 для корректной обработки имен с кириллицей
                            from email.utils import encode_rfc2231
                            filename = path.name
                            
                            # Для безопасности экранируем имя файла
                            part.add_header(
                                'Content-Disposition',
                                'attachment',
                                filename=('utf-8', '', filename)
                            )
                            
                            message.attach(part)
                            attached_count += 1
                            logger.debug(f"[{task.task_id}] Successfully attached {filename} as {mime_type}")
                    except Exception as e:
                        logger.error(f"[{task.task_id}] ✗ Error attaching file {file_path}: {e}")
                
                if attached_count > 0:
                    logger.info(f"[{task.task_id}] Successfully attached {attached_count}/{len(task.attachments)} file(s)")
                else:
                    logger.warning(f"[{task.task_id}] No attachments were added (all files missing or failed)")
            else:
                logger.debug(f"[{task.task_id}] No attachments to process")
            
            # Отправляем через SMTP
            logger.info(f"[{task.task_id}] Connecting to {smtp_config.host}:{smtp_config.port}...")
            
            if smtp_config.use_tls and smtp_config.port == 465:
                # Используем SMTP_SSL для порта 465
                logger.debug(f"[{task.task_id}] Using SMTP_SSL (port 465)")
                await aiosmtplib.send(
                    message,
                    hostname=smtp_config.host,
                    port=smtp_config.port,
                    username=smtp_config.email,
                    password=smtp_config.password,
                    use_tls=True
                )
            else:
                # Используем STARTTLS для порта 587
                logger.debug(f"[{task.task_id}] Using STARTTLS (port 587)")
                await aiosmtplib.send(
                    message,
                    hostname=smtp_config.host,
                    port=smtp_config.port,
                    username=smtp_config.email,
                    password=smtp_config.password,
                    start_tls=True
                )
            
            logger.info(f"[{task.task_id}] Email sent successfully via {smtp_config.host}")
            return True
            
        except aiosmtplib.SMTPException as e:
            logger.error(f"[{task.task_id}] SMTP error: {type(e).__name__}: {e}")
            return False
        except Exception as e:
            logger.exception(f"[{task.task_id}] Unexpected error: {e}")
            return False
    
    @staticmethod
    def _wrap_html_template(html_content: str) -> str:
        """
        Оборачивает HTML-контент в стандартный email-шаблон
        
        Это необходимо для:
        - Корректного отображения в различных email-клиентах
        - Поддержки UTF-8 кодировки
        - Адаптивности на мобильных устройствах
        """
        return f"""
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            line-height: 1.6;
            color: #333;
            max-width: 600px;
            margin: 0 auto;
            padding: 20px;
        }}
        code {{
            background-color: #f4f4f4;
            padding: 2px 6px;
            border-radius: 3px;
            font-family: 'Courier New', monospace;
        }}
        pre {{
            background-color: #f4f4f4;
            padding: 10px;
            border-radius: 5px;
            overflow-x: auto;
        }}
        blockquote {{
            border-left: 4px solid #ddd;
            margin: 0;
            padding-left: 15px;
            color: #666;
        }}
        table {{
            border-collapse: collapse;
            width: 100%;
        }}
        table th, table td {{
            border: 1px solid #ddd;
            padding: 8px;
            text-align: left;
        }}
        table th {{
            background-color: #f4f4f4;
        }}
    </style>
</head>
<body>
    {html_content}
</body>
</html>
"""
    
    @staticmethod
    def sanitize_notification_id(task_id: str, recipient: str) -> str:
        """Создает безопасный ID для уведомления"""
        safe_recipient = recipient.replace("@", "_at_").replace(".", "_")
        return f"{task_id}_{safe_recipient}"



# ============================================================================
# ИНСТРУКЦИЯ ПО НАСТРОЙКЕ
# ============================================================================
#
# Для использования реальной отправки писем:
#
# 1. Откройте файл src/smtp_config.py
# 2. Заполните авторизационные данные для нужных серверов
# 3. Измените TEST_MODE = False для включения реальной отправки
#
# Важно:
# - Для Gmail используйте App Password, НЕ обычный пароль!
# - Не коммитьте smtp_config.py с реальными данными в git
# - Добавьте smtp_config.py в .gitignore
#
# ============================================================================

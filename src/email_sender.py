"""
Модуль для отправки электронных писем
"""

import asyncio
import random
from dataclasses import dataclass
from typing import List, Callable, Optional


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
    
    def __init__(self, status_callback: Optional[Callable] = None):
        """
        Args:
            status_callback: Колбэк для обновления статуса отправки
                            Сигнатура: callback(notification_id: str, status: str)
        """
        self.status_callback = status_callback
        self.email_queue: List[EmailTask] = []
        self.active_tasks = {}
    
    def add_to_queue(self, task: EmailTask) -> None:
        """Добавить задачу в очередь"""
        self.email_queue.append(task)
    
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
        
        В реальном приложении здесь будет код для отправки через SMTP
        """
        # Заменяем недопустимые символы в ID для уведомлений
        safe_recipient = recipient.replace("@", "_at_").replace(".", "_")
        notif_id = f"{task_id}_{safe_recipient}"
        
        # Обновляем статус на "sending"
        if self.status_callback:
            self.status_callback(notif_id, "sending")
        
        # Симулируем отправку (2-5 секунд)
        # TODO: Заменить на реальную отправку через SMTP
        await asyncio.sleep(random.uniform(2, 5))
        
        # Случайно определяем результат (85% успех, 15% ошибка)
        # TODO: Заменить на обработку реального результата отправки
        status = "success" if random.random() > 0.15 else "error"
        
        # Обновляем статус
        if self.status_callback:
            self.status_callback(notif_id, status)
    
    @staticmethod
    def sanitize_notification_id(task_id: str, recipient: str) -> str:
        """Создает безопасный ID для уведомления"""
        safe_recipient = recipient.replace("@", "_at_").replace(".", "_")
        return f"{task_id}_{safe_recipient}"


# Пример использования с реальным SMTP (для будущего)
"""
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

async def send_real_email(
    server: str,
    sender_email: str,
    sender_password: str,
    recipient: str,
    subject: str,
    body: str,
    attachments: List[str]
) -> bool:
    '''Реальная отправка письма через SMTP'''
    try:
        # Создаем сообщение
        message = MIMEMultipart()
        message['From'] = sender_email
        message['To'] = recipient
        message['Subject'] = subject
        
        # Добавляем тело письма
        message.attach(MIMEText(body, 'plain'))
        
        # Добавляем вложения
        for file_path in attachments:
            with open(file_path, 'rb') as attachment:
                part = MIMEBase('application', 'octet-stream')
                part.set_payload(attachment.read())
                encoders.encode_base64(part)
                part.add_header(
                    'Content-Disposition',
                    f'attachment; filename= {Path(file_path).name}'
                )
                message.attach(part)
        
        # Отправляем через SMTP
        smtp_server = get_smtp_server(server)
        with smtplib.SMTP_SSL(smtp_server, 465) as server:
            server.login(sender_email, sender_password)
            server.send_message(message)
        
        return True
    except Exception as e:
        print(f"Error sending email: {e}")
        return False

def get_smtp_server(server_name: str) -> str:
    '''Получить SMTP сервер по имени'''
    servers = {
        'Gmail': 'smtp.gmail.com',
        'Yandex': 'smtp.yandex.ru',
        'Outlook': 'smtp.outlook.com'
    }
    return servers.get(server_name, 'smtp.gmail.com')
"""

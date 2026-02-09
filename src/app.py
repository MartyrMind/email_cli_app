from textual.app import App, ComposeResult
from textual.containers import VerticalScroll, Container, Horizontal, Vertical
from textual.widgets import Input, Label, TextArea, Button, Select, Static, Markdown
from textual.reactive import reactive
from textual.message import Message
from pathlib import Path
import subprocess
import asyncio
from datetime import datetime
from typing import List
import time
import re

# Импортируем модуль для отправки писем
from email_sender import EmailSender, EmailTask

class NotificationItem(Container):
    """Виджет для отдельного уведомления"""
    
    DEFAULT_CSS = """
    NotificationItem {
        width: 100%;
        height: auto;
        margin-bottom: 1;
        padding: 1;
        background: $panel;
        border: solid $primary;
    }
    
    NotificationItem.waiting {
        border: solid $secondary;
    }
    
    NotificationItem.sending {
        border: solid $warning;
    }
    
    NotificationItem.success {
        border: solid $success;
    }
    
    NotificationItem.error {
        border: solid $error;
    }
    
    .notification-to {
        width: 100%;
        color: $text;
        text-style: bold;
        margin-bottom: 1;
    }
    
    .notification-subject {
        width: 100%;
        color: $text-muted;
        text-style: italic;
    }
    
    .notification-status {
        width: 100%;
        margin-top: 1;
    }
    
    .notification-status.waiting {
        color: $secondary;
    }
    
    .notification-status.sending {
        color: $warning;
    }
    
    .notification-status.success {
        color: $success;
    }
    
    .notification-status.error {
        color: $error;
    }
    
    .notification-hint {
        width: 100%;
        color: $text-muted;
        text-style: italic;
        margin-top: 1;
    }
    """
    
    def __init__(self, notification_id: str, to: str, subject: str, status: str = "waiting"):
        super().__init__()
        self.notification_id = notification_id
        self.to = to
        self.subject = subject
        self.status = status
        
    def compose(self) -> ComposeResult:
        yield Static(f"📧 To: {self.to}", classes="notification-to")
        yield Static(f"Subject: {self.subject[:30]}...", classes="notification-subject")
        
        status_icon = "⏸️" if self.status == "waiting" else "⏳" if self.status == "sending" else "✅" if self.status == "success" else "❌"
        status_text = "Waiting in queue..." if self.status == "waiting" else "Sending..." if self.status == "sending" else "Sent successfully" if self.status == "success" else "Failed to send"
        
        yield Static(f"{status_icon} {status_text}", classes=f"notification-status {self.status}")
    
    def on_click(self, event) -> None:
        """Подсчет кликов для двойного клика"""
        if not hasattr(self, '_click_count'):
            self._click_count = 0
            self._last_click_time = 0
        
        import time
        current_time = time.time()
        
        # Если между кликами прошло меньше 0.5 секунды - это двойной клик
        if current_time - self._last_click_time < 0.5:
            self._click_count += 1
            if self._click_count >= 2:
                # Двойной клик - удаляем уведомление
                self.post_message(self.Deleted(self.notification_id))
                self._click_count = 0
        else:
            self._click_count = 1
        
        self._last_click_time = current_time
    
    class Deleted(Message):
        """Сообщение об удалении уведомления"""
        def __init__(self, notification_id: str):
            super().__init__()
            self.notification_id = notification_id

class EmailSenderApp(App):
    CSS_PATH = "styles.css"
    
    # Реактивные переменные
    attached_files: reactive[list] = reactive(list)
    recipients: reactive[list] = reactive(list)
    notification_counter: int = 0
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Создаем экземпляр EmailSender с колбэком для обновления статусов
        self.email_sender = EmailSender(status_callback=self.update_notification_status)

    def compose(self) -> ComposeResult:
        # Заголовок приложения на всю ширину
        yield Static("📧 Email Sender", classes="header")
        
        with Horizontal(id="app_layout"):
            # Основная панель слева
            with VerticalScroll(id="main_container"):
                # Секция выбора сервера
                yield Container(
                    Label("Mail Server", classes="section-label"),
                    Select(
                        options=[
                            ("Gmail", "Gmail (smtp.gmail.com)"),
                            ("Yandex", "Yandex (smtp.yandex.ru)"),
                            ("Outlook", "Outlook (smtp.outlook.com)")
                        ],
                        id="server_select",
                        prompt="Choose mail server...",
                        allow_blank=False
                    ),
                    classes="section"
                )
                
                # Секция получателей
                yield Container(
                    Label("Recipients", classes="section-label"),
                    Input(
                        placeholder="Enter email and press Enter",
                        id="to_input"
                    ),
                    Static("💡 Tip: Press Enter or comma to add recipient", classes="hint"),
                    Horizontal(id="recipients_list", classes="recipients-container"),
                    classes="section recipients-section"
                )
                
                # Секция темы письма
                yield Container(
                    Label("Subject", classes="section-label"),
                    Input(placeholder="Enter email subject", id="subject_input"),
                    classes="section"
                )
                
                # Секция вложений
                yield Container(
                    Label("Attachments", classes="section-label"),
                    Button("📎 Add Files", id="add_files_btn", variant="default"),
                    Horizontal(id="attachments_list", classes="attachments-container"),
                    Static("💡 Click 'Add Files' to attach files from your computer", classes="hint"),
                    classes="section attachments-section"
                )
                
                # Секция тела письма
                yield Container(
                    Label("Message Body", classes="section-label"),
                    Horizontal(
                        Vertical(
                            Label("✍️ Edit (Markdown)", classes="editor-label"),
                            TextArea(
                                text="",
                                id="body_textarea"
                            ),
                            classes="editor-container"
                        ),
                        Vertical(
                            Label("👁️ Preview", classes="preview-label"),
                            Markdown("*Start typing to see preview...*", id="body_preview"),
                            classes="preview-container"
                        ),
                        classes="body-editor"
                    ),
                    classes="section body-section"
                )
                
                # Кнопка отправки
                yield Horizontal(
                    Button("📤 Send Email", variant="primary", id="send_btn"),
                    classes="button-container"
                )
            
            # Панель уведомлений справа
            with VerticalScroll(id="notifications_panel"):
                yield Static("📬 Notifications", classes="notifications-header")
                yield Container(id="notifications_list")
    
    def on_mount(self) -> None:
        """Запуск worker процесса при старте приложения"""
        self.run_worker(self.email_sender.worker(), exclusive=False)
    
    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Обработка нажатий кнопок"""
        if event.button.id == "add_files_btn":
            self.open_file_dialog()
        elif event.button.id == "send_btn":
            self.queue_email_for_sending()
    
    def on_click(self, event) -> None:
        """Обработка кликов по Static элементам"""
        widget_id = str(event.widget.id) if hasattr(event.widget, 'id') else ""
        
        if widget_id.startswith("remove_file_"):
            # Удаление файла из списка
            file_index = int(widget_id.replace("remove_file_", ""))
            if 0 <= file_index < len(self.attached_files):
                self.attached_files.pop(file_index)
                self.update_attachments_display()
        elif widget_id.startswith("remove_recipient_"):
            # Удаление получателя из списка
            recipient_index = int(widget_id.replace("remove_recipient_", ""))
            if 0 <= recipient_index < len(self.recipients):
                self.recipients.pop(recipient_index)
                self.update_recipients_display()
    
    def on_notification_item_deleted(self, message: NotificationItem.Deleted) -> None:
        """Обработка сообщения об удалении уведомления"""
        self.remove_notification(message.notification_id)
    
    def add_notification(self, to: str, subject: str, status: str = "waiting", notification_id: str = None) -> str:
        """Добавление нового уведомления"""
        if notification_id is None:
            self.notification_counter += 1
            notification_id = f"notif_{self.notification_counter}"
        
        container = self.query_one("#notifications_list")
        notification = NotificationItem(notification_id, to, subject, status)
        container.mount(notification)
        
        return notification_id
    
    def update_notification_status(self, notification_id: str, status: str) -> None:
        """Обновление статуса уведомления"""
        try:
            notifications = self.query_one("#notifications_list").query(NotificationItem)
            for notification in notifications:
                if notification.notification_id == notification_id:
                    # Обновляем статус
                    notification.status = status
                    notification.remove_class("waiting", "sending", "success", "error")
                    notification.add_class(status)
                    
                    # Обновляем текст статуса
                    status_widget = notification.query(".notification-status").first()
                    if status_widget:
                        status_icon = "⏸️" if status == "waiting" else "⏳" if status == "sending" else "✅" if status == "success" else "❌"
                        status_text = "Waiting in queue..." if status == "waiting" else "Sending..." if status == "sending" else "Sent successfully" if status == "success" else "Failed to send"
                        status_widget.update(f"{status_icon} {status_text}")
                    
                    break
        except Exception as e:
            pass
    
    def remove_notification(self, notification_id: str) -> None:
        """Удаление уведомления"""
        try:
            notifications = self.query_one("#notifications_list").query(NotificationItem)
            for notif in notifications:
                if notif.notification_id == notification_id:
                    notif.remove()
                    break
        except:
            pass
    
    def clear_form(self) -> None:
        """Очистка формы после отправки"""
        try:
            # Очищаем получателей
            self.recipients = []
            self.update_recipients_display()
            
            # Очищаем тему
            subject_input = self.query_one("#subject_input", Input)
            subject_input.value = ""
            
            # Очищаем тело письма
            body_textarea = self.query_one("#body_textarea", TextArea)
            body_textarea.text = ""
            
            # Очищаем превью
            body_preview = self.query_one("#body_preview", Markdown)
            body_preview.update("*Start typing to see preview...*")
            
            # Очищаем вложения
            self.attached_files = []
            self.update_attachments_display()
            
            # Сбрасываем выбор сервера (опционально)
            # server_select = self.query_one("#server_select", Select)
            # server_select.clear()
            
        except Exception as e:
            self.log(f"Error clearing form: {e}")
    
    def queue_email_for_sending(self) -> None:
        """Добавление письма в очередь на отправку"""
        # Получаем данные из формы
        try:
            server_select = self.query_one("#server_select", Select)
            subject_input = self.query_one("#subject_input", Input)
            body_textarea = self.query_one("#body_textarea", TextArea)
            
            # Проверяем, что есть получатели
            if not self.recipients:
                # TODO: показать ошибку
                self.log("No recipients!")
                return
            
            # Получаем выбранный сервер
            server = server_select.value if server_select.value else "Gmail"
            
            # Создаем задачу
            self.notification_counter += 1
            task_id = f"email_{self.notification_counter}"
            
            task = EmailTask(
                task_id=task_id,
                recipients=self.recipients.copy(),
                subject=subject_input.value or "No Subject",
                body=body_textarea.text or "",
                attachments=self.attached_files.copy(),
                server=server,
                status="waiting"
            )
            
            # Добавляем в очередь через EmailSender
            self.email_sender.add_to_queue(task)
            self.log(f"Added task to queue: {task_id}, recipients: {task.recipients}")
            
            # Создаем уведомления для каждого получателя
            for recipient in task.recipients:
                notif_id = EmailSender.sanitize_notification_id(task_id, recipient)
                self.log(f"Creating notification: {notif_id}")
                self.add_notification(recipient, task.subject, "waiting", notification_id=notif_id)
            
            # Очищаем форму после отправки
            self.clear_form()
            
        except Exception as e:
            self.log(f"Error in queue_email_for_sending: {e}")
            pass
    
    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Обработка нажатия Enter в полях ввода"""
        if event.input.id == "to_input":
            self.add_recipient(event.value)
            event.input.value = ""
    
    def on_input_changed(self, event: Input.Changed) -> None:
        """Обработка изменения значения в полях ввода"""
        if event.input.id == "to_input":
            # Проверяем, есть ли запятая в тексте
            if "," in event.value:
                parts = event.value.split(",")
                # Добавляем все части кроме последней
                for part in parts[:-1]:
                    email = part.strip()
                    if email:
                        self.add_recipient(email)
                # Оставляем последнюю часть в поле ввода
                event.input.value = parts[-1].strip()
    
    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        """Обработка изменения текста в TextArea для live preview"""
        if event.text_area.id == "body_textarea":
            # Обновляем превью
            try:
                preview = self.query_one("#body_preview", Markdown)
                text = str(event.text_area.text) if event.text_area.text else "*Start typing to see preview...*"
                # Если текст пустой или только пробелы, показываем placeholder
                if not text.strip():
                    text = "*Start typing to see preview...*"
                preview.update(text)
            except Exception as e:
                self.log(f"Error updating preview: {e}")
                pass
    
    def add_recipient(self, email: str) -> None:
        """Добавление получателя в список"""
        email = email.strip()
        if email and self.is_valid_email(email) and email not in self.recipients:
            self.recipients.append(email)
            self.update_recipients_display()
    
    def is_valid_email(self, email: str) -> bool:
        """Простая валидация email"""
        import re
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return re.match(pattern, email) is not None
    
    def update_recipients_display(self) -> None:
        """Обновление отображения списка получателей"""
        container = self.query_one("#recipients_list")
        container.remove_children()
        
        if not self.recipients:
            # Если список пуст, показываем placeholder
            container.mount(Static("No recipients added yet", classes="empty-placeholder"))
        else:
            for index, email in enumerate(self.recipients):
                # Создаем чип с email и кнопкой удаления
                # Временно используем Static вместо Button
                remove_widget = Static("🗑️", id=f"remove_recipient_{index}", classes="remove-recipient-btn")
                remove_widget.can_focus = True
                
                recipient_chip = Horizontal(
                    Static(f"👤 {email}", classes="recipient-email"),
                    remove_widget,
                    classes="recipient-chip"
                )
                container.mount(recipient_chip)
    
    def open_file_dialog(self) -> None:
        """Открытие диалога выбора файлов (для macOS)"""
        try:
            # Используем osascript для вызова нативного диалога macOS
            result = subprocess.run(
                ['osascript', '-e', 'POSIX path of (choose file with multiple selections allowed)'],
                capture_output=True,
                text=True,
                timeout=60
            )
            
            if result.returncode == 0 and result.stdout.strip():
                # Файлы разделены запятыми
                files = [f.strip() for f in result.stdout.strip().split(',') if f.strip()]
                for file_path in files:
                    if file_path and file_path not in self.attached_files:
                        self.attached_files.append(file_path)
                self.update_attachments_display()
        except Exception as e:
            # Если диалог не сработал, добавим демонстрационные файлы
            demo_files = ["example_document.pdf", "photo.jpg", "report.xlsx"]
            for demo_file in demo_files:
                if demo_file not in self.attached_files:
                    self.attached_files.append(demo_file)
            self.update_attachments_display()
    
    def update_attachments_display(self) -> None:
        """Обновление отображения списка прикрепленных файлов"""
        container = self.query_one("#attachments_list")
        container.remove_children()
        
        for index, file_path in enumerate(self.attached_files):
            file_name = Path(file_path).name
            file_ext = Path(file_path).suffix.lower()
            
            # Выбор иконки в зависимости от типа файла
            if file_ext in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp']:
                icon = "🖼️"
            elif file_ext in ['.pdf']:
                icon = "📄"
            elif file_ext in ['.doc', '.docx', '.txt', '.rtf']:
                icon = "📝"
            elif file_ext in ['.xls', '.xlsx', '.csv']:
                icon = "📊"
            elif file_ext in ['.zip', '.rar', '.7z', '.tar', '.gz']:
                icon = "📦"
            elif file_ext in ['.mp4', '.avi', '.mov', '.mkv']:
                icon = "🎥"
            elif file_ext in ['.mp3', '.wav', '.flac', '.m4a']:
                icon = "🎵"
            else:
                icon = "📎"
            
            # Создаем строку с файлом и кнопкой удаления
            # Временно используем Static вместо Button
            remove_widget = Static("🗑️", id=f"remove_file_{index}", classes="remove-btn")
            remove_widget.can_focus = True
            
            file_item = Horizontal(
                Static(f"{icon} {file_name}", classes="file-name"),
                remove_widget,
                classes="file-item"
            )
            container.mount(file_item)
    
    def send_email(self) -> None:
        """Отправка email (вызывается при нажатии кнопки)"""
        self.queue_email_for_sending()

if __name__ == "__main__":
    app = EmailSenderApp()
    app.run()
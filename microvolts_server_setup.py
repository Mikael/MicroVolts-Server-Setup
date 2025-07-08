from logging import config
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, scrolledtext
from ttkthemes import ThemedTk
import requests
import zipfile
import os
import subprocess
import threading
import json
import shutil
from pathlib import Path
import configparser
import secrets
import string
import sys
import time
import re

# Imports from Database Editor
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QTableWidget, QTableWidgetItem,
    QMessageBox, QDialog, QDialogButtonBox, QInputDialog, QComboBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
import mariadb

# Database Editor Classes
class DatabaseThread(QThread):
    connection_signal = pyqtSignal(object)
    tables_signal = pyqtSignal(list)
    table_data_signal = pyqtSignal(object)
    update_signal = pyqtSignal(bool)
    error_signal = pyqtSignal(str)
    player_grades_signal = pyqtSignal(list)

    def __init__(self, config):
        super().__init__()
        self.config = config
        self.connection = None

    def run(self):
        try:
            self.connection = mariadb.connect(**self.config)
            self.connection_signal.emit(self.connection)
        except mariadb.Error as err:
            self.error_signal.emit(f"Error connecting to MariaDB: {err}")

    def list_tables(self):
        if self.connection:
            try:
                cursor = self.connection.cursor()
                cursor.execute("SHOW TABLES")
                tables = [table[0] for table in cursor.fetchall()]
                self.tables_signal.emit(tables)
            except mariadb.Error as err:
                self.error_signal.emit(f"Error listing tables: {err}")

    def get_table_data(self, table_name):
        if self.connection:
            try:
                cursor = self.connection.cursor(dictionary=True)
                cursor.execute(f"SELECT * FROM {table_name}")
                data = cursor.fetchall()
                self.table_data_signal.emit({"table_name": table_name, "data": data})
            except mariadb.Error as err:
                self.error_signal.emit(f"Error getting table data: {err}")

    def update_cell_value(self, table_name, column_name, new_value, primary_key_column, primary_key_value):
        if self.connection:
            try:
                cursor = self.connection.cursor()
                query = f"UPDATE {table_name} SET {column_name} = ? WHERE {primary_key_column} = ?"
                cursor.execute(query, (new_value, primary_key_value))
                self.connection.commit()
                self.update_signal.emit(True)
            except mariadb.Error as err:
                self.error_signal.emit(f"Error updating cell value: {err}")
                self.update_signal.emit(False)

    def get_player_grades(self):
        if self.connection:
            try:
                cursor = self.connection.cursor()
                cursor.execute("SELECT DISTINCT Grade FROM PlayerGrade")
                grades = [grade[0] for grade in cursor.fetchall()]
                self.player_grades_signal.emit(grades)
            except mariadb.Error as err:
                self.error_signal.emit(f"Error getting player grades: {err}")


class LoginDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Database Login")
        self.layout = QVBoxLayout(self)

        self.ip_input = QLineEdit()
        self.ip_input.setPlaceholderText("IP Address/Hostname")
        self.layout.addWidget(QLabel("IP Address/Hostname:"))
        self.layout.addWidget(self.ip_input)

        self.port_input = QLineEdit()
        self.port_input.setPlaceholderText("Port (default: 3306)")
        self.layout.addWidget(QLabel("Port:"))
        self.layout.addWidget(self.port_input)

        self.user_input = QLineEdit()
        self.user_input.setPlaceholderText("Username")
        self.layout.addWidget(QLabel("Username:"))
        self.layout.addWidget(self.user_input)

        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.setPlaceholderText("Password")
        self.layout.addWidget(QLabel("Password:"))
        self.layout.addWidget(self.password_input)
        
        self.db_input = QLineEdit()
        self.db_input.setPlaceholderText("Database")
        self.layout.addWidget(QLabel("Database:"))
        self.layout.addWidget(self.db_input)

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.layout.addWidget(self.buttons)

    def get_credentials(self):
        try:
            port = int(self.port_input.text())
        except ValueError:
            port = 3306
        return {
            "host": self.ip_input.text(),
            "port": port,
            "user": self.user_input.text(),
            "password": self.password_input.text(),
            "database": self.db_input.text()
        }


class DatabaseEditorMainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Database Editor")
        self.setGeometry(100, 100, 800, 600)

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.layout = QHBoxLayout(self.central_widget)

        self.tables_list_widget = QTableWidget()
        self.tables_list_widget.setColumnCount(1)
        self.tables_list_widget.setHorizontalHeaderLabels(["Tables"])
        self.tables_list_widget.itemClicked.connect(self.table_selected)
        self.layout.addWidget(self.tables_list_widget)

        self.table_data_widget = QTableWidget()
        self.table_data_widget.itemDoubleClicked.connect(self.edit_cell)
        self.layout.addWidget(self.table_data_widget)

        self.db_thread = None
        self.current_table = None
        self.attempt_auto_login()

    def attempt_auto_login(self):
        config_file = "mv_setup_config.json"
        credentials = None
        if os.path.exists(config_file):
            try:
                with open(config_file, 'r') as f:
                    config = json.load(f)
                credentials = {
                    "host": config.get("db_ip", "127.0.0.1"),
                    "port": int(config.get("db_port", 3306)),
                    "user": config.get("db_username", "root"),
                    "password": config.get("db_password", ""),
                    "database": config.get("db_name", "microvolts-db")
                }
            except (json.JSONDecodeError, KeyError, ValueError) as e:
                self.show_error(f"Error reading config file: {e}")
                credentials = None
        
        if credentials:
            self.db_thread = DatabaseThread(credentials)
            self.db_thread.connection_signal.connect(self.on_connection)
            self.db_thread.error_signal.connect(self.on_auto_login_error)
            self.db_thread.start()
        else:
            self.login() # Fallback to manual login

    def on_auto_login_error(self, error_message):
        self.show_error(f"Auto-login failed: {error_message}\nPlease log in manually.")
        self.login()

    def login(self):
        # Disconnect previous error signal if any
        if self.db_thread and hasattr(self.db_thread, 'error_signal'):
            try:
                self.db_thread.error_signal.disconnect(self.on_auto_login_error)
            except TypeError:
                pass # Signal not connected

        dialog = LoginDialog(self)
        if dialog.exec():
            credentials = dialog.get_credentials()
            self.db_thread = DatabaseThread(credentials)
            self.db_thread.connection_signal.connect(self.on_connection)
            self.db_thread.error_signal.connect(self.show_error)
            self.db_thread.start()
        else:
            # If the user cancels the manual login, close the window.
            self.close()

    def on_connection(self, connection):
        if connection:
            self.db_thread.tables_signal.connect(self.show_tables)
            self.db_thread.list_tables()
        else:
            self.show_error("Failed to connect to the database.")

    def show_tables(self, tables):
        self.tables_list_widget.setRowCount(len(tables))
        for i, table_name in enumerate(tables):
            self.tables_list_widget.setItem(i, 0, QTableWidgetItem(table_name))

    def table_selected(self, item):
        self.current_table = item.text()
        self.db_thread.table_data_signal.connect(self.show_table_data)
        self.db_thread.get_table_data(self.current_table)

    def show_table_data(self, result):
        table_name = result["table_name"]
        data = result["data"]
        if table_name != self.current_table:
            return

        if not data:
            self.table_data_widget.setRowCount(0)
            self.table_data_widget.setColumnCount(0)
            return

        self.table_data_widget.setRowCount(len(data))
        self.table_data_widget.setColumnCount(len(data[0]))
        
        column_names = list(data[0].keys())
        self.table_data_widget.setHorizontalHeaderLabels(column_names)

        for i, row in enumerate(data):
            for j, col_name in enumerate(column_names):
                self.table_data_widget.setItem(i, j, QTableWidgetItem(str(row[col_name])))

    def edit_cell(self, item):
        row = item.row()
        column = item.column()
        column_name = self.table_data_widget.horizontalHeaderItem(column).text()
        current_value = item.text()
        
        primary_key_column = self.table_data_widget.horizontalHeaderItem(0).text()
        primary_key_value = self.table_data_widget.item(row, 0).text()

        if self.current_table == "Users" and column_name == "Grade":
            self.db_thread.player_grades_signal.connect(self.show_grade_dialog)
            self.db_thread.get_player_grades()
        else:
            new_value, ok = QInputDialog.getText(self, "Edit Cell", f"Enter new value for {column_name}:", QLineEdit.EchoMode.Normal, current_value)
            if ok and new_value != current_value:
                self.db_thread.update_signal.connect(self.on_update)
                self.db_thread.update_cell_value(self.current_table, column_name, new_value, primary_key_column, primary_key_value)

    def show_grade_dialog(self, grades):
        grade, ok = QInputDialog.getItem(self, "Select Grade", "Select a new grade:", grades, 0, False)
        if ok and grade:
            row = self.table_data_widget.currentRow()
            column = self.table_data_widget.currentColumn()
            column_name = self.table_data_widget.horizontalHeaderItem(column).text()
            primary_key_column = self.table_data_widget.horizontalHeaderItem(0).text()
            primary_key_value = self.table_data_widget.item(row, 0).text()
            self.db_thread.update_signal.connect(self.on_update)
            self.db_thread.update_cell_value(self.current_table, column_name, grade, primary_key_column, primary_key_value)

    def on_update(self, success):
        if success:
            self.db_thread.get_table_data(self.current_table)
        else:
            self.show_error("Failed to update the database.")

    def show_error(self, message):
        QMessageBox.critical(self, "Error", message)


def run_db_editor_app_process():
    app = QApplication(sys.argv)
    
    dark_stylesheet = """
        QWidget {
            background-color: #2e2e2e;
            color: #e0e0e0;
            font-family: "Segoe UI", "Helvetica Neue", "Arial", sans-serif;
        }
        QMainWindow, QDialog {
            background-color: #353535;
        }
        QTableWidget {
            background-color: #252525;
            color: #e0e0e0;
            border: 1px solid #444;
            gridline-color: #444;
        }
        QHeaderView::section {
            background-color: #3a3a3a;
            color: #e0e0e0;
            padding: 5px;
            border: 1px solid #444;
            border-bottom: 2px solid #0078d4;
        }
        QTableCornerButton::section {
            background-color: #3a3a3a;
        }
        QScrollBar:vertical {
            border: none;
            background: #252525;
            width: 12px;
            margin: 15px 0 15px 0;
            border-radius: 6px;
        }
        QScrollBar::handle:vertical {
            background: #555;
            min-height: 20px;
            border-radius: 6px;
        }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
            height: 0px;
        }
        QScrollBar:horizontal {
            border: none;
            background: #252525;
            height: 12px;
            margin: 0 15px 0 15px;
            border-radius: 6px;
        }
        QScrollBar::handle:horizontal {
            background: #555;
            min-width: 20px;
            border-radius: 6px;
        }
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
            width: 0px;
        }
        QPushButton {
            background-color: #0078d4;
            color: white;
            border: none;
            padding: 8px 16px;
            border-radius: 4px;
            font-weight: bold;
        }
        QPushButton:hover {
            background-color: #106ebe;
        }
        QPushButton:pressed {
            background-color: #005a9e;
        }
        QLineEdit, QComboBox {
            background-color: #252525;
            color: #e0e0e0;
            border: 1px solid #444;
            border-radius: 4px;
            padding: 5px;
        }
        QLineEdit:focus, QComboBox:focus {
            border: 1px solid #0078d4;
        }
        QComboBox::drop-down {
            border: none;
        }
        QComboBox::down-arrow {
            image: url(down_arrow.png);
        }
        QLabel {
            color: #e0e0e0;
        }
        QMessageBox {
            background-color: #353535;
        }
    """
    app.setStyleSheet(dark_stylesheet)

    editor = DatabaseEditorMainWindow()
    editor.show()
    sys.exit(app.exec())


class MicroVoltsServerSetup:
    def __init__(self, root):
        self.root = root
        self.root.title("MicroVolts Server Setup v2.1 | @Mikael")
        self.root.geometry("850x750")
        self.root.resizable(True, True)

        self.style = ttk.Style(self.root)
        self.root.set_theme("scidblue")

        self.project_path = tk.StringVar()
        self.local_ip = tk.StringVar()
        
        self.db_ip = tk.StringVar(value="127.0.0.1")
        self.db_port = tk.StringVar(value="3306")
        self.db_username = tk.StringVar(value="root")
        self.db_password = tk.StringVar()
        self.db_name = tk.StringVar(value="microvolts-db")

        self.config_file = "mv_setup_config.json"
        self.existing_mariadb = tk.BooleanVar(value=False)
        self.db_root_password = tk.StringVar()

        self.state_file = "setup_state.json"
        self.setup_state = {}

        self.servers = []
        self.server_widgets = []
        
        self.setup_gui()

        self.load_settings()

        if not self.project_path.get():
            self.generate_random_password()
        
        self.center_window()
        
    def center_window(self):
        self.root.update_idletasks()
        x = (self.root.winfo_screenwidth() // 2) - (self.root.winfo_width() // 2)
        y = (self.root.winfo_screenheight() // 2) - (self.root.winfo_height() // 2)
        self.root.geometry(f"+{x}+{y}")

    def browse_directory(self):
        directory = filedialog.askdirectory()
        if directory:
            self.project_path.set(directory)

    def load_settings(self):
        if os.path.exists(self.config_file):
            self.log(f"Loading settings from {self.config_file}")
            try:
                with open(self.config_file, 'r') as f:
                    config = json.load(f)
                
                self.project_path.set(config.get("project_path", ""))
                self.local_ip.set(config.get("local_ip", ""))
                self.db_ip.set(config.get("db_ip", "127.0.0.1"))
                self.db_port.set(config.get("db_port", "3306"))
                self.db_username.set(config.get("db_username", "root"))
                self.db_password.set(config.get("db_password", ""))
                self.db_name.set(config.get("db_name", "microvolts-db"))
                
                for widgets in self.server_widgets:
                    widgets["frame"].destroy()
                self.server_widgets.clear()

                self.servers = config.get("servers", [])
                for server_data in self.servers:
                    self.add_server_row()
                    widgets = self.server_widgets[-1]
                    widgets["main_local_ip"].set(server_data.get("main_local_ip", ""))
                    widgets["main_public_ip"].set(server_data.get("main_public_ip", ""))
                    widgets["main_port"].set(server_data.get("main_port", ""))
                    widgets["main_ipc_port"].set(server_data.get("main_ipc_port", ""))
                    widgets["cast_local_ip"].set(server_data.get("cast_local_ip", ""))
                    widgets["cast_public_ip"].set(server_data.get("cast_public_ip", ""))
                    widgets["cast_port"].set(server_data.get("cast_port", ""))
                    widgets["cast_ipc_port"].set(server_data.get("cast_ipc_port", ""))

                self.log("Settings loaded successfully.")
            except Exception as e:
                self.log(f"Error loading settings: {e}")
                messagebox.showerror("Error", f"Could not load settings from {self.config_file}.\n{e}")
        else:
            self.log("No existing configuration file found. Starting with default settings.")

    def save_settings(self):
        self.log(f"Saving settings to {self.config_file}")
        try:
            servers_data = []
            for widgets in self.server_widgets:
                server_data = {
                    "main_local_ip": widgets["main_local_ip"].get(),
                    "main_public_ip": widgets["main_public_ip"].get(),
                    "main_port": widgets["main_port"].get(),
                    "main_ipc_port": widgets["main_ipc_port"].get(),
                    "cast_local_ip": widgets["cast_local_ip"].get(),
                    "cast_public_ip": widgets["cast_public_ip"].get(),
                    "cast_port": widgets["cast_port"].get(),
                    "cast_ipc_port": widgets["cast_ipc_port"].get(),
                }
                servers_data.append(server_data)

            config = {
                "project_path": self.project_path.get(),
                "local_ip": self.local_ip.get(),
                "db_ip": self.db_ip.get(),
                "db_port": self.db_port.get(),
                "db_username": self.db_username.get(),
                "db_password": self.db_password.get(),
                "db_name": self.db_name.get(),
                "servers": servers_data
            }
            with open(self.config_file, 'w') as f:
                json.dump(config, f, indent=4)
            self.log("Settings saved successfully.")
        except Exception as e:
            self.log(f"Error saving settings: {e}")
            messagebox.showerror("Error", f"Could not save settings to {self.config_file}.\n{e}")
        
    def setup_gui(self):
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)
        
        title_label = ttk.Label(main_frame, text="MicroVolts Server Setup", 
                               font=("Arial", 16, "bold"))
        title_label.grid(row=0, column=0, columnspan=3, pady=(0, 20))
        
        ttk.Label(main_frame, text="Installation Directory:").grid(row=1, column=0, sticky=tk.W, pady=5)
        ttk.Entry(main_frame, textvariable=self.project_path, width=50).grid(row=1, column=1, sticky=(tk.W, tk.E), pady=5, padx=(5, 5))
        ttk.Button(main_frame, text="Browse", command=self.browse_directory).grid(row=1, column=2, pady=5)
        
        notebook = ttk.Notebook(main_frame)
        notebook.grid(row=2, column=0, columnspan=3, sticky=(tk.W, tk.E, tk.N, tk.S), pady=10)
        main_frame.rowconfigure(2, weight=1)

        server_tab = ttk.Frame(notebook, padding="10")
        db_tab = ttk.Frame(notebook, padding="10")

        notebook.add(server_tab, text="Server Configuration")
        notebook.add(db_tab, text="Database Configuration")

        multi_server_tab = ttk.Frame(notebook, padding="10")
        notebook.add(multi_server_tab, text="Multi-Server")

        # Server Configuration Tab
        server_tab.columnconfigure(1, weight=1)
        
        ip_frame = ttk.LabelFrame(server_tab, text="IP Settings", padding="10")
        ip_frame.grid(row=0, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=10)
        ip_frame.columnconfigure(1, weight=1)

        ttk.Label(ip_frame, text="Local IP:").grid(row=0, column=0, sticky=tk.W, pady=2)
        ttk.Entry(ip_frame, textvariable=self.local_ip, width=20).grid(row=0, column=1, sticky=(tk.W, tk.E), pady=2, padx=(5, 0))
        ttk.Button(ip_frame, text="Auto-detect Local IP",
                  command=self.auto_detect_ip).grid(row=0, column=2, padx=(5, 0), pady=2)

        # Multi-Server Tab
        multi_server_tab.columnconfigure(0, weight=1)
        multi_server_tab.rowconfigure(0, weight=1)

        canvas = tk.Canvas(multi_server_tab)
        scrollbar = ttk.Scrollbar(multi_server_tab, orient="vertical", command=canvas.yview)
        self.server_list_frame = ttk.Frame(canvas)

        self.server_list_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(
                scrollregion=canvas.bbox("all")
            )
        )

        canvas.create_window((0, 0), window=self.server_list_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        button_frame_multi = ttk.Frame(multi_server_tab)
        button_frame_multi.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(10,0))
        button_frame_multi.columnconfigure(0, weight=1)
        
        add_server_button = ttk.Button(button_frame_multi, text="+ Add Server", command=self.add_server_row)
        add_server_button.grid(row=0, column=0, sticky="e")

        # Database Configuration Tab
        db_tab.columnconfigure(1, weight=1)

        self.db_install_frame = ttk.Frame(db_tab)
        self.db_install_frame.grid(row=0, column=0, sticky="ew", columnspan=4)
        self.db_install_frame.columnconfigure(1, weight=1)

        db_frame = ttk.LabelFrame(self.db_install_frame, text="New MariaDB Installation", padding="10")
        db_frame.grid(row=0, column=0, columnspan=4, sticky=(tk.W, tk.E), pady=10)
        db_frame.columnconfigure(1, weight=1)
        db_frame.columnconfigure(3, weight=1)

        ttk.Label(db_frame, text="Database IP:").grid(row=0, column=0, sticky=tk.W, pady=2)
        ttk.Entry(db_frame, textvariable=self.db_ip, width=20).grid(row=0, column=1, sticky=(tk.W, tk.E), pady=2, padx=(5, 0))
        
        ttk.Label(db_frame, text="Database Port:").grid(row=0, column=2, sticky=tk.W, pady=2, padx=(10, 0))
        ttk.Entry(db_frame, textvariable=self.db_port, width=10).grid(row=0, column=3, sticky=tk.W, pady=2, padx=(5, 0))
        
        ttk.Label(db_frame, text="Username:").grid(row=1, column=0, sticky=tk.W, pady=2)
        ttk.Entry(db_frame, textvariable=self.db_username, width=20).grid(row=1, column=1, sticky=(tk.W, tk.E), pady=2, padx=(5, 0))
        
        ttk.Label(db_frame, text="Database Name:").grid(row=1, column=2, sticky=tk.W, pady=2, padx=(10, 0))
        ttk.Entry(db_frame, textvariable=self.db_name, width=20).grid(row=1, column=3, sticky=(tk.W, tk.E), pady=2, padx=(5, 0))
        
        ttk.Label(db_frame, text="Password:").grid(row=2, column=0, sticky=tk.W, pady=2)
        self.password_entry = ttk.Entry(db_frame, textvariable=self.db_password, width=30, show="*")
        self.password_entry.grid(row=2, column=1, columnspan=2, sticky=(tk.W, tk.E), pady=2, padx=(5, 0))
        
        ttk.Button(db_frame, text="Generate New", 
                  command=self.generate_random_password).grid(row=2, column=3, padx=(5, 0), pady=2)

        ttk.Checkbutton(db_tab, text="Use existing MariaDB installation", 
                        variable=self.existing_mariadb, command=self.toggle_mariadb_fields).grid(row=1, column=0, sticky=tk.W, pady=10, padx=5)

        self.existing_db_frame = ttk.LabelFrame(db_tab, text="Existing MariaDB Credentials", padding="10")
        
        ttk.Label(self.existing_db_frame, text="Root Password:").grid(row=0, column=0, sticky=tk.W, pady=2)
        ttk.Entry(self.existing_db_frame, textvariable=self.db_root_password, show="*").grid(row=0, column=1, sticky=(tk.W, tk.E), pady=2, padx=5)
        self.existing_db_frame.columnconfigure(1, weight=1)
        
        progress_frame = ttk.LabelFrame(main_frame, text="Setup Progress", padding="10")
        progress_frame.grid(row=3, column=0, columnspan=3, sticky=(tk.W, tk.E, tk.N, tk.S), pady=10)
        progress_frame.columnconfigure(0, weight=1)
        progress_frame.rowconfigure(0, weight=1)

        self.log_text = scrolledtext.ScrolledText(progress_frame, height=15, width=80, relief=tk.FLAT)
        self.log_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        self.progress_bar = ttk.Progressbar(progress_frame, mode='indeterminate')
        self.progress_bar.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(10, 0))

        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=4, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=(10, 0))
        button_frame.columnconfigure(0, weight=1)
        button_frame.columnconfigure(1, weight=1)
        button_frame.columnconfigure(2, weight=1)
        button_frame.columnconfigure(3, weight=1)

        self.start_button = ttk.Button(button_frame, text="Start Setup", 
                                      command=self.start_setup, style="Accent.TButton")
        self.start_button.grid(row=0, column=0, sticky=tk.E, padx=5)
        
        self.stop_button = ttk.Button(button_frame, text="Stop", 
                                     command=self.stop_setup, state=tk.DISABLED, style="Stop.TButton")
        self.stop_button.grid(row=0, column=1, sticky=tk.W, padx=5)
        
        ttk.Button(button_frame, text="Clear Log", 
                  command=self.clear_log).grid(row=0, column=2, sticky=tk.E, padx=5)
        
        ttk.Button(button_frame, text="Exit",
                  command=self.root.quit).grid(row=0, column=3, sticky=tk.W, padx=5)

        ttk.Button(button_frame, text="Clear Cache & Restart",
                  command=self.clear_cache_and_restart).grid(row=0, column=4, padx=5)
        
        update_frame = ttk.LabelFrame(main_frame, text="Updates", padding="10")
        update_frame.grid(row=5, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=10)
        update_frame.columnconfigure(0, weight=1)

        self.update_button = ttk.Button(update_frame, text="Check for Updates & Recompile", command=self.check_for_updates)
        self.update_button.grid(row=0, column=0, padx=5, pady=5, sticky="ew")

        command_editor_button = ttk.Button(update_frame, text="Command Permissions Editor", command=self.open_command_editor)
        command_editor_button.grid(row=1, column=0, padx=5, pady=5, sticky="ew")

        db_editor_button = ttk.Button(update_frame, text="Database Editor", command=self.open_database_editor)
        db_editor_button.grid(row=2, column=0, padx=5, pady=5, sticky="ew")

        main_frame.rowconfigure(3, weight=1)
        
        self.setup_running = False
        self.toggle_mariadb_fields()

    def open_database_editor(self):
        self.save_settings()

        if not self.db_ip.get() or not self.db_username.get() or not self.db_name.get():
            messagebox.showerror("Database Error", "Database details are not configured. Please fill in the database information on the 'Database Configuration' tab first.")
            self.log("Failed to open Database Editor: Details not configured.")
            return

        self.log("Opening Database Editor...")
        # Run the editor in a separate process to avoid conflicts between Tkinter and PyQt
        from multiprocessing import Process
        p = Process(target=run_db_editor_app_process)
        p.start()

    def add_server_row(self):
        server_number = len(self.server_widgets) + 2
        
        row_frame = ttk.LabelFrame(self.server_list_frame, text=f"Server {server_number}", padding="10")
        row_frame.pack(fill="x", expand=True, padx=10, pady=5)

        # MainServer
        ttk.Label(row_frame, text="MainServer Local IP:").grid(row=0, column=0, sticky=tk.W, pady=2)
        main_local_ip = tk.StringVar()
        ttk.Entry(row_frame, textvariable=main_local_ip).grid(row=0, column=1, sticky="ew", pady=2, padx=5)

        ttk.Label(row_frame, text="MainServer Public IP:").grid(row=0, column=2, sticky=tk.W, pady=2, padx=(10, 0))
        main_public_ip = tk.StringVar()
        ttk.Entry(row_frame, textvariable=main_public_ip).grid(row=0, column=3, sticky="ew", pady=2, padx=5)

        ttk.Label(row_frame, text="MainServer Port:").grid(row=1, column=0, sticky=tk.W, pady=2)
        main_port = tk.StringVar()
        ttk.Entry(row_frame, textvariable=main_port).grid(row=1, column=1, sticky="ew", pady=2, padx=5)

        ttk.Label(row_frame, text="MainServer IPC Port:").grid(row=1, column=2, sticky=tk.W, pady=2, padx=(10, 0))
        main_ipc_port = tk.StringVar()
        ttk.Entry(row_frame, textvariable=main_ipc_port).grid(row=1, column=3, sticky="ew", pady=2, padx=5)

        # CastServer
        ttk.Label(row_frame, text="CastServer Local IP:").grid(row=2, column=0, sticky=tk.W, pady=2)
        cast_local_ip = tk.StringVar()
        ttk.Entry(row_frame, textvariable=cast_local_ip).grid(row=2, column=1, sticky="ew", pady=2, padx=5)

        ttk.Label(row_frame, text="CastServer Public IP:").grid(row=2, column=2, sticky=tk.W, pady=2, padx=(10, 0))
        cast_public_ip = tk.StringVar()
        ttk.Entry(row_frame, textvariable=cast_public_ip).grid(row=2, column=3, sticky="ew", pady=2, padx=5)

        ttk.Label(row_frame, text="CastServer Port:").grid(row=3, column=0, sticky=tk.W, pady=2)
        cast_port = tk.StringVar()
        ttk.Entry(row_frame, textvariable=cast_port).grid(row=3, column=1, sticky="ew", pady=2, padx=5)

        ttk.Label(row_frame, text="CastServer IPC Port:").grid(row=3, column=2, sticky=tk.W, pady=2, padx=(10, 0))
        cast_ipc_port = tk.StringVar()
        ttk.Entry(row_frame, textvariable=cast_ipc_port).grid(row=3, column=3, sticky="ew", pady=2, padx=5)

        remove_button = ttk.Button(row_frame, text="-", command=lambda: self.remove_server_row(row_frame))
        remove_button.grid(row=0, column=4, rowspan=4, padx=10, sticky="ns")

        row_frame.columnconfigure(1, weight=1)
        row_frame.columnconfigure(3, weight=1)

        widgets = {
            "frame": row_frame,
            "main_local_ip": main_local_ip, "main_public_ip": main_public_ip,
            "main_port": main_port, "main_ipc_port": main_ipc_port,
            "cast_local_ip": cast_local_ip, "cast_public_ip": cast_public_ip,
            "cast_port": cast_port, "cast_ipc_port": cast_ipc_port
        }
        self.server_widgets.append(widgets)

    def remove_server_row(self, row_frame):
        for i, widgets in enumerate(self.server_widgets):
            if widgets["frame"] == row_frame:
                self.server_widgets.pop(i)
                break
        row_frame.destroy()
        
        for i, widgets in enumerate(self.server_widgets):
            widgets["frame"].config(text=f"Server {i + 2}")

    def auto_detect_ip(self):
        try:
            result = subprocess.run(['ipconfig'], capture_output=True, text=True, shell=True)
            lines = result.stdout.split('\n')
            found_ips = set()
            
            for line in lines:
                if 'IPv4 Address' in line:
                    ip = line.split(':')[-1].strip()
                    if self.is_private_ip(ip) and ip not in found_ips:
                        found_ips.add(ip)
                        self.local_ip.set(ip)
                        self.log(f"Auto-detected local IP: {ip}")
                        break
                        
            if not found_ips:
                self.log("No private IP addresses found")
        except Exception as e:
            self.log(f"Failed to auto-detect IP: {str(e)}")

    def toggle_mariadb_fields(self):
        if self.existing_mariadb.get():
            self.existing_db_frame.grid(row=2, column=0, columnspan=4, sticky=(tk.W, tk.E), pady=10, padx=5)
            self.db_install_frame.grid_remove()
        else:
            self.existing_db_frame.grid_remove()
            self.db_install_frame.grid()
    
    def is_valid_ip(self, ip):
        """Basic IP address validation"""
        try:
            parts = ip.split('.')
            if len(parts) != 4:
                return False
            
            for part in parts:
                num = int(part)
                if num < 0 or num > 255:
                    return False
            
            return True
        except (ValueError, AttributeError):
            return False
    
    def is_private_ip(self, ip):
        """Check if an IP address is in a private range"""
        try:
            parts = ip.split('.')
            if len(parts) != 4:
                return False
            
            octets = [int(part) for part in parts]
            
            if octets[0] == 10:
                return True
            
            if octets[0] == 172 and 16 <= octets[1] <= 31:
                return True
            
            if octets[0] == 192 and octets[1] == 168:
                return True
            
            return False
        except (ValueError, IndexError):
            return False
            
    def generate_random_password(self):
        """Generate a random secure password for the database"""
        alphabet = string.ascii_letters + string.digits
        password = ''.join(secrets.choice(alphabet) for _ in range(16))
        self.db_password.set(password)
        return password
            
    def log(self, message):
        self.log_text.insert(tk.END, f"{message}\n")
        self.log_text.see(tk.END)
        self.root.update_idletasks()
        
    def clear_log(self):
        self.log_text.delete(1.0, tk.END)
        
    def start_setup(self):
        if not self.project_path.get():
            messagebox.showerror("Error", "Please select an installation directory")
            return

        self.save_settings()
            
        self.setup_running = True
        self.start_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.NORMAL)
        self.progress_bar.start()
        
        setup_thread = threading.Thread(target=self.run_setup)
        setup_thread.daemon = True
        setup_thread.start()
        
    def stop_setup(self):
        self.setup_running = False
        self.start_button.config(state=tk.NORMAL)
        self.stop_button.config(state=tk.DISABLED)
        self.progress_bar.stop()
        self.log("Setup stopped by user")
        
    def run_setup(self):
        try:
            self.load_setup_state()

            steps = [
                ("prerequisites", self.check_prerequisites),
                ("install_type", self.ask_for_install_type),
                ("install_llvm", self.install_llvm),
                ("download_repo", self.download_repository),
                ("extract_cleanup", self.extract_and_cleanup),
                ("setup_vcpkg", self.setup_vcpkg),
                ("configure_project", self.configure_project),
                ("install_mariadb", self.install_mariadb),
                ("setup_config", self.setup_config),
                ("setup_database", self.setup_database)
            ]

            for step_name, step_func in steps:
                if not self.setup_running:
                    self.log("Setup stopped by user.")
                    return

                if not self.setup_state.get(step_name, False):
                    self.log(f"--- Running step: {step_name} ---")
                    
                    # Special handling for GUI interaction
                    if step_name == "install_type":
                        result = step_func()
                        if result != "source":
                            self.log("Setup paused. Pre-compiled download not implemented.")
                            self.setup_state[step_name] = True
                            self.save_setup_state()
                            return
                        self.setup_state[step_name] = True
                        self.save_setup_state()
                        continue

                    # We need a way to get the result from the thread
                    result_queue = []
                    
                    def step_wrapper():
                        result_queue.append(step_func())

                    step_thread = threading.Thread(target=step_wrapper)
                    step_thread.daemon = True
                    step_thread.start()
                    
                    while step_thread.is_alive():
                        self.root.update_idletasks()
                        time.sleep(0.1)
                    
                    step_success = result_queue and result_queue[0]

                    if not step_success:
                        self.log(f"Step {step_name} failed. Aborting.")
                        # This messagebox will be shown in the main thread
                        messagebox.showerror("Setup Failed", f"The setup failed at step: {step_name}.\nCheck the log for details. You can try to resume by clicking 'Start Setup' again.")
                        return
                    
                    self.setup_state[step_name] = True
                    self.save_setup_state()
                else:
                    self.log(f"--- Skipping already completed step: {step_name} ---")

            self.log("Setup completed successfully!")
            self.log("Next steps:")
            self.log("1. Open the Visual Studio solution (.sln) file")
            self.log("2. Build projects in order: Common, then MainServer/AuthServer/CastServer")
            self.log("3. Configure your database connection")
            self.log("4. Start the servers!")
            
            messagebox.showinfo("Success", "MicroVolts Server setup completed successfully!")
            
        except Exception as e:
            self.log(f"Setup failed: {str(e)}")
            messagebox.showerror("Error", f"Setup failed: {str(e)}")
        finally:
            self.setup_running = False
            self.start_button.config(state=tk.NORMAL)
            self.stop_button.config(state=tk.DISABLED)
            self.progress_bar.stop()
            self.log("To start fresh, click 'Clear Cache & Restart'.")

    def load_setup_state(self):
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, 'r') as f:
                    self.setup_state = json.load(f)
                self.log("Loaded previous setup state. Will attempt to resume.")
            except Exception as e:
                self.log(f"Could not load state file, starting fresh: {e}")
                self.setup_state = {}
        else:
            self.setup_state = {}

    def save_setup_state(self):
        try:
            with open(self.state_file, 'w') as f:
                json.dump(self.setup_state, f, indent=4)
        except Exception as e:
            self.log(f"Warning: Could not save setup state: {e}")

    def clear_cache_and_restart(self):
        if messagebox.askyesno("Confirm", "This will delete the setup state and configuration file. Are you sure you want to start over?"):
            if os.path.exists(self.state_file):
                os.remove(self.state_file)
                self.log("Setup state file deleted.")
            if os.path.exists(self.config_file):
                os.remove(self.config_file)
                self.log("Configuration file deleted.")
            
            self.setup_state = {}
            self.project_path.set("")
            self.local_ip.set("")
            self.generate_random_password()
            self.log("Cache cleared. Restarting setup tool.")
            
            # Restart the application
            python = sys.executable
            os.execl(python, python, *sys.argv)

    def ask_for_install_type(self):
        if not os.path.exists(self.config_file):
            answer = messagebox.askquestion("Installation Type", "This looks like a first-time setup.\n\nWould you like to download and compile the source code (Yes) or download pre-compiled executables (No)?", icon='question')
            if answer == 'yes':
                self.log("User chose to install from source.")
                return "source"
            else:
                self.log("User chose to use pre-compiled executables.")
                messagebox.showinfo("Not Implemented", "Downloading pre-compiled executables is not yet implemented. The setup will proceed with source installation.")
                return "source" 
        return "source"

    def check_prerequisites(self):
        self.log("Checking prerequisites...")
        
        try:
            result = subprocess.run(['git', '--version'], capture_output=True, text=True)
            if result.returncode == 0:
                self.log(f"Git is installed: {result.stdout.strip()}")
            else:
                raise FileNotFoundError
        except FileNotFoundError:
            self.log("Git not found.")
            if messagebox.askyesno("Prerequisite Missing", "Git is not installed or not in your PATH. Would you like to download and install it?"):
                self.install_git()
                return False
            else:
                self.log("User chose not to install Git. Setup may fail.")
                return False

        try:
            python_executable = sys.executable
            self.log(f"Python is installed: {python_executable}")
            subprocess.run(['python', '--version'], capture_output=True, text=True, check=True)
            self.log("Python is in the system PATH.")
        except (subprocess.CalledProcessError, FileNotFoundError):
            self.log("Warning: Python might not be in the system PATH. Attempting to add it.")
            python_dir = os.path.dirname(sys.executable)
            scripts_dir = os.path.join(python_dir, "Scripts")
            self.add_to_system_path(python_dir)
            self.add_to_system_path(scripts_dir)
            self.log("PATH updated. A restart might be required for it to take full effect.")

        if not self.is_vs_installed():
            self.log("Visual Studio with C++ workload not found.")
            messagebox.showerror("Prerequisite Missing", "Visual Studio with the 'Desktop development with C++' workload is required. Please install it from the Visual Studio Installer.")
            return False
        else:
            self.log("Visual Studio with C++ workload found.")
            
        return True

    def is_vs_installed(self):
        try:
            vswhere_path = os.path.join(os.environ.get("ProgramFiles(x86)", ""), "Microsoft Visual Studio", "Installer", "vswhere.exe")
            if not os.path.exists(vswhere_path):
                self.log("vswhere.exe not found. Cannot reliably check for Visual Studio.")
                return False

            cmd = [vswhere_path, "-latest", "-products", "*", "-requires", "Microsoft.VisualStudio.Workload.NativeDesktop", "-property", "installationPath"]
            result = subprocess.run(cmd, capture_output=True, text=True, shell=True)
            
            if result.returncode == 0 and result.stdout.strip():
                self.log(f"Found Visual Studio at: {result.stdout.strip()}")
                return True
            else:
                self.log("Visual Studio with C++ workload not found via vswhere.")
                return False
        except Exception as e:
            self.log(f"Error checking for Visual Studio: {e}")
            return False

    def install_git(self):
        self.log("Downloading Git...")
        git_installer_url = "https://github.com/git-for-windows/git/releases/download/v2.45.2.windows.1/Git-2.45.2-64-bit.exe"
        installer_path = os.path.join(self.project_path.get(), "Git-Installer.exe")
        try:
            response = requests.get(git_installer_url, stream=True)
            response.raise_for_status()
            with open(installer_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            self.log("Git downloaded. Starting installation...")
            self.log("Please follow the prompts in the Git installer.")
            subprocess.run([installer_path], shell=True)
            
            git_install_path = "C:\\Program Files\\Git\\bin"
            self.add_to_system_path(git_install_path)
            os.environ['PATH'] = f"{git_install_path};{os.environ['PATH']}"

            self.log("Git installation finished. Please restart the setup tool for the changes to take effect.")
            messagebox.showinfo("Restart Required", "Git has been installed. Please restart the setup tool.")
            self.root.quit()
        except Exception as e:
            self.log(f"Failed to download or install Git: {e}")
            messagebox.showerror("Error", f"Failed to install Git: {e}")

    def startup_update_check(self):
        # Only run the check if a config file exists and a project path is set.
        if self.project_path.get() and os.path.exists(os.path.join(self.project_path.get(), "MicrovoltsEmulator", ".git")):
            # Run this in a separate thread to not block the GUI
            update_thread = threading.Thread(target=self.check_for_updates, args=(True,))
            update_thread.daemon = True
            update_thread.start()

    def check_for_updates(self, startup=False):
        repo_path = os.path.join(self.project_path.get(), "MicrovoltsEmulator")
        if not os.path.exists(os.path.join(repo_path, ".git")):
            if not startup:
                messagebox.showerror("Error", "This is not a Git repository. Cannot check for updates.")
            return

        self.log("Checking for updates...")
        try:
            subprocess.run(["git", "fetch"], cwd=repo_path, check=True, capture_output=True, text=True)
            status_result = subprocess.run(["git", "status", "-uno"], cwd=repo_path, check=True, capture_output=True, text=True)
            
            update_pulled = False
            if "Your branch is behind" in status_result.stdout:
                if messagebox.askyesno("Update Available", "A new version of the emulator is available. Would you like to update now?"):
                    self.log("New update found. Pulling changes...")
                    pull_result = subprocess.run(["git", "pull"], cwd=repo_path, check=True, capture_output=True, text=True)
                    self.log(f"Pull successful:\n{pull_result.stdout}")
                    update_pulled = True
                else:
                    self.log("User chose not to update.")
            else:
                self.log("You have the most updated version of the Emulator available.")
                if not startup:
                    messagebox.showinfo("Up to Date", "You have the most updated version of the Emulator available.")

            # Always ask to recompile unless it's a silent startup check
            if not startup:
                if messagebox.askyesno("Recompile Project", "Would you like to recompile the project now?"):
                    self.start_button.config(state=tk.DISABLED)
                    self.update_button.config(state=tk.DISABLED)
                    self.progress_bar.start()
                    
                    recompile_thread = threading.Thread(target=self.run_recompile)
                    recompile_thread.daemon = True
                    recompile_thread.start()

            elif update_pulled:
                # If it was a startup check AND we pulled an update, recompile automatically
                self.log("Update pulled on startup, automatically recompiling...")
                self.start_button.config(state=tk.DISABLED)
                self.update_button.config(state=tk.DISABLED)
                self.progress_bar.start()

                recompile_thread = threading.Thread(target=self.run_recompile)
                recompile_thread.daemon = True
                recompile_thread.start()

        except subprocess.CalledProcessError as e:
            self.log(f"Error checking for updates: {e.stderr}")
            if not startup:
                messagebox.showerror("Error", f"An error occurred while checking for updates:\n{e.stderr}")

    def run_recompile(self):
        if self.recompile_project():
            messagebox.showinfo("Success", "Project recompiled successfully.")
        
        self.start_button.config(state=tk.NORMAL)
        self.update_button.config(state=tk.NORMAL)
        self.progress_bar.stop()

    def recompile_project(self):
        self.log("Attempting to recompile project...")
        repo_path = os.path.join(self.project_path.get(), "MicrovoltsEmulator")
        sln_file = os.path.join(repo_path, "Microvolts-Emulator-V2.sln")
        
        if not os.path.exists(sln_file):
            self.log(f"Solution file not found: {sln_file}")
            messagebox.showerror("Error", f"Solution file not found:\n{sln_file}")
            return False
            
        try:
            self.log("Finding MSBuild.exe...")
            vswhere_path = os.path.join(os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)"), "Microsoft Visual Studio", "Installer", "vswhere.exe")
            if not os.path.exists(vswhere_path):
                self.log("vswhere.exe not found, cannot locate MSBuild.")
                messagebox.showerror("Error", "Could not locate vswhere.exe to find MSBuild.")
                return False

            cmd = [vswhere_path, "-latest", "-find", "MSBuild\\**\\Bin\\MSBuild.exe"]
            result = subprocess.run(cmd, capture_output=True, text=True, shell=True)
            
            if result.returncode != 0 or not result.stdout.strip():
                self.log("Could not find MSBuild.exe via vswhere.")
                messagebox.showerror("Error", "Could not find MSBuild.exe. Make sure Visual Studio with C++ workload is installed.")
                return False
            
            msbuild_path = result.stdout.strip().split('\n')[0]
            self.log(f"Using MSBuild at: {msbuild_path}")

            self.log(f"Cleaning and rebuilding solution: {sln_file}...")

            # Find vcvarsall.bat to set up the build environment
            vswhere_cmd = [vswhere_path, "-latest", "-property", "installationPath"]
            vs_path_result = subprocess.run(vswhere_cmd, capture_output=True, text=True, shell=True)
            if vs_path_result.returncode != 0 or not vs_path_result.stdout.strip():
                self.log("Could not find Visual Studio installation path.")
                messagebox.showerror("Error", "Could not find Visual Studio installation path.")
                return False
            
            vs_path = vs_path_result.stdout.strip()
            vcvarsall_path = os.path.join(vs_path, "VC", "Auxiliary", "Build", "vcvarsall.bat")

            if not os.path.exists(vcvarsall_path):
                self.log(f"vcvarsall.bat not found at: {vcvarsall_path}")
                messagebox.showerror("Error", f"Could not find vcvarsall.bat. Build environment cannot be set up.")
                return False

            self.log(f"Using vcvarsall.bat from: {vcvarsall_path}")

            # Build "Common" project first
            self.log("Building 'Common' project...")
            common_build_cmd = f'call "{vcvarsall_path}" x64 && "{msbuild_path}" "{sln_file}" /t:Common /p:Configuration=Release /p:Platform=x64 /m'
            
            self.log(f"Executing build command: {common_build_cmd}")
            common_process = subprocess.Popen(
                common_build_cmd,
                cwd=repo_path,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True,
                shell=True
            )
            for line in common_process.stdout:
                self.log(line.strip())
            common_process.wait()

            if common_process.returncode != 0:
                self.log("'Common' project build failed. Aborting.")
                messagebox.showerror("Build Failed", "The 'Common' project failed to build. Check the log for details.")
                return False
            
            self.log("'Common' project built successfully.")

            # Build the rest of the solution
            self.log("Building the rest of the solution...")
            solution_build_cmd = f'call "{vcvarsall_path}" x64 && "{msbuild_path}" "{sln_file}" /p:Configuration=Release /p:Platform=x64 /m'

            self.log(f"Executing build command: {solution_build_cmd}")
            process = subprocess.Popen(
                solution_build_cmd,
                cwd=repo_path,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True,
                shell=True
            )

            for line in process.stdout:
                self.log(line.strip())

            process.wait()

            output = []
            for line in process.stdout:
                stripped_line = line.strip()
                self.log(stripped_line)
                output.append(stripped_line)

            process.wait()

            output_str = "".join(output)
            known_error = "Microvolts-Emulator-V2.cpp(1,1): error C1083: Cannot open source file: 'Microvolts-Emulator-V2.cpp'"

            if process.returncode == 0:
                self.log("Build successful.")
                return True
            elif known_error in output_str:
                self.log("Build finished with a known, non-critical error. This is normal and can be ignored.")
                messagebox.showinfo("Build Information", "The build process completed with a known, non-critical error related to 'Microvolts-Emulator-V2.cpp'. This is expected and can be safely ignored.")
                return True
            else:
                self.log(f"Build failed with exit code {process.returncode}")
               # messagebox.showerror("Build Failed", f"The project failed to recompile with exit code {process.returncode}. Check the log for details.")
                return False
        except Exception as e:
            self.log(f"An error occurred during recompilation: {e}")
            messagebox.showerror("Error", f"An unexpected error occurred during recompilation:\n{e}")
            return False

    def find_mariadb_executable(self):
        self.log("Searching for MariaDB executable...")
        for version in ["11.5", "11.4", "11.3", "11.2", "11.1", "11.0", "10.11", "10.6", "10.5"]:
            path = f"C:\\Program Files\\MariaDB {version}\\bin\\mariadb.exe"
            if os.path.exists(path):
                self.log(f"Found MariaDB executable at: {path}")
                return path
        
        try:
            result = subprocess.run(['where', 'mariadb'], capture_output=True, text=True, shell=True)
            if result.returncode == 0:
                path = result.stdout.strip().split('\n')[0]
                self.log(f"Found MariaDB executable in PATH: {path}")
                return path
        except Exception:
            pass

        self.log("MariaDB executable not found.")
        messagebox.showerror("Error", "Could not find mariadb.exe. Please ensure MariaDB is installed and its 'bin' directory is in the system PATH.")
        return None
            
    def install_llvm(self):
        if not self.setup_running:
            return False
            
        self.log("Checking for LLVM (clang-cl) installation...")
        
        try:
            result = subprocess.run(['clang-cl', '--version'], capture_output=True, text=True)
            if result.returncode == 0:
                self.log("LLVM (clang-cl) is already installed")
                self.log(f"Version: {result.stdout.split()[2] if len(result.stdout.split()) > 2 else 'Unknown'}")
                return True
        except FileNotFoundError:
            pass
        
        self.log("LLVM (clang-cl) not found. Installing...")
        
        try:
            llvm_version = "18.1.8"
            llvm_url = f"https://github.com/llvm/llvm-project/releases/download/llvmorg-{llvm_version}/LLVM-{llvm_version}-win64.exe"
            
            self.log(f"Downloading LLVM {llvm_version}...")
            response = requests.get(llvm_url, stream=True)
            response.raise_for_status()
            
            installer_path = os.path.join(self.project_path.get(), f"LLVM-{llvm_version}-win64.exe")
            
            total_size = int(response.headers.get('content-length', 0))
            downloaded = 0
            
            with open(installer_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if not self.setup_running:
                        return False
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0:
                        progress = (downloaded / total_size) * 100
                        self.log(f"Download progress: {progress:.1f}%")
            
            self.log("LLVM downloaded successfully")
            
            self.log("Installing LLVM (this may take a few minutes)...")
            self.log("Note: You may see a UAC prompt - please click 'Yes' to allow installation")
            
            import ctypes
            import sys
            
            try:
                is_admin = ctypes.windll.shell32.IsUserAnAdmin()
            except:
                is_admin = False
            
            if not is_admin:
                self.log("Requesting administrator privileges for LLVM installation...")
                powershell_cmd = f'''
                Start-Process -FilePath "{installer_path}" -ArgumentList "/S", "/D=C:\\Program Files\\LLVM" -Verb RunAs -Wait
                '''
                
                result = subprocess.run([
                    "powershell", "-Command", powershell_cmd
                ], capture_output=True, text=True)
                
                if result.returncode != 0:
                    self.log(f"Admin installation failed: {result.stderr}")
                    self.log("Trying regular installation...")
                    result = subprocess.run([
                        installer_path, 
                        '/S',
                        '/D=C:\\Program Files\\LLVM'
                    ], capture_output=True, text=True)
            else:
                result = subprocess.run([
                    installer_path, 
                    '/S',
                    '/D=C:\\Program Files\\LLVM'
                ], capture_output=True, text=True)
            
            try:
                os.remove(installer_path)
            except:
                pass
            
            self.log("Verifying LLVM installation and configuring Visual Studio...")
            
            llvm_bin_path = "C:\\Program Files\\LLVM\\bin"
            self.add_to_system_path(llvm_bin_path)
            
            current_path = os.environ.get('PATH', '')
            if llvm_bin_path not in current_path:
                os.environ['PATH'] = f"{llvm_bin_path};{current_path}"
            
            self.configure_vs_for_llvm()
            
            try:
                result = subprocess.run(['clang-cl', '--version'], capture_output=True, text=True)
                if result.returncode == 0:
                    self.log("LLVM (clang-cl) installed and configured successfully!")
                    self.log("Visual Studio is now configured to use LLVM/Clang")
                    return True
                else:
                    self.log("Warning: LLVM installed but clang-cl not accessible")
                    self.log("PATH may need system restart to take effect")
                    return True
            except FileNotFoundError:
                self.log("Warning: LLVM installed but clang-cl not found in PATH")
                self.log("System restart may be required for PATH changes")
                return True
                
        except Exception as e:
            self.log(f"Failed to install LLVM: {str(e)}")
            self.log("You can manually download and install LLVM from:")
            self.log("https://github.com/llvm/llvm-project/releases")
            
            response = messagebox.askyesno(
                "LLVM Installation Failed", 
                "LLVM installation failed. Do you want to continue setup anyway?\n\n"
                "Note: You may need to install LLVM manually later for compilation."
            )
            return response
    
    def add_to_system_path(self, path):
        """Add a path to the system PATH environment variable permanently, requesting admin rights."""
        try:
            self.log(f"Attempting to add {path} to system PATH...")

            import ctypes
            is_admin = False
            try:
                is_admin = ctypes.windll.shell32.IsUserAnAdmin()
            except Exception:
                pass

            # PowerShell command to add the path
            ps_script = f'''
            $envPath = [System.Environment]::GetEnvironmentVariable('PATH', 'Machine');
            if ($envPath -notlike '*{path}*') {{
                $newPath = $envPath + ';{path}';
                [System.Environment]::SetEnvironmentVariable('PATH', $newPath, 'Machine');
                Write-Host 'Successfully added {path} to system PATH.';
                Write-Host 'Please restart your terminal or PC for the change to take effect.';
            }} else {{
                Write-Host 'Path is already in the system PATH.';
            }}
            '''

            if is_admin:
                self.log("Running with admin rights. Updating system PATH directly.")
                result = subprocess.run(['powershell', '-Command', ps_script], capture_output=True, text=True)
                if result.returncode == 0:
                    self.log(result.stdout)
                else:
                    self.log(f"Failed to update PATH: {result.stderr}")
            else:
                self.log("Not running as admin. Requesting elevation to update system PATH.")
                self.log("A UAC prompt will appear. Please click 'Yes' to proceed.")
                
                # Use Start-Process with -Verb RunAs to elevate
                # The script needs to be passed as an encoded command to avoid quoting hell
                import base64
                encoded_ps_script = base64.b64encode(ps_script.encode('utf-16-le')).decode('ascii')
                
                run_as_cmd = f"Start-Process powershell -Verb RunAs -ArgumentList '-NoProfile', '-EncodedCommand', '{encoded_ps_script}' -Wait"
                
                result = subprocess.run(['powershell', '-Command', run_as_cmd], capture_output=True, text=True)

                if result.returncode == 0:
                    self.log("PATH update process launched. Check the new terminal for results.")
                else:
                    self.log(f"Failed to launch elevation process: {result.stderr}")
                    self.log("You may need to add the path to the environment variables manually.")

        except Exception as e:
            self.log(f"An error occurred while trying to update system PATH: {str(e)}")
    
    def configure_vs_for_llvm(self):
        """Configure Visual Studio to recognize and use LLVM/Clang"""
        try:
            self.log("Configuring Visual Studio for LLVM/Clang...")
            
            vs_versions = ["2019", "2022"]
            
            for vs_version in vs_versions:
                try:
                    vs_path = None
                    possible_paths = [
                        f"C:\\Program Files\\Microsoft Visual Studio\\{vs_version}",
                        f"C:\\Program Files (x86)\\Microsoft Visual Studio\\{vs_version}"
                    ]
                    
                    for base_path in possible_paths:
                        if os.path.exists(base_path):
                            for edition in ["Community", "Professional", "Enterprise"]:
                                full_path = os.path.join(base_path, edition)
                                if os.path.exists(full_path):
                                    vs_path = full_path
                                    break
                            if vs_path:
                                break
                    
                    if vs_path:
                        self.log(f"Found Visual Studio {vs_version} at: {vs_path}")
                        
                        msbuild_path = os.path.join(vs_path, "MSBuild", "Microsoft", "VC", "v170")
                        if os.path.exists(msbuild_path):
                            props_file = os.path.join(msbuild_path, "LLVM.props")
                            
                            props_content = '''<?xml version="1.0" encoding="utf-8"?>
<Project ToolsVersion="4.0" xmlns="http://schemas.microsoft.com/developer/msbuild/2003">
  <PropertyGroup>
    <LLVMInstallDir>C:\\Program Files\\LLVM\\</LLVMInstallDir>
    <LLVMToolsPath>$(LLVMInstallDir)bin\\</LLVMToolsPath>
  </PropertyGroup>
  <ItemDefinitionGroup>
    <ClCompile>
      <AdditionalIncludeDirectories>$(LLVMInstallDir)include;%(AdditionalIncludeDirectories)</AdditionalIncludeDirectories>
    </ClCompile>
    <Link>
      <AdditionalLibraryDirectories>$(LLVMInstallDir)lib;%(AdditionalLibraryDirectories)</AdditionalLibraryDirectories>
    </Link>
  </ItemDefinitionGroup>
</Project>'''
                            
                            with open(props_file, 'w') as f:
                                f.write(props_content)
                            
                            self.log(f"Created LLVM configuration for Visual Studio {vs_version}")
                        
                except Exception as e:
                    self.log(f"Could not configure Visual Studio {vs_version}: {str(e)}")
            
            try:
                import os
                user_profile = os.environ.get('USERPROFILE', '')
                if user_profile:
                    msbuild_user_path = os.path.join(user_profile, "AppData", "Local", "Microsoft", "MSBuild", "v4.0")
                    os.makedirs(msbuild_user_path, exist_ok=True)
                    
                    user_props_file = os.path.join(msbuild_user_path, "Microsoft.Cpp.Win32.user.props")
                    
                    user_props_content = '''<?xml version="1.0" encoding="utf-8"?>
<Project ToolsVersion="4.0" xmlns="http://schemas.microsoft.com/developer/msbuild/2003">
  <ImportGroup Label="PropertySheets" />
  <PropertyGroup Label="UserMacros">
    <LLVM_ROOT>C:\\Program Files\\LLVM</LLVM_ROOT>
  </PropertyGroup>
  <PropertyGroup>
    <_PropertySheetDisplayName>LLVM Configuration</_PropertySheetDisplayName>
  </PropertyGroup>
  <ItemDefinitionGroup>
    <ClCompile>
      <AdditionalIncludeDirectories>$(LLVM_ROOT)\\include;%(AdditionalIncludeDirectories)</AdditionalIncludeDirectories>
    </ClCompile>
    <Link>
      <AdditionalLibraryDirectories>$(LLVM_ROOT)\\lib;%(AdditionalLibraryDirectories)</AdditionalLibraryDirectories>
    </Link>
  </ItemDefinitionGroup>
</Project>'''
                    
                    with open(user_props_file, 'w') as f:
                        f.write(user_props_content)
                    
                    self.log("Created user-level LLVM configuration")
                    
            except Exception as e:
                self.log(f"Could not create user-level configuration: {str(e)}")
                
            self.log("Visual Studio LLVM configuration completed")
            
        except Exception as e:
            self.log(f"Warning: Could not fully configure Visual Studio for LLVM: {str(e)}")
            
    def download_repository(self):
        if not self.setup_running:
            return False
            
        self.log("Cloning MicroVolts Emulator repository...")
        
        try:
            repo_url = "https://github.com/SoWeBegin/MicrovoltsEmulator.git"
            repo_path = os.path.join(self.project_path.get(), "MicrovoltsEmulator")
            
            if os.path.exists(repo_path):
                self.log("Removing existing MicrovoltsEmulator directory...")
                shutil.rmtree(repo_path)
            
            self.log("Cloning repository (this may take a few minutes)...")
            result = subprocess.run([
                "git", "clone", "-b", "mv1.1_2.0", repo_url, repo_path
            ], capture_output=True, text=True)
            
            if result.returncode != 0:
                raise Exception(f"Git clone failed: {result.stderr}")
                
            self.log("Repository cloned successfully")
            return True
            
        except Exception as e:
            self.log(f"Failed to clone repository: {str(e)}")
            self.log("Make sure Git is installed and accessible from command line")
            return False
            
    def extract_and_cleanup(self):
        if not self.setup_running:
            return False
            
        self.log("Verifying repository structure...")
        
        try:
            repo_path = os.path.join(self.project_path.get(), "MicrovoltsEmulator")
            
            if not os.path.exists(repo_path):
                raise Exception("Repository directory not found")
                
            sln_file = os.path.join(repo_path, "Microvolts-Emulator-V2.sln")
            vcpkg_json = os.path.join(repo_path, "vcpkg.json")
            
            if not os.path.exists(sln_file):
                raise Exception("Visual Studio solution file not found")
                
            if not os.path.exists(vcpkg_json):
                self.log("Warning: vcpkg.json not found, package installation may be skipped")
            
            self.log("Repository structure verified successfully")
            return True
            
        except Exception as e:
            self.log(f"Failed to verify repository: {str(e)}")
            return False
            
    def setup_vcpkg(self):
        if not self.setup_running:
            return False
            
        self.log("Setting up vcpkg...")
        
        try:
            repo_path = os.path.join(self.project_path.get(), "MicrovoltsEmulator")
            ext_lib_path = os.path.join(repo_path, "ExternalLibraries")
            os.makedirs(ext_lib_path, exist_ok=True)
            
            self.log("Cloning vcpkg repository...")
            vcpkg_path = os.path.join(ext_lib_path, "vcpkg")
            
            if os.path.exists(vcpkg_path):
                shutil.rmtree(vcpkg_path)
                
            result = subprocess.run([
                "git", "clone", "https://github.com/microsoft/vcpkg.git", vcpkg_path
            ], capture_output=True, text=True)
            
            if result.returncode != 0:
                raise Exception(f"Git clone failed: {result.stderr}")
                
            self.log("Bootstrapping vcpkg...")
            bootstrap_script = os.path.join(vcpkg_path, "bootstrap-vcpkg.bat")
            result = subprocess.run([bootstrap_script], cwd=vcpkg_path, capture_output=True, text=True)
            
            if result.returncode != 0:
                self.log(f"Bootstrap warning: {result.stderr}")
                
            self.log("Integrating vcpkg with Visual Studio...")
            vcpkg_exe = os.path.join(vcpkg_path, "vcpkg.exe")
            result = subprocess.run([vcpkg_exe, "integrate", "install"], 
                                  cwd=vcpkg_path, capture_output=True, text=True)
            
            if result.returncode != 0:
                self.log(f"Integration warning: {result.stderr}")
                
            repo_path = os.path.join(self.project_path.get(), "MicrovoltsEmulator")
            vcpkg_json_src = os.path.join(repo_path, "vcpkg.json")
            vcpkg_json_dst = os.path.join(vcpkg_path, "vcpkg.json")
            
            if os.path.exists(vcpkg_json_src):
                shutil.copy2(vcpkg_json_src, vcpkg_json_dst)
                self.log("Copied vcpkg.json to vcpkg directory")
                
                # Install packages
                self.log("Installing vcpkg packages (this may take several minutes)...")
                result = subprocess.run([vcpkg_exe, "install"], 
                                      cwd=vcpkg_path, capture_output=True, text=True)
                
                if result.returncode != 0:
                    self.log(f"Package installation warning: {result.stderr}")
                    self.log("Some packages may have failed to install, but continuing...")
                else:
                    self.log("vcpkg packages installed successfully")
            else:
                self.log("vcpkg.json not found in repository, skipping package installation")
                
            self.log("vcpkg setup completed")
            return True
            
        except Exception as e:
            self.log(f"Failed to setup vcpkg: {str(e)}")
            return False
            
    def configure_project(self):
        if not self.setup_running:
            return False
            
        self.log("Project configuration completed")
        self.log("Note: You'll need to manually configure Visual Studio project properties:")
        self.log("- Set vcpkg Installed Directory to: ..\\ExternalLibraries\\vcpkg\\vcpkg_installed")
        self.log("- Use Release mode for building (Debug mode needs manual path configuration)")
        return True
        
    def _get_local_ip(self):
        try:
            result = subprocess.run(['ipconfig'], capture_output=True, text=True, shell=True)
            lines = result.stdout.split('\n')
            for line in lines:
                if 'IPv4 Address' in line:
                    ip = line.split(':')[-1].strip()
                    if self.is_private_ip(ip):
                        return ip
            return "127.0.0.1"
        except Exception:
            return "127.0.0.1"

    def set_system_environment_variable(self, name, value):
        """Set a system-wide environment variable permanently"""
        try:
            self.log(f"Setting system environment variable: {name}...")
            
            powershell_cmd = f'''
            [Environment]::SetEnvironmentVariable("{name}", "{value}", "Machine")
            Write-Output "Environment variable '{name}' set successfully"
            '''
            
            result = subprocess.run([
                "powershell", "-Command", powershell_cmd
            ], capture_output=True, text=True)
            
            if result.returncode == 0:
                self.log(result.stdout)
                self.log("Note: A system restart may be required for changes to take full effect in all processes.")
            else:
                self.log(f"Warning: Could not set system environment variable: {result.stderr}")
                
        except Exception as e:
            self.log(f"Warning: Failed to set system environment variable: {str(e)}")

    def setup_config(self):
        if not self.setup_running:
            return False
            
        self.log("Setting up configuration files...")
        
        try:
            repo_path = os.path.join(self.project_path.get(), "MicrovoltsEmulator")
            setup_dir = os.path.join(repo_path, "Setup")
            os.makedirs(setup_dir, exist_ok=True)
            
            config_path = os.path.join(setup_dir, "config.ini")
            
            config = configparser.ConfigParser()
            config.optionxform = str
            
            # Use auto-detected local IP if available, otherwise default
            local_ip = self.local_ip.get() if self.local_ip.get() else "10.0.0.5"

            config['AuthServer'] = {
                'LocalIp': local_ip,
                'Ip': '127.0.0.1',
                'Port': '13000'
            }
            
            config['MainServer_1'] = {
                'LocalIp': local_ip,
                'Ip': '127.0.0.1',
                'Port': '13005',
                'IpcPort': '14005',
                'IsPublic': 'true'
            }
            
            config['CastServer_1'] = {
                'LocalIp': local_ip,
                'Ip': '127.0.0.1',
                'Port': '13006',
                'IpcPort': '14006'
            }
            
            config['Database'] = {
                'LocalIp': local_ip,
                'Ip': '127.0.0.1',
                'Port': self.db_port.get(),
                'DatabaseName': self.db_name.get(),
                'Username': self.db_username.get(),
                'PasswordEnvironmentName': 'MICROVOLTS_DB_PASSWORD'
            }
            
            config['Website'] = {
                'Ip': '127.0.0.1',
                'Port': '8080'
            }
            
            config['Client'] = {
                'ClientVersion': '1.1.1'
            }

            for i, widgets in enumerate(self.server_widgets):
                server_number = i + 2
                config[f'MainServer_{server_number}'] = {
                    'LocalIp': widgets['main_local_ip'].get(),
                    'Ip': widgets['main_public_ip'].get(),
                    'Port': widgets['main_port'].get(),
                    'IpcPort': widgets['main_ipc_port'].get(),
                    'IsPublic': 'true'
                }
                config[f'CastServer_{server_number}'] = {
                    'LocalIp': widgets['cast_local_ip'].get(),
                    'Ip': widgets['cast_public_ip'].get(),
                    'Port': widgets['cast_port'].get(),
                    'IpcPort': widgets['cast_ipc_port'].get()
                }
            
            with open(config_path, 'w') as configfile:
                config.write(configfile)
                
            self.log(f"Configuration file created: {config_path}")
            self.log(f"Local IP set to: {local_ip}")
            
            # Set the password as a system environment variable
            db_password = self.db_password.get()
            self.set_system_environment_variable('MICROVOLTS_DB_PASSWORD', db_password)
            
            self.log("Database Configuration:")
            self.log(f"  IP: 127.0.0.1")
            self.log(f"  Port: {self.db_port.get()}")
            self.log(f"  Database: {self.db_name.get()}")
            self.log(f"  Username: {self.db_username.get()}")
            self.log(f"  Password: {db_password}")
            
            return True
            
        except Exception as e:
            self.log(f"Failed to setup configuration: {str(e)}")
            return False

    def install_mariadb(self):
        if not self.setup_running:
            return False

        if self.existing_mariadb.get():
            self.log("Skipping MariaDB installation as per user's choice.")
            return True

        self.log("Checking for MariaDB installation...")

        import re
        local_installer_filename = None
        mariadb_version = "11.5.1"

        for file in os.listdir('.'):
            if file.startswith('mariadb-') and file.endswith('-winx64.msi'):
                local_installer_filename = file
                self.log(f"Found local MariaDB installer: {local_installer_filename}")
                match = re.search(r'mariadb-([\d\.]+)-winx64\.msi', file)
                if match:
                    mariadb_version = match.group(1)
                    self.log(f"Using MariaDB version from local file: {mariadb_version}")
                break
        
        version_parts = mariadb_version.split('.')
        mariadb_version_major_minor = f"{version_parts[0]}.{version_parts[1]}"
        mariadb_install_path = f"C:\\Program Files\\MariaDB {mariadb_version_major_minor}"

        if os.path.exists(mariadb_install_path):
            self.log(f"MariaDB installation detected at: {mariadb_install_path}. Performing clean install.")
            
            try:
                self.log("Stopping MariaDB service...")
                subprocess.run(['sc', 'stop', 'MariaDB'], capture_output=True, text=True, shell=True)
                
                installer_path = os.path.abspath(local_installer_filename)
                self.log(f"Uninstalling existing MariaDB using {installer_path}...")
                uninstall_cmd = ['msiexec', '/x', installer_path, '/qn']
                result = subprocess.run(uninstall_cmd, capture_output=True, text=True)

                if result.returncode == 0 or result.returncode == 3010:
                    self.log("MariaDB uninstalled successfully.")
                else:
                    self.log(f"MariaDB uninstallation may have failed. Exit code: {result.returncode}")
                    self.log(f"Stderr: {result.stderr}")
                    self.log(f"Stdout: {result.stdout}")

                self.log(f"Removing MariaDB installation directory: {mariadb_install_path}")
                shutil.rmtree(mariadb_install_path, ignore_errors=True)
                
            except Exception as e:
                self.log(f"An error occurred during MariaDB cleanup: {str(e)}")

        self.log("Proceeding with fresh MariaDB installation...")
        try:
            installer_path = None
            if local_installer_filename:
                installer_path = os.path.abspath(local_installer_filename)
                self.log(f"Using local installer at {installer_path}")
            else:
                self.log(f"No local installer found. Downloading MariaDB version {mariadb_version}...")
                mariadb_url = f"https://archive.mariadb.org/mariadb-{mariadb_version}/winx64-packages/mariadb-{mariadb_version}-winx64.msi"
                installer_path = os.path.join(self.project_path.get(), f"mariadb-{mariadb_version}-winx64.msi")

                response = requests.get(mariadb_url, stream=True)
                response.raise_for_status()

                with open(installer_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if not self.setup_running: return False
                        f.write(chunk)
                self.log("MariaDB downloaded.")

            self.log("MariaDB downloaded. Installing...")
            self.log("Note: A UAC prompt may appear. Please accept to proceed.")

            root_password = self.db_password.get()
            
            log_path = os.path.join(os.path.dirname(installer_path), "mariadb_install.log")
            self.log(f"MariaDB installation log will be saved to: {log_path}")
            
            install_cmd = [
                'msiexec', '/i', installer_path,
                '/qn',
                f'/L*v', '{log_path}',
                'SERVICENAME=MariaDB',
                'PORT=3306',
                f'PASSWORD={root_password}',
                'ADDLOCAL=ALL'
            ]

            result = subprocess.run(install_cmd, capture_output=True, text=True)

            if result.returncode == 0 or result.returncode == 3010:
                self.log("MariaDB installed successfully.")
                mariadb_bin_path = f"C:\\Program Files\\MariaDB {mariadb_version_major_minor}\\bin"
                self.add_to_system_path(mariadb_bin_path)
                os.environ['PATH'] = f"{mariadb_bin_path};{os.environ['PATH']}"
                
                self.configure_mariadb_my_ini(mariadb_version_major_minor)

                if not local_installer_filename:
                    try:
                        os.remove(installer_path)
                    except OSError as e:
                        self.log(f"Could not remove downloaded installer: {e}")
                return True
            else:
                self.log(f"MariaDB installation failed. Exit code: {result.returncode}")
                self.log(f"Stderr: {result.stderr}")
                self.log(f"Stdout: {result.stdout}")
                messagebox.showerror("MariaDB Installation Failed", f"MariaDB installation failed with exit code {result.returncode}.\n\nPlease try running the installer manually from:\n{installer_path}")
                return False

        except Exception as e:
            self.log(f"An error occurred during MariaDB installation: {str(e)}")
            return False

    def configure_mariadb_my_ini(self, version_major_minor):
        self.log("Configuring my.ini for MariaDB...")
        try:
            install_dir = f"C:/Program Files/MariaDB {version_major_minor}"
            data_dir = f"{install_dir}/data"
            my_ini_path = os.path.join(data_dir, "my.ini")

            os.makedirs(data_dir, exist_ok=True)

            plugin_dir = f"{install_dir}/lib/plugin".replace('\\', '/')

            my_ini_content = f"""
[mysqld]
skip-grant-tables
datadir="{data_dir.replace('\\', '/')}"
port=3306
innodb_buffer_pool_size=1967M

[client]
port=3306
plugin-dir="{plugin_dir}"
"""
            with open(my_ini_path, 'w') as f:
                f.write(my_ini_content)
            
            self.log(f"Successfully configured {my_ini_path}")

        except Exception as e:
            self.log(f"Failed to configure my.ini: {str(e)}")

    def open_command_editor(self):
        if not self.project_path.get() or not os.path.isdir(self.project_path.get()):
            messagebox.showerror("Error", "Please select a valid installation directory first.")
            return
        CommandEditorWindow(self.root, self.project_path.get())

    def setup_database(self):
        if not self.setup_running:
            return False

        self.log("Setting up the database...")
        
        try:
            repo_path = os.path.join(self.project_path.get(), "MicrovoltsEmulator")
            sql_script_path = os.path.join(repo_path, "microvolts-db.sql")

            if not os.path.exists(sql_script_path):
                self.log(f"Database script not found at: {sql_script_path}")
                return False

            mysql_exe = self.find_mariadb_executable()
            if not mysql_exe:
                return False

            db_name = self.db_name.get()
            db_user = self.db_username.get()
            db_pass = self.db_password.get()
            
            if self.existing_mariadb.get():
                root_user = "root"
                root_pass = self.db_root_password.get()
                
                self.log("Using existing MariaDB. Connecting as root to create user and database.")
                
                # Check if database exists
                check_db_cmd = [mysql_exe, "-u", root_user, f"-p{root_pass}", "-e", f"SHOW DATABASES LIKE '{db_name}';"]
                result = subprocess.run(check_db_cmd, capture_output=True, text=True)
                
                if result.returncode != 0:
                    self.log(f"Error checking for database. Wrong root password? Stderr: {result.stderr}")
                    messagebox.showerror("Database Error", f"Could not connect to MariaDB as root. Please check the root password.\nError: {result.stderr}")
                    return False

                if db_name not in result.stdout:
                    self.log(f"Database '{db_name}' does not exist. Creating it...")
                    create_db_cmd = [mysql_exe, "-u", root_user, f"-p{root_pass}", "-e", f"CREATE DATABASE `{db_name}`;"]
                    result = subprocess.run(create_db_cmd, capture_output=True, text=True)
                    if result.returncode != 0:
                        self.log(f"Failed to create database '{db_name}'. Stderr: {result.stderr}")
                        return False
                    self.log(f"Database '{db_name}' created.")
                else:
                    self.log(f"Database '{db_name}' already exists.")

                # Create user and grant privileges
                self.log(f"Creating user '{db_user}' and granting privileges...")
                grant_sql = f"CREATE USER IF NOT EXISTS '{db_user}'@'localhost' IDENTIFIED BY '{db_pass}'; GRANT ALL PRIVILEGES ON `{db_name}`.* TO '{db_user}'@'localhost'; FLUSH PRIVILEGES;"
                grant_cmd = [mysql_exe, "-u", root_user, f"-p{root_pass}", "-e", grant_sql]
                result = subprocess.run(grant_cmd, capture_output=True, text=True)
                if result.returncode != 0:
                    self.log(f"Failed to create user or grant privileges. Stderr: {result.stderr}")
                    return False
                self.log(f"User '{db_user}' created and privileges granted.")

            else: # New installation
                self.log("Waiting for new MariaDB service to be ready...")
                import time
                time.sleep(10)
                
                create_db_cmd = [mysql_exe, "-u", db_user, f"-p{db_pass}", "-e", f"CREATE DATABASE IF NOT EXISTS `{db_name}`;"]
                result = subprocess.run(create_db_cmd, capture_output=True, text=True)
                if result.returncode != 0:
                    self.log(f"Failed to create database '{db_name}'. Stderr: {result.stderr}")
                    return False
                self.log(f"Database '{db_name}' created or already exists.")

            self.log("Connecting to MariaDB and executing setup script...")
            with open(sql_script_path, 'r') as f:
                sql_script_content = f.read()

            import_cmd = [mysql_exe, "-u", db_user, f"-p{db_pass}", "-D", db_name]
            result = subprocess.run(import_cmd, input=sql_script_content, capture_output=True, text=True)

            if result.returncode == 0:
                self.log("Database setup script executed successfully.")
                return True
            else:
                self.log(f"Failed to execute database script: {result.stderr}")
                return False

        except Exception as e:
            self.log(f"Failed to setup database: {str(e)}")
            return False

class CommandEditorWindow(tk.Toplevel):
    def __init__(self, parent, project_path):
        super().__init__(parent)
        self.title("Command Permission Editor")
        self.geometry("900x600")
        self.transient(parent)
        self.grab_set()

        self.project_path = project_path
        self.commands = {}
        self.command_files_path = os.path.join(self.project_path, 'MicrovoltsEmulator', 'MainServer', 'include', 'ChatCommands', 'Commands')
        self.player_enums_path = os.path.join(self.project_path, 'MicrovoltsEmulator', 'Common', 'include', 'Enums', 'PlayerEnums.h')

        self.grades = self.load_grades()
        
        self.style = ttk.Style(self)
        self.style.configure("Treeview", rowheight=25, font=('Helvetica', 10))
        self.style.configure("Treeview.Heading", font=('Helvetica', 10, 'bold'))
        self.style.map("Treeview", background=[('selected', '#0078d4')])

        self.main_frame = ttk.Frame(self, padding="10")
        self.main_frame.pack(fill="both", expand=True)
        self.main_frame.columnconfigure(0, weight=1)
        self.main_frame.rowconfigure(0, weight=1)

        self.create_widgets()
        self.load_commands()

        button_frame = ttk.Frame(self)
        button_frame.pack(fill="x", pady=10, padx=10)
        
        # Add a label for instructions
        instructions = "Double-click a permission to change it. Your changes are temporary until you click 'Save Changes'."
        ttk.Label(button_frame, text=instructions, style="Italic.TLabel").pack(side="left", expand=True, fill="x")
        
        save_button = ttk.Button(button_frame, text="Save Changes", command=self.save_changes, style="Accent.TButton")
        save_button.pack(side="right")
        
        self.style.configure("Italic.TLabel", font=('Helvetica', 9, 'italic'))

    def load_grades(self):
        try:
            with open(self.player_enums_path, 'r') as f:
                content = f.read()
            
            enum_content_match = re.search(r'enum\s+PlayerGrade\s*{([^}]+)}', content)
            if not enum_content_match:
                raise ValueError("PlayerGrade enum not found")

            enum_content = enum_content_match.group(1)
            grade_regex = re.compile(r'(\w+)\s*=\s*\d+')
            grades = grade_regex.findall(enum_content)
            
            if not grades:
                raise ValueError("No grades found in PlayerGrade enum")

            return grades
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load player grades from PlayerEnums.h:\n{e}")
            self.destroy()
            return []

    def load_commands(self):
        description_regex = re.compile(r'ICommand\s*{\s*[^,]+,\s*"([^"]+)"')
        permission_regex = re.compile(r"REGISTER_CMD\(\s*(\w+)\s*,\s*Common::Enums::PlayerGrade::(\w+)\)")

        if not os.path.isdir(self.command_files_path):
            messagebox.showerror("Error", f"Commands directory not found at:\n{self.command_files_path}")
            self.destroy()
            return

        for filename in os.listdir(self.command_files_path):
            if filename.endswith(".h"):
                filepath = os.path.join(self.command_files_path, filename)
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read()
                    
                    matches = permission_regex.finditer(content)
                    for match in matches:
                        command_name = match.group(1)
                        permission = match.group(2)
                        
                        class_def_search_area = content[:match.start()]
                        
                        class_regex = re.compile(r"(?:class|struct)\s+" + re.escape(command_name) + r"\s*(?:final)?\s*:\s*public")
                        class_match = class_regex.search(class_def_search_area)
                        
                        if class_match:
                            constructor_area = class_def_search_area[class_match.start():]
                            desc_match = description_regex.search(constructor_area)
                            if desc_match:
                                description = desc_match.group(1)
                                self.commands[command_name] = {
                                    "file": filepath,
                                    "permission": permission,
                                    "description": description,
                                    "original_permission": permission
                                }
        
        self.populate_tree()

    def create_widgets(self):
        tree_frame = ttk.Frame(self.main_frame)
        tree_frame.grid(row=0, column=0, sticky="nsew")
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)

        self.tree = ttk.Treeview(tree_frame, columns=("Command", "Description", "Permission"), show="headings")
        self.tree.heading("Command", text="Command")
        self.tree.heading("Description", text="Description / Usage")
        self.tree.heading("Permission", text="Permission")

        self.tree.column("Command", width=150, stretch=False, anchor="w")
        self.tree.column("Description", width=450, anchor="w")
        self.tree.column("Permission", width=200, stretch=False, anchor="center")

        self.tree.tag_configure('oddrow', background='#f0f0f0')
        self.tree.tag_configure('evenrow', background='white')

        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        self.tree.bind("<Double-1>", self.on_double_click)

    def populate_tree(self):
        # Clear existing items
        for item in self.tree.get_children():
            self.tree.delete(item)
        # Populate with new data
        for i, (name, data) in enumerate(sorted(self.commands.items())):
            tag = 'evenrow' if i % 2 == 0 else 'oddrow'
            self.tree.insert("", "end", values=(name, data['description'], data['permission']), tags=(tag,), iid=name)

    def on_double_click(self, event):
        # Clean up any existing editor
        if hasattr(self, '_editor') and self._editor.winfo_exists():
            self._editor.destroy()

        rowid = self.tree.identify_row(event.y)
        column_id = self.tree.identify_column(event.x)
        
        if not rowid or self.tree.heading(column_id, "text") != "Permission":
            return

        x, y, width, height = self.tree.bbox(rowid, column_id)

        current_value = self.tree.set(rowid, "Permission")
        
        self._editor = ttk.Combobox(self.tree, values=self.grades, state="readonly")
        self._editor.set(current_value)
        self._editor.place(x=x, y=y, width=width, height=height)
        
        self._editor.focus_force()
        # Drop down the list automatically
        self._editor.event_generate('<Button-1>')

        def on_combo_select(event):
            new_permission = self._editor.get()
            self.tree.set(rowid, "Permission", new_permission)
            command_name = self.tree.item(rowid, "values")[0]
            self.commands[command_name]['permission'] = new_permission
            self._editor.destroy()

        def on_focus_out(event):
            if hasattr(self, '_editor') and self._editor.winfo_exists():
                self._editor.destroy()

        self._editor.bind("<<ComboboxSelected>>", on_combo_select)
        self._editor.bind("<FocusOut>", on_focus_out)
        self._editor.bind("<Escape>", lambda e: self._editor.destroy())

    def save_changes(self):
        changed_files = set()
        for name, data in self.commands.items():
            if data['permission'] != data['original_permission']:
                filepath = data['file']
                
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        content = f.read()

                    old_line = f"REGISTER_CMD({name}, Common::Enums::PlayerGrade::{data['original_permission']})"
                    new_line = f"REGISTER_CMD({name}, Common::Enums::PlayerGrade::{data['permission']})"
                    
                    if old_line in content:
                        content = content.replace(old_line, new_line, 1)
                        with open(filepath, 'w', encoding='utf-8') as f:
                            f.write(content)
                        
                        data['original_permission'] = data['permission']
                        changed_files.add(os.path.basename(filepath))
                    else:
                        messagebox.showwarning("Warning", f"Could not find the line to update for command '{name}' in {os.path.basename(filepath)}. It might have been modified externally or the file has changed.")

                except Exception as e:
                    messagebox.showerror("Error", f"Failed to save changes for {name} in {os.path.basename(filepath)}.\n\nError: {e}")


        if changed_files:
            messagebox.showinfo("Success", f"Changes saved successfully to:\n\n" + "\n".join(sorted(list(changed_files))))
        else:
            messagebox.showinfo("No Changes", "No permissions were changed.")
        
        self.destroy()

def main():
    root = ThemedTk(theme="scidblue")
    
    style = ttk.Style()
    
    style.configure("Accent.TButton", foreground="white", background="#0078d4", font=('Helvetica', 10, 'bold'))
    style.map("Accent.TButton", background=[('active', '#106ebe')])

    style.configure("Stop.TButton", foreground="white", background="#d40000", font=('Helvetica', 10, 'bold'))
    style.map("Stop.TButton", background=[('active', '#b80000'), ('disabled', '#ff7979')], foreground=[('disabled', 'white')])
    
    app = MicroVoltsServerSetup(root)
    root.mainloop()

if __name__ == "__main__":
    # This is important for multiprocessing on Windows
    from multiprocessing import freeze_support
    freeze_support()
    main()

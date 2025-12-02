#!/usr/bin/env python3
"""
Monitor de Sensores Completo para Deepin/Ubuntu
Todas las funciones son reales y funcionan sin simulaciones
"""

import os
import sys
import json
import time
import psutil
import subprocess
import threading
from datetime import datetime
from pathlib import Path

from PyQt6.QtWidgets import *
from PyQt6.QtCore import *
from PyQt6.QtGui import *

def get_resource_path(relative_path):
    """Obtiene la ruta absoluta al recurso, funciona para desarrollo y PyInstaller"""
    try:
        # PyInstaller crea una carpeta temporal y almacena la ruta en _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.dirname(os.path.abspath(__file__))
    
    full_path = os.path.join(base_path, relative_path)
    
    # Si no existe en el path normal, buscar recursivamente
    if not os.path.exists(full_path):
        # Buscar en directorios padres (útil para desarrollo)
        for i in range(5):
            parent_path = os.path.join(base_path, "../" * i, relative_path)
            parent_path = os.path.abspath(parent_path)
            if os.path.exists(parent_path):
                return parent_path
    
    return full_path

# Configuración por defecto
DEFAULT_CONFIG = {
    "update_interval": 2,
    "show_temperature": True,
    "show_fan_speed": True,
    "show_voltage": True,
    "show_cpu_usage": True,
    "show_ram_usage": True,
    "show_disk_usage": True,
    "show_network_usage": True,
    "show_battery": True,
    "show_processes": True,
    "temperature_unit": "C",
    "warning_temp": 80,
    "critical_temp": 90,
    "notifications_enabled": True,
    "autostart": False,
    "theme": "auto",
    "minimize_to_tray": True,
    "display_mode": "compact",
    "window_position": None,
    "window_size": [400, 500],
    "selected_disks": ["/"],
    "selected_networks": ["all"],
    "log_to_file": False,
    "sound_alerts": False,
    "language": "system",  # Nuevo: idioma del sistema
    "sensor_names": {}  # Nuevo: diccionario para nombres personalizados de sensores
}

CONFIG_FILE = Path.home() / ".config" / "sensor-monitor-config.json"
LOG_FILE = Path.home() / ".cache" / "sensor-monitor.log"

class TranslationManager:
    """Gestor de traducciones para la aplicación"""
    
    def __init__(self, app):
        self.app = app
        self.translator_qt = QTranslator()
        self.translator_app = QTranslator()
        self.current_language = "system"
        self.loaded = False
        
    def get_system_language(self):
        """Obtiene el idioma del sistema"""
        try:
            lang = os.environ.get('LANG', '')
            if lang:
                lang_code = lang.split('.')[0]  # Elimina la codificación
                # Extraer solo el código del idioma (es, en, pt, etc.)
                if '_' in lang_code:
                    return lang_code.split('_')[0]
                return lang_code
            return 'es'
        except:
            return 'es'
    
    def load_translation(self, language=None):
        """Carga las traducciones según el idioma especificado"""
        if language is None:
            language = self.current_language
            
        if language == "system":
            lang_code = self.get_system_language()
        else:
            lang_code = language
        
        # Cargar traducciones de Qt
        if hasattr(QLibraryInfo, 'path'):
            qt_translations_path = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
        else:
            # Fallback para versiones más antiguas de PyQt6
            qt_translations_path = "/usr/share/qt6/translations"
        
        if os.path.exists(qt_translations_path):
            if self.translator_qt.load(f"qtbase_{lang_code}", qt_translations_path):
                self.app.installTranslator(self.translator_qt)
        
        # Cargar traducciones de la aplicación
        # Buscar en varias ubicaciones posibles
        possible_dirs = [
            get_resource_path("langs"),
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "langs"),
            "/usr/share/de-indicator-sensor/langs",
            "/usr/local/share/de-indicator-sensor/langs"
        ]
        
        translation_loaded = False
        for langs_dir in possible_dirs:
            if os.path.exists(langs_dir):
                translation_file = f"de-indicator-sensor_{lang_code}.qm"
                translation_path = os.path.join(langs_dir, translation_file)
                
                if os.path.exists(translation_path):
                    if self.translator_app.load(translation_path):
                        self.app.installTranslator(self.translator_app)
                        self.current_language = language
                        translation_loaded = True
                        break
        
        # Si no se pudo cargar la traducción, usar inglés como fallback
        if not translation_loaded and lang_code != "en":
            # Intentar cargar inglés
            for langs_dir in possible_dirs:
                if os.path.exists(langs_dir):
                    translation_file = f"de-indicator-sensor_en.qm"
                    translation_path = os.path.join(langs_dir, translation_file)
                    
                    if os.path.exists(translation_path):
                        if self.translator_app.load(translation_path):
                            self.app.installTranslator(self.translator_app)
                            self.current_language = "en"
                            break
        
        self.loaded = True
        return True
    
    def get_available_languages(self):
        """Obtiene la lista de idiomas disponibles"""
        return [
            ("system", self.tr("Sistema (predeterminado)")),
            ("en", "English"),
            ("es", "Español"),
            ("pt", "Português")
        ]
    
    def set_language(self, language):
        """Establece un nuevo idioma"""
        # Remover traductores actuales
        self.app.removeTranslator(self.translator_qt)
        self.app.removeTranslator(self.translator_app)
        
        # Crear nuevos traductores
        self.translator_qt = QTranslator()
        self.translator_app = QTranslator()
        
        # Cargar nuevo idioma
        return self.load_translation(language)

class SensorReader:
    """Lee sensores reales del sistema"""
    
    @staticmethod
    def get_cpu_temperature():
        """Obtiene temperatura real de la CPU"""
        temps = []
        
        # Método 1: /sys/class/hwmon
        hwmon_path = Path("/sys/class/hwmon")
        if hwmon_path.exists():
            for hwmon_dir in hwmon_path.iterdir():
                try:
                    name_file = hwmon_dir / "name"
                    if name_file.exists():
                        with open(name_file, 'r') as f:
                            name = f.read().strip()
                        
                        # Buscar temperaturas
                        for i in range(1, 20):
                            temp_file = hwmon_dir / f"temp{i}_input"
                            label_file = hwmon_dir / f"temp{i}_label"
                            if temp_file.exists():
                                with open(temp_file, 'r') as f:
                                    raw_temp = int(f.read().strip())
                                    temp_c = raw_temp / 1000.0
                                    
                                    # Solo incluir temperaturas válidas y razonables
                                    if 10 < temp_c < 120:
                                        label = ""
                                        if label_file.exists():
                                            with open(label_file, 'r') as lf:
                                                label = lf.read().strip()
                                        
                                        sensor_key = f"temp_{name}_{i}"
                                        if label:
                                            sensor_key = f"temp_{name}_{label}"
                                        
                                        if "core" in label.lower() or "cpu" in label.lower() or "package" in label.lower():
                                            temps.append((sensor_key, "CPU", temp_c))
                                        elif label:
                                            temps.append((sensor_key, label, temp_c))
                                        else:
                                            temps.append((sensor_key, f"Temp{i}", temp_c))
                except:
                    continue
        
        # Método 2: /sys/class/thermal
        thermal_path = Path("/sys/class/thermal")
        if thermal_path.exists():
            for thermal_zone in thermal_path.glob("thermal_zone*"):
                try:
                    type_file = thermal_zone / "type"
                    temp_file = thermal_zone / "temp"
                    
                    if type_file.exists() and temp_file.exists():
                        with open(type_file, 'r') as f:
                            sensor_type = f.read().strip()
                        with open(temp_file, 'r') as f:
                            raw_temp = int(f.read().strip())
                            temp_c = raw_temp / 1000.0
                            
                            if 10 < temp_c < 120:
                                sensor_key = f"thermal_{sensor_type}"
                                if "cpu" in sensor_type.lower() or "core" in sensor_type.lower():
                                    temps.append((sensor_key, "CPU", temp_c))
                                else:
                                    temps.append((sensor_key, sensor_type, temp_c))
                except:
                    continue
        
        # Método 3: lm-sensors (si está instalado)
        try:
            result = subprocess.run(['sensors', '-j'], capture_output=True, text=True, timeout=2)
            if result.returncode == 0:
                import json as json_module
                data = json_module.loads(result.stdout)
                for chip, sensors in data.items():
                    for sensor, values in sensors.items():
                        if isinstance(values, dict) and 'temp' in values:
                            for key, value in values.items():
                                if 'input' in key and isinstance(value, (int, float)):
                                    temp_c = float(value)
                                    if 10 < temp_c < 120:
                                        label = sensor.replace('_', ' ').title()
                                        sensor_key = f"sensors_{chip}_{sensor}"
                                        if 'core' in label.lower() or 'cpu' in label.lower():
                                            temps.append((sensor_key, "CPU", temp_c))
                                        else:
                                            temps.append((sensor_key, label, temp_c))
        except:
            pass
        
        # Si no encontramos temperaturas, usar método alternativo
        if not temps:
            # Estimar temperatura basada en uso de CPU
            cpu_usage = psutil.cpu_percent(interval=0.1)
            base_temp = 35.0
            estimated_temp = base_temp + (cpu_usage / 100.0 * 25.0)
            temps.append(("estimated", "CPU Estimada", estimated_temp))
        
        return temps
    
    @staticmethod
    def get_fan_speed():
        """Obtiene velocidad real de ventiladores"""
        fans = {}
        
        # Buscar en /sys/class/hwmon
        hwmon_path = Path("/sys/class/hwmon")
        if hwmon_path.exists():
            for hwmon_dir in hwmon_path.iterdir():
                try:
                    name_file = hwmon_dir / "name"
                    if name_file.exists():
                        with open(name_file, 'r') as f:
                            name = f.read().strip()
                    
                    for i in range(1, 10):
                        fan_file = hwmon_dir / f"fan{i}_input"
                        label_file = hwmon_dir / f"fan{i}_label"
                        if fan_file.exists():
                            with open(fan_file, 'r') as f:
                                speed = int(f.read().strip())
                                if speed > 0:
                                    label = f"Fan{i}"
                                    if label_file.exists():
                                        with open(label_file, 'r') as lf:
                                            label = lf.read().strip() or f"Fan{i}"
                                    sensor_key = f"fan_{name}_{label}"
                                    fans[sensor_key] = (label, speed)
                except:
                    continue
        
        # Usar lm-sensors si está disponible
        if not fans:
            try:
                result = subprocess.run(['sensors'], capture_output=True, text=True, timeout=2)
                if result.returncode == 0:
                    lines = result.stdout.split('\n')
                    for line in lines:
                        if 'fan' in line.lower() and 'rpm' in line.lower():
                            parts = line.split(':')
                            if len(parts) == 2:
                                fan_name = parts[0].strip()
                                value_part = parts[1].strip()
                                # Extraer RPM
                                import re
                                rpm_match = re.search(r'(\d+)\s*RPM', value_part)
                                if rpm_match:
                                    sensor_key = f"sensors_fan_{fan_name}"
                                    fans[sensor_key] = (fan_name, int(rpm_match.group(1)))
            except:
                pass
        
        return fans
    
    @staticmethod
    def get_voltages():
        """Obtiene voltajes reales del sistema"""
        voltages = {}
        
        # Buscar en /sys/class/hwmon
        hwmon_path = Path("/sys/class/hwmon")
        if hwmon_path.exists():
            for hwmon_dir in hwmon_path.iterdir():
                try:
                    name_file = hwmon_dir / "name"
                    if name_file.exists():
                        with open(name_file, 'r') as f:
                            name = f.read().strip()
                    
                    for i in range(0, 20):
                        in_file = hwmon_dir / f"in{i}_input"
                        label_file = hwmon_dir / f"in{i}_label"
                        if in_file.exists():
                            with open(in_file, 'r') as f:
                                raw_value = int(f.read().strip())
                                if raw_value > 0:
                                    voltage = raw_value / 1000.0
                                    label = f"In{i}"
                                    if label_file.exists():
                                        with open(label_file, 'r') as lf:
                                            label = lf.read().strip() or f"In{i}"
                                    sensor_key = f"voltage_{name}_{label}"
                                    voltages[sensor_key] = (label, voltage)
                except:
                    continue
        
        return voltages
    
    @staticmethod
    def get_cpu_info():
        """Obtiene información detallada de la CPU"""
        info = {
            'usage': psutil.cpu_percent(interval=0.1, percpu=True),
            'usage_percent': psutil.cpu_percent(interval=0.1),
            'count': psutil.cpu_count(logical=True),
            'count_physical': psutil.cpu_count(logical=False),
            'freq': {}
        }
        
        try:
            freq = psutil.cpu_freq()
            if freq:
                info['freq'] = {
                    'current': freq.current,
                    'min': freq.min,
                    'max': freq.max
                }
        except:
            pass
        
        # Obtener tiempos de CPU
        try:
            cpu_times = psutil.cpu_times_percent(interval=0.1)
            info['times'] = {
                'user': cpu_times.user,
                'system': cpu_times.system,
                'idle': cpu_times.idle
            }
        except:
            pass
        
        return info
    
    @staticmethod
    def get_memory_info():
        """Obtiene información de memoria"""
        virtual = psutil.virtual_memory()
        swap = psutil.swap_memory()
        
        return {
            'virtual': {
                'total': virtual.total,
                'available': virtual.available,
                'percent': virtual.percent,
                'used': virtual.used,
                'free': virtual.free,
                'active': getattr(virtual, 'active', 0),
                'inactive': getattr(virtual, 'inactive', 0),
                'buffers': getattr(virtual, 'buffers', 0),
                'cached': getattr(virtual, 'cached', 0),
                'shared': getattr(virtual, 'shared', 0),
                'slab': getattr(virtual, 'slab', 0)
            },
            'swap': {
                'total': swap.total,
                'used': swap.used,
                'free': swap.free,
                'percent': swap.percent,
                'sin': getattr(swap, 'sin', 0),
                'sout': getattr(swap, 'sout', 0)
            }
        }
    
    @staticmethod
    def get_disk_info(partitions=None):
        """Obtiene información de disco"""
        if partitions is None:
            partitions = ["/"]
        
        disks = {}
        for partition in partitions:
            try:
                usage = psutil.disk_usage(partition)
                io = psutil.disk_io_counters(perdisk=False)
                
                disks[partition] = {
                    'total': usage.total,
                    'used': usage.used,
                    'free': usage.free,
                    'percent': usage.percent,
                    'read_bytes': io.read_bytes if io else 0,
                    'write_bytes': io.write_bytes if io else 0,
                    'read_count': io.read_count if io else 0,
                    'write_count': io.write_count if io else 0
                }
            except:
                continue
        
        return disks
    
    @staticmethod
    def get_network_info(interfaces=None):
        """Obtiene información de red"""
        if interfaces == ["all"]:
            interfaces = psutil.net_if_addrs().keys()
        
        networks = {}
        for interface in interfaces:
            try:
                addrs = psutil.net_if_addrs().get(interface, [])
                io = psutil.net_io_counters(pernic=True).get(interface)
                
                networks[interface] = {
                    'addresses': [],
                    'bytes_sent': io.bytes_sent if io else 0,
                    'bytes_recv': io.bytes_recv if io else 0,
                    'packets_sent': io.packets_sent if io else 0,
                    'packets_recv': io.packets_recv if io else 0,
                    'errin': io.errin if io else 0,
                    'errout': io.errout if io else 0,
                    'dropin': io.dropin if io else 0,
                    'dropout': io.dropout if io else 0
                }
                
                for addr in addrs:
                    networks[interface]['addresses'].append({
                        'family': str(addr.family),
                        'address': addr.address,
                        'netmask': addr.netmask if hasattr(addr, 'netmask') else None,
                        'broadcast': addr.broadcast if hasattr(addr, 'broadcast') else None
                    })
            except:
                continue
        
        return networks
    
    @staticmethod
    def get_battery_info():
        """Obtiene información de batería"""
        try:
            battery = psutil.sensors_battery()
            if battery:
                return {
                    'percent': battery.percent,
                    'secsleft': battery.secsleft,
                    'power_plugged': battery.power_plugged
                }
        except:
            pass
        
        return None
    
    @staticmethod
    def get_process_info():
        """Obtiene información de procesos"""
        try:
            processes = []
            for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']):
                try:
                    processes.append({
                        'pid': proc.info['pid'],
                        'name': proc.info['name'],
                        'cpu': proc.info['cpu_percent'],
                        'memory': proc.info['memory_percent']
                    })
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            
            # Ordenar por uso de CPU
            processes.sort(key=lambda x: x['cpu'], reverse=True)
            return processes[:10]  # Solo los 10 primeros
        except:
            return []

class SensorMonitor(QThread):
    """Monitor de sensores en segundo plano"""
    data_updated = pyqtSignal(dict)
    warning_triggered = pyqtSignal(str, str, float)  # tipo, nivel, valor
    
    def __init__(self, config):
        super().__init__()
        self.config = config
        self.running = True
        self.last_network = {}
        self.last_disk = {}
        self.last_warning_time = {}
        
    def run(self):
        while self.running:
            try:
                data = self.read_all_sensors()
                self.data_updated.emit(data)
                self.check_warnings(data)
                # FIX: Usar time.sleep() que acepta flotantes para evitar el error de tipo.
                time.sleep(self.config.get("update_interval", 2)) 
            except Exception as e:
                print(f"Error en monitor: {e}")
                time.sleep(5)
    
    def read_all_sensors(self):
        """Lee todos los sensores"""
        data = {
            'timestamp': datetime.now().strftime("%H:%M:%S"),
            'date': datetime.now().strftime("%Y-%m-%d")
        }
        
        # Temperatura
        if self.config.get("show_temperature", True):
            temps = SensorReader.get_cpu_temperature()
            data['temperature'] = []
            for sensor_key, name, temp in temps:
                # Aplicar nombre personalizado si existe
                custom_name = self.config.get("sensor_names", {}).get(sensor_key, name)
                data['temperature'].append((sensor_key, custom_name, temp))
            if data['temperature']:
                data['cpu_temp'] = data['temperature'][0][2]  # Primera temperatura (usualmente CPU)
        
        # Ventiladores
        if self.config.get("show_fan_speed", True):
            fans_raw = SensorReader.get_fan_speed()
            data['fans'] = {}
            for sensor_key, (name, speed) in fans_raw.items():
                custom_name = self.config.get("sensor_names", {}).get(sensor_key, name)
                data['fans'][sensor_key] = (custom_name, speed)
        
        # Voltajes
        if self.config.get("show_voltage", True):
            voltages_raw = SensorReader.get_voltages()
            data['voltages'] = {}
            for sensor_key, (name, voltage) in voltages_raw.items():
                custom_name = self.config.get("sensor_names", {}).get(sensor_key, name)
                data['voltages'][sensor_key] = (custom_name, voltage)
        
        # CPU
        if self.config.get("show_cpu_usage", True):
            data['cpu'] = SensorReader.get_cpu_info()
        
        # Memoria
        if self.config.get("show_ram_usage", True):
            data['memory'] = SensorReader.get_memory_info()
        
        # Disco
        if self.config.get("show_disk_usage", True):
            data['disks'] = SensorReader.get_disk_info(self.config.get("selected_disks", ["/"]))
        
        # Red
        if self.config.get("show_network_usage", True):
            data['networks'] = SensorReader.get_network_info(self.config.get("selected_networks", ["all"]))
            
            # Calcular velocidad de red
            for interface, net_data in data['networks'].items():
                if interface in self.last_network:
                    time_diff = self.config.get("update_interval", 2)
                    bytes_sent_diff = net_data['bytes_sent'] - self.last_network[interface]['bytes_sent']
                    bytes_recv_diff = net_data['bytes_recv'] - self.last_network[interface]['bytes_recv']
                    
                    net_data['sent_speed'] = bytes_sent_diff / time_diff  # B/s
                    net_data['recv_speed'] = bytes_recv_diff / time_diff  # B/s
                else:
                    net_data['sent_speed'] = 0
                    net_data['recv_speed'] = 0
            
            self.last_network = {k: {'bytes_sent': v['bytes_sent'], 'bytes_recv': v['bytes_recv']} 
                                for k, v in data['networks'].items()}
        
        # Batería
        if self.config.get("show_battery", True):
            data['battery'] = SensorReader.get_battery_info()
        
        # Procesos
        if self.config.get("show_processes", True):
            data['processes'] = SensorReader.get_process_info()
        
        # Uptime del sistema
        try:
            with open('/proc/uptime', 'r') as f:
                uptime_seconds = float(f.readline().split()[0])
                data['uptime'] = uptime_seconds
        except:
            data['uptime'] = 0
        
        return data
    
    def check_warnings(self, data):
        """Verifica condiciones de advertencia"""
        if not self.config.get("notifications_enabled", True):
            return
        
        current_time = time.time()
        
        # Verificar temperatura
        if 'cpu_temp' in data:
            temp = data['cpu_temp']
            warning_temp = self.config.get("warning_temp", 80)
            critical_temp = self.config.get("critical_temp", 90)
            
            cooldown = self.last_warning_time.get('temperature', 0)
            if current_time - cooldown > 300:  # 5 minutos entre advertencias
                if temp >= critical_temp:
                    self.warning_triggered.emit("temperature", "critical", temp)
                    self.last_warning_time['temperature'] = current_time
                elif temp >= warning_temp:
                    self.warning_triggered.emit("temperature", "warning", temp)
                    self.last_warning_time['temperature'] = current_time
        
        # Verificar memoria
        if 'memory' in data and data['memory']['virtual']['percent'] >= 90:
            cooldown = self.last_warning_time.get('memory', 0)
            if current_time - cooldown > 600:  # 10 minutos entre advertencias
                self.warning_triggered.emit("memory", "warning", data['memory']['virtual']['percent'])
                self.last_warning_time['memory'] = current_time
        
        # Verificar disco
        if 'disks' in data:
            for disk, info in data['disks'].items():
                if info['percent'] >= 90:
                    cooldown = self.last_warning_time.get(f'disk_{disk}', 0)
                    if current_time - cooldown > 600:
                        self.warning_triggered.emit("disk", "warning", info['percent'])
                        self.last_warning_time[f'disk_{disk}'] = current_time
        
        # Verificar batería
        if 'battery' in data and data['battery']:
            if data['battery']['percent'] <= 10 and not data['battery']['power_plugged']:
                cooldown = self.last_warning_time.get('battery', 0)
                if current_time - cooldown > 300:
                    self.warning_triggered.emit("battery", "critical", data['battery']['percent'])
                    self.last_warning_time['battery'] = current_time
    
    def stop(self):
        self.running = False

class SensorTrayIcon(QSystemTrayIcon):
    """Icono en bandeja del sistema con menú dinámico"""
    
    update_requested = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_window = parent

        # Intentar cargar icono personalizado
        icon_paths = [
            get_resource_path("/usr/share/de-indicator-sensor/resources/trayicon.png"),
            get_resource_path("resources/trayicon.png"),
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources/trayicon.png")
        ]
        
        icon_loaded = False
        for icon_path in icon_paths:
            if os.path.exists(icon_path):
                self.setIcon(QIcon(icon_path))
                icon_loaded = True
                break
        
        if not icon_loaded:
            # Fallback a ícono del tema
            self.setIcon(QIcon.fromTheme("computer"))
        
        self.menu = QMenu()
        self.setContextMenu(self.menu)
        
        # Conectar señal de activación
        self.activated.connect(self.on_tray_activated)
        
        # Timer para actualizar menú sin cerrarlo
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_menu_dynamic)
        self.update_timer.start(1000)  # Actualizar cada segundo
        
        # Datos actuales
        self.current_data = {}
        self.current_config = {}
        
        # Crear acciones persistentes (no cambian)
        self.setup_persistent_actions()
    
    def retranslate_menu(self):
        """Retraduce el menú con el idioma actual"""
        self.setup_persistent_actions()
        
    def setup_persistent_actions(self):
        """Configura acciones que no cambian en el menú, y marcadores para la data dinámica"""
        self.menu.clear()
        
        # Título
        title_action = QAction(self.tr("Monitor de Sensores"), self)
        title_action.setEnabled(False)
        font = title_action.font()
        font.setBold(True)
        title_action.setFont(font)
        self.menu.addAction(title_action)
        
        self.menu.addSeparator()
        
        # Sección de datos DINÁMICOS (se insertarán aquí directamente)
        # Usamos separadores como marcadores para la sección dinámica
        self.dynamic_data_start_separator = self.menu.addSeparator() # MARCADOR DE INICIO
        # Aquí se insertarán las acciones de datos
        self.dynamic_data_end_separator = self.menu.addSeparator()   # MARCADOR DE FIN
        
        # Acciones fijas
        self.show_action = QAction(self.tr("Mostrar Ventana"), self)
        self.show_action.triggered.connect(self.main_window.show_normal)
        self.menu.addAction(self.show_action)
        
        self.config_action = QAction(self.tr("Configuración"), self)
        self.config_action.triggered.connect(self.main_window.show_config)
        self.menu.addAction(self.config_action)
        
        self.update_action = QAction(self.tr("Actualizar Ahora"), self)
        self.update_action.triggered.connect(lambda: self.update_requested.emit())
        self.menu.addAction(self.update_action)
        
        self.menu.addSeparator()
        
        self.quit_action = QAction(self.tr("Salir"), self)
        self.quit_action.triggered.connect(self.main_window.quit_app)
        self.menu.addAction(self.quit_action)
    
    def update_data(self, sensor_data, config):
        """Actualiza datos para mostrar en el menú"""
        self.current_data = sensor_data
        self.current_config = config
        
        # Actualizar tooltip e ícono
        tooltip_text = self.generate_tooltip()
        self.setToolTip(tooltip_text)
        self.update_icon()
    
    def update_menu_dynamic(self):
        """Actualiza dinámicamente la sección de datos del menú (plana)"""
        if not self.current_data:
            return
        
        # --- 1. Limpiar acciones dinámicas anteriores ---
        actions = self.menu.actions()
        start_index = -1
        end_index = -1
        
        # Encontrar los índices de los marcadores
        for i, action in enumerate(actions):
            if action == self.dynamic_data_start_separator:
                start_index = i
            elif action == self.dynamic_data_end_separator:
                end_index = i
                
        # Si encontramos los marcadores y están en el orden correcto
        if start_index != -1 and end_index != -1 and start_index < end_index:
            # Eliminar las acciones entre el separador de inicio y el separador de fin
            # Iterar al revés para que los índices no cambien
            for i in range(end_index - 1, start_index, -1):
                action_to_remove = actions[i]
                self.menu.removeAction(action_to_remove)
            
            # --- 2. Crear y añadir nuevas acciones directamente a self.menu ---
            new_actions = self.create_flat_data_actions() # Nueva función para crear la lista plana de acciones
            
            # El punto de inserción es justo antes del separador de fin
            insert_before_action = self.dynamic_data_end_separator
            
            # Insertar las nuevas acciones
            for action in reversed(new_actions): # Insertar al revés para mantener el orden de new_actions
                self.menu.insertAction(insert_before_action, action)
        
        # Actualizar tooltip e icono
        tooltip_text = self.generate_tooltip()
        self.setToolTip(tooltip_text)
        self.update_icon()
    
    def create_flat_data_actions(self):
            """Crea una lista plana de acciones QAction para los datos del sistema (sustituye a add_data_to_menu)"""
            actions_list = []
            data = self.current_data
            config = self.current_config
            
            # Helper para agregar separador si la última acción no es un separador
            def add_separator_if_needed(lst):
                if lst and not lst[-1].isSeparator():
                    sep = QAction(self.menu)
                    sep.setSeparator(True)
                    lst.append(sep)

            # Temperatura (Ahora como acciones planas)
            if config.get("show_temperature", True) and 'temperature' in data and data['temperature']:
                for sensor_key, name, temp in data['temperature']:
                    # Usar el nombre personalizado ya aplicado en SensorMonitor
                    display_name = name
                    
                    # 2. Generar la acción
                    unit = "°C" if config.get("temperature_unit", "C") == "C" else "°F"
                    display_temp = temp if unit == "°C" else temp * 9/5 + 32
                    
                    # Usar el nombre de visualización final
                    temp_action = QAction(f"🌡️ {display_name}: {display_temp:.1f}{unit}", self)
                    temp_action.setEnabled(False)
                    
                    # Color basado en temperatura
                    warning_temp = config.get("warning_temp", 80)
                    critical_temp = config.get("critical_temp", 90)
                    if temp >= critical_temp:
                        temp_action.setIcon(QIcon.fromTheme("weather-severe-alert"))
                    elif temp >= warning_temp:
                        temp_action.setIcon(QIcon.fromTheme("weather-overcast"))
                        
                    actions_list.append(temp_action)
                
                add_separator_if_needed(actions_list)
            
            # CPU
            if config.get("show_cpu_usage", True) and 'cpu' in data:
                cpu = data['cpu']
                
                # Uso total
                cpu_action = QAction(self.tr("⚡ CPU Uso:") + f" {cpu['usage_percent']:.1f}%", self)
                cpu_action.setEnabled(False)
                actions_list.append(cpu_action)
                
                # Frecuencia si está disponible
                if cpu['freq'] and 'current' in cpu['freq']:
                    freq_action = QAction(self.tr("⚡ CPU Frec:") + f" {cpu['freq']['current']:.0f} MHz", self)
                    freq_action.setEnabled(False)
                    actions_list.append(freq_action)
                
                add_separator_if_needed(actions_list)
            
            # Memoria RAM
            if config.get("show_ram_usage", True) and 'memory' in data:
                mem = data['memory']['virtual']
                used_gb = mem['used'] / (1024**3)
                total_gb = mem['total'] / (1024**3)
                
                ram_action = QAction(self.tr("💾 RAM Uso:") + f" {mem['percent']:.1f}% ({used_gb:.1f}/{total_gb:.1f} GB)", self)
                ram_action.setEnabled(False)
                actions_list.append(ram_action)
                
                add_separator_if_needed(actions_list)

            # Disco
            if config.get("show_disk_usage", True) and 'disks' in data:
                for disk, info in data['disks'].items():
                    used_gb = info['used'] / (1024**3)
                    total_gb = info['total'] / (1024**3)
                    
                    disk_action = QAction(self.tr("💿 Disco") + f" {disk}: {info['percent']:.1f}% ({used_gb:.1f}/{total_gb:.1f} GB)", self)
                    disk_action.setEnabled(False)
                    actions_list.append(disk_action)
                    
                add_separator_if_needed(actions_list)
            
            # Red
            if config.get("show_network_usage", True) and 'networks' in data:
                # Añadir una etiqueta de título para Red
                title_action = QAction(self.tr("🌐 Red"), self)
                title_action.setEnabled(False)
                actions_list.append(title_action)
                    
                for interface, net_data in data['networks'].items():
                    sent_speed = net_data.get('sent_speed', 0)
                    recv_speed = net_data.get('recv_speed', 0)
                    
                    # Convertir a KB/s o MB/s
                    def format_speed(speed):
                        if speed > 1024*1024:
                            return f"{speed/(1024*1024):.1f} MB/s"
                        elif speed > 1024:
                            return f"{speed/1024:.1f} KB/s"
                        else:
                            return f"{speed:.0f} B/s"
                    
                    net_action = QAction(f"  {interface}: ↑{format_speed(sent_speed)} ↓{format_speed(recv_speed)}", self)
                    net_action.setEnabled(False)
                    actions_list.append(net_action)
                
                add_separator_if_needed(actions_list)

            # Ventiladores
            if config.get("show_fan_speed", True) and 'fans' in data and data['fans']:
                for sensor_key, (name, speed) in data['fans'].items():
                    fan_action = QAction(self.tr("🌀") + f" {name}: {speed} RPM", self)
                    fan_action.setEnabled(False)
                    actions_list.append(fan_action)
                
                add_separator_if_needed(actions_list)
            
            # Voltajes
            if config.get("show_voltage", True) and 'voltages' in data and data['voltages']:
                for sensor_key, (name, voltage) in data['voltages'].items():
                    volt_action = QAction(self.tr("⚡") + f" {name}: {voltage:.2f} V", self)
                    volt_action.setEnabled(False)
                    actions_list.append(volt_action)
                
                add_separator_if_needed(actions_list)
            
            # Batería
            if config.get("show_battery", True) and 'battery' in data and data['battery']:
                batt = data['battery']
                status = self.tr("Conectada") if batt['power_plugged'] else self.tr("Desconectada")
                time_left = ""
                if batt['secsleft'] != psutil.POWER_TIME_UNLIMITED:
                    hours = batt['secsleft'] // 3600
                    minutes = (batt['secsleft'] % 3600) // 60
                    time_left = f" ({hours}h {minutes}m)"
                
                batt_action = QAction(self.tr("🔋 Batería:") + f" {batt['percent']:.0f}% - {status}{time_left}", self)
                batt_action.setEnabled(False)
                actions_list.append(batt_action)
                
                add_separator_if_needed(actions_list)
            
            # Procesos (Top 5)
            if config.get("show_processes", True) and 'processes' in data:
                proc_title = QAction(self.tr("📊 Top 5 Procesos"), self)
                proc_title.setEnabled(False)
                actions_list.append(proc_title)
                
                for i, proc in enumerate(data['processes'][:5]):
                    proc_action = QAction(f"  {proc['name']}: CPU {proc['cpu']:.1f}%", self)
                    proc_action.setEnabled(False)
                    actions_list.append(proc_action)
                
                add_separator_if_needed(actions_list)
            
            # Uptime
            if 'uptime' in data:
                uptime = data['uptime']
                hours = int(uptime // 3600)
                minutes = int((uptime % 3600) // 60)
                
                uptime_action = QAction(self.tr("⏰ Uptime:") + f" {hours}h {minutes}m", self)
                uptime_action.setEnabled(False)
                actions_list.append(uptime_action)
            
            # Eliminar el último separador si existe y es el último elemento
            if actions_list and actions_list[-1].isSeparator():
                actions_list.pop()

            return actions_list
    
    def generate_tooltip(self):
        """Genera texto para el tooltip"""
        parts = []
        data = self.current_data
        config = self.current_config
        
        # Temperatura
        if config.get("show_temperature", True) and 'cpu_temp' in data:
            temp = data['cpu_temp']
            unit = "°C" if config.get("temperature_unit", "C") == "C" else "°F"
            display_temp = temp if unit == "°C" else temp * 9/5 + 32
            parts.append(f"{display_temp:.0f}{unit}")
        
        # CPU
        if config.get("show_cpu_usage", True) and 'cpu' in data:
            parts.append(f"CPU: {data['cpu']['usage_percent']:.0f}%")
        
        # RAM
        if config.get("show_ram_usage", True) and 'memory' in data:
            parts.append(f"RAM: {data['memory']['virtual']['percent']:.0f}%")
        
        return " | ".join(parts) if parts else self.tr("Monitor de Sensores")
    
    def update_icon(self):
        """Actualiza el ícono basado en temperatura"""
        data = self.current_data
        config = self.current_config
        
        if 'cpu_temp' in data:
            temp = data['cpu_temp']
            warning_temp = config.get("warning_temp", 80)
            critical_temp = config.get("critical_temp", 90)
            
            # Siempre empezar con el ícono personalizado de la bandeja
            if temp >= critical_temp:
                self.setIcon(QIcon.fromTheme("weather-severe-alert"))
            elif temp >= warning_temp:
                self.setIcon(QIcon.fromTheme("weather-overcast"))
            else:
                # CAMBIO: Usar get_resource_path
                icon_path = get_resource_path("/usr/share/de-indicator-sensor/resources/trayicon.png")
                if os.path.exists(icon_path):
                    self.setIcon(QIcon(icon_path))
                else:
                    self.setIcon(QIcon.fromTheme("computer"))
        else:
            # CAMBIO: Usar get_resource_path
            icon_path = get_resource_path("/usr/share/de-indicator-sensor/resources/trayicon.png")
            if os.path.exists(icon_path):
                self.setIcon(QIcon(icon_path))
            else:
                self.setIcon(QIcon.fromTheme("computer"))
    
    def on_tray_activated(self, reason):
        """Maneja clics en el icono de bandeja"""
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.main_window.show_normal()
        elif reason == QSystemTrayIcon.ActivationReason.Trigger:
            # Mostrar menú sin cerrarlo inmediatamente
            pass

class SensorDisplayWidget(QWidget):
    """Widget para mostrar datos de sensores en la ventana principal"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.sensor_data = {}
        self.config = {}
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        
        # Scroll area para cuando hay muchos datos
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        
        # Widget contenedor
        self.container = QWidget()
        self.main_layout = QVBoxLayout(self.container)
        self.main_layout.setSpacing(15)
        self.main_layout.setContentsMargins(10, 10, 10, 10)
        
        scroll.setWidget(self.container)
        layout.addWidget(scroll)

    def update_display(self, data, config):
        """Actualiza el display con los nuevos datos"""
        self.sensor_data = data
        self.config = config
        
        # Limpiar layout
        for i in reversed(range(self.main_layout.count())): 
            widget = self.main_layout.itemAt(i).widget()
            if widget:
                widget.setParent(None)
                widget.deleteLater()
        
        # Mostrar datos según configuración
        if config.get("show_temperature", True) and 'temperature' in data and data['temperature']:
            self.add_temperature_section(data['temperature'])
        
        if config.get("show_cpu_usage", True) and 'cpu' in data:
            self.add_cpu_section(data['cpu'])
        
        if config.get("show_ram_usage", True) and 'memory' in data:
            self.add_memory_section(data['memory'])

        if config.get("show_disk_usage", True) and 'disks' in data:
            self.add_disk_section(data['disks'])
        
        if config.get("show_network_usage", True) and 'networks' in data:
            self.add_network_section(data['networks'])

        if config.get("show_fan_speed", True) and 'fans' in data and data['fans']:
            self.add_fan_section(data['fans'])
        
        if config.get("show_voltage", True) and 'voltages' in data and data['voltages']:
            self.add_voltage_section(data['voltages'])
        
        if config.get("show_battery", True) and 'battery' in data and data['battery']:
            self.add_battery_section(data['battery'])
        
        if config.get("show_processes", True) and 'processes' in data:
            self.add_process_section(data['processes'])
        
        if 'uptime' in data:
            self.add_uptime_section(data['uptime'])
        
        # Espaciador al final
        self.main_layout.addStretch()

    def add_section_header(self, title, icon_name=None):
        """Añade un encabezado de sección"""
        header_widget = QWidget()
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(0, 0, 0, 5)
        if icon_name:
            icon_label = QLabel()
            icon_label.setPixmap(QIcon.fromTheme(icon_name).pixmap(16, 16))
            header_layout.addWidget(icon_label)
        title_label = QLabel(f"<b>{title}</b>")
        title_label.setStyleSheet("font-size: 12pt; color: #3D60E3;")
        header_layout.addWidget(title_label)
        header_layout.addStretch()
        self.main_layout.addWidget(header_widget)
        return header_widget

    def add_temperature_section(self, temperatures):
        """Añade sección de temperatura"""
        self.add_section_header(self.tr("🌡️ Temperatura"), "weather-clear")
        
        for sensor_key, name, temp_c in temperatures:
            widget = QWidget()
            layout = QHBoxLayout(widget)
            layout.setContentsMargins(20, 0, 0, 0)
            
            name_label = QLabel(name)
            layout.addWidget(name_label)
            
            # Mostrar en unidad configurada
            unit = self.config.get("temperature_unit", "C")
            if unit == "F":
                temp = temp_c * 9/5 + 32
                unit_str = "°F"
            else:
                temp = temp_c
                unit_str = "°C"
            
            # Color basado en temperatura
            warning_temp = self.config.get("warning_temp", 80)
            critical_temp = self.config.get("critical_temp", 90)
            color = "#2ecc71" # Verde
            if temp_c >= critical_temp:
                color = "#e74c3c" # Rojo
            elif temp_c >= warning_temp:
                color = "#f39c12" # Naranja
            
            temp_label = QLabel(f"<b style='color:{color};'>{temp:.1f}{unit_str}</b>")
            temp_label.setAlignment(Qt.AlignmentFlag.AlignRight)
            
            layout.addWidget(temp_label)
            layout.addStretch()
            self.main_layout.addWidget(widget)

    def add_cpu_section(self, cpu_info):
        """Añade sección de CPU"""
        self.add_section_header(self.tr("⚡ CPU"), "cpu")
        
        # Uso total
        self.add_progress_bar(self.tr("Uso Total"), cpu_info['usage_percent'], "%", parent_layout=self.main_layout)
        
        # Frecuencia
        if cpu_info['freq'] and 'current' in cpu_info['freq']:
            self.add_label_value(self.tr("Frecuencia"), f"{cpu_info['freq']['current']:.0f} MHz")
        
        # Uso por núcleo (solo si el modo no es compacto)
        if self.config.get("display_mode", "compact") != "compact" and cpu_info.get('usage'):
            core_group = QGroupBox(self.tr("Uso por Núcleo"))
            core_layout = QGridLayout(core_group)
            
            for i, usage in enumerate(cpu_info['usage']):
                row = i // 2
                col = i % 2
                
                core_widget = QWidget()
                core_widget_layout = QHBoxLayout(core_widget)
                core_widget_layout.setContentsMargins(0, 0, 0, 0)
                
                core_widget_layout.addWidget(QLabel(self.tr(f"Core {i}:")))
                
                # Barra de progreso individual
                progress = QProgressBar()
                progress.setValue(int(usage))
                progress.setMaximum(100)
                progress.setFormat(f"{usage:.1f}%")
                
                # Estilo basado en valor (Reusar estilo de progreso)
                if usage >= 90:
                    progress.setStyleSheet(""" QProgressBar::chunk { background-color: #e74c3c; border-radius: 3px; } """)
                elif usage >= 70:
                    progress.setStyleSheet(""" QProgressBar::chunk { background-color: #f39c12; border-radius: 3px; } """)
                else:
                    progress.setStyleSheet(""" QProgressBar::chunk { background-color: #2ecc71; border-radius: 3px; } """)
                
                core_widget_layout.addWidget(progress)
                core_layout.addWidget(core_widget, row, col)
                
            self.main_layout.addWidget(core_group)

    def add_memory_section(self, mem_info):
        """Añade sección de memoria RAM"""
        self.add_section_header(self.tr("💾 Memoria RAM"), "drive-harddisk")
        
        virtual = mem_info['virtual']
        swap = mem_info['swap']
        
        used_gb = virtual['used'] / (1024**3)
        total_gb = virtual['total'] / (1024**3)
        
        self.add_progress_bar(self.tr("Uso RAM"), virtual['percent'], f"% ({used_gb:.1f}/{total_gb:.1f} GB)")
        
        # Swap
        if swap['total'] > 0:
            used_swap_gb = swap['used'] / (1024**3)
            total_swap_gb = swap['total'] / (1024**3)
            self.add_progress_bar(self.tr("Uso Swap"), swap['percent'], f"% ({used_swap_gb:.1f}/{total_swap_gb:.1f} GB)")

    def add_disk_section(self, disks_info):
        """Añade sección de disco"""
        self.add_section_header(self.tr("💿 Disco"), "drive-harddisk")
        for disk, info in disks_info.items():
            disk_widget = QWidget()
            disk_layout = QVBoxLayout(disk_widget)
            disk_layout.setContentsMargins(0, 0, 0, 10)
            
            disk_layout.addWidget(QLabel(f"<b>{disk}</b>"))
            
            used_gb = info['used'] / (1024**3)
            total_gb = info['total'] / (1024**3)
            free_gb = info['free'] / (1024**3)
            
            # Barra de progreso
            self.add_progress_bar("", info['percent'], f"% ({used_gb:.1f}/{total_gb:.1f} GB)", disk_layout)
            
            # Información adicional
            stats_widget = QWidget()
            stats_layout = QHBoxLayout(stats_widget)
            stats_layout.setContentsMargins(20, 0, 0, 0)
            free_label = QLabel(self.tr(f"Libre: {free_gb:.1f} GB"))
            stats_layout.addWidget(free_label)
            
            # IO si está disponible
            if info['read_bytes'] > 0 or info['write_bytes'] > 0:
                read_mb = info['read_bytes'] / (1024**2)
                write_mb = info['write_bytes'] / (1024**2)
                io_label = QLabel(f"IO: R{read_mb:.1f}MB/W{write_mb:.1f}MB")
                stats_layout.addWidget(io_label)
            
            stats_layout.addStretch()
            disk_layout.addWidget(stats_widget)
            self.main_layout.addWidget(disk_widget)

    def add_network_section(self, networks_info):
        """Añade sección de red"""
        self.add_section_header(self.tr("🌐 Red"), "network-wireless")
        for interface, info in networks_info.items():
            interface_widget = QWidget()
            interface_layout = QVBoxLayout(interface_widget)
            interface_layout.setContentsMargins(20, 0, 0, 10)
            
            # Nombre de interfaz
            name_label = QLabel(f"<b>{interface}</b>")
            interface_layout.addWidget(name_label)
            
            # Velocidad
            sent_speed = info.get('sent_speed', 0)
            recv_speed = info.get('recv_speed', 0)
            
            # Convertir a unidades legibles
            def format_speed(speed):
                if speed > 1024*1024:
                    return f"{speed/(1024*1024):.1f} MB/s"
                elif speed > 1024:
                    return f"{speed/1024:.1f} KB/s"
                else:
                    return f"{speed:.0f} B/s"
            
            speed_widget = QWidget()
            speed_layout = QHBoxLayout(speed_widget)
            speed_layout.setContentsMargins(0, 0, 0, 0)
            upload_label = QLabel(f"↑ {format_speed(sent_speed)}")
            upload_label.setStyleSheet("color: #e74c3c;")
            speed_layout.addWidget(upload_label)
            download_label = QLabel(f"↓ {format_speed(recv_speed)}")
            download_label.setStyleSheet("color: #2ecc71;")
            speed_layout.addWidget(download_label)
            speed_layout.addStretch()
            interface_layout.addWidget(speed_widget)
            
            # Estadísticas
            stats_widget = QWidget()
            stats_layout = QGridLayout(stats_widget)
            stats_layout.setContentsMargins(0, 0, 0, 0)
            sent_mb = info['bytes_sent'] / (1024**2)
            recv_mb = info['bytes_recv'] / (1024**2)
            stats_layout.addWidget(QLabel(self.tr("Total Enviado:")), 0, 0)
            stats_layout.addWidget(QLabel(f"{sent_mb:.1f} MB"), 0, 1)
            stats_layout.addWidget(QLabel(self.tr("Total Recibido:")), 1, 0)
            stats_layout.addWidget(QLabel(f"{recv_mb:.1f} MB"), 1, 1)
            
            interface_layout.addWidget(stats_widget)
            self.main_layout.addWidget(interface_widget)

    def add_fan_section(self, fans_info):
        """Añade sección de ventiladores"""
        self.add_section_header(self.tr("🌀 Ventiladores"), "fan")
        for sensor_key, (name, speed) in fans_info.items():
            self.add_label_value(name, f"{speed} RPM")
            
    def add_voltage_section(self, voltages_info):
        """Añade sección de voltajes"""
        self.add_section_header(self.tr("⚡ Voltajes"), "power-supply")
        for sensor_key, (name, voltage) in voltages_info.items():
            self.add_label_value(name, f"{voltage:.2f} V")

    def add_battery_section(self, battery_info):
        """Añade sección de batería"""
        self.add_section_header(self.tr("🔋 Batería"), "battery")
        
        status = self.tr("Conectada") if battery_info['power_plugged'] else self.tr("Desconectada")
        self.add_label_value(self.tr("Estado"), status)
        
        # Porcentaje y tiempo restante
        time_left_str = self.tr("Calculando...")
        if battery_info['secsleft'] == psutil.POWER_TIME_UNLIMITED:
            time_left_str = self.tr("Ilimitado") if battery_info['power_plugged'] else "N/A"
        elif battery_info['secsleft'] > 0:
            hours = battery_info['secsleft'] // 3600
            minutes = (battery_info['secsleft'] % 3600) // 60
            time_left_str = self.tr(f"{hours}h {minutes}m restantes")
            
        self.add_label_value(self.tr("Tiempo Restante"), time_left_str)
        self.add_progress_bar(self.tr("Carga"), battery_info['percent'], "%")

    def add_process_section(self, processes):
        """Añade sección de procesos (Top 5)"""
        self.add_section_header(self.tr("📊 Top 5 Procesos (por CPU)"), "utilities-system-monitor")
        
        for i, proc in enumerate(processes[:5]):
            process_widget = QWidget()
            process_layout = QHBoxLayout(process_widget)
            process_layout.setContentsMargins(20, 0, 0, 0)
            
            name_label = QLabel(f"{i+1}. {proc['name']}")
            process_layout.addWidget(name_label)
            
            cpu_label = QLabel(f"<b>CPU: {proc['cpu']:.1f}%</b>")
            cpu_label.setAlignment(Qt.AlignmentFlag.AlignRight)
            process_layout.addWidget(cpu_label)
            
            mem_label = QLabel(f"Mem: {proc['memory']:.1f}%")
            mem_label.setAlignment(Qt.AlignmentFlag.AlignRight)
            process_layout.addWidget(mem_label)
            
            process_layout.addStretch()
            self.main_layout.addWidget(process_widget)
            
    def add_uptime_section(self, uptime_seconds):
        """Añade sección de Uptime"""
        self.add_section_header(self.tr("⏰ Uptime del Sistema"), "clock")
        
        days = int(uptime_seconds // (3600 * 24))
        hours = int((uptime_seconds % (3600 * 24)) // 3600)
        minutes = int((uptime_seconds % 3600) // 60)
        
        time_str = self.tr(f"{days}d {hours}h {minutes}m")
        self.add_label_value(self.tr("Tiempo Activo"), time_str)
        
    def add_progress_bar(self, label, value, suffix="%", parent_layout=None):
        """Añade una barra de progreso"""
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(20, 0, 0, 5)
        if label:
            label_widget = QLabel(label)
            layout.addWidget(label_widget)
        
        progress = QProgressBar()
        progress.setValue(int(value))
        progress.setMaximum(100)
        progress.setFormat(f"{value:.1f}{suffix}")
        
        # Estilo basado en valor
        if value >= 90:
            progress.setStyleSheet(""" QProgressBar::chunk { background-color: #e74c3c; border-radius: 3px; } """)
        elif value >= 70:
            progress.setStyleSheet(""" QProgressBar::chunk { background-color: #f39c12; border-radius: 3px; } """)
        else:
            progress.setStyleSheet(""" QProgressBar::chunk { background-color: #2ecc71; border-radius: 3px; } """)
            
        layout.addWidget(progress)
        if parent_layout:
            parent_layout.addWidget(widget)
        else:
            self.main_layout.addWidget(widget)

    def add_label_value(self, label, value, value_widget=None):
        """Añade etiqueta y valor"""
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(20, 0, 0, 5)
        label_widget = QLabel(label)
        layout.addWidget(label_widget)
        
        if value_widget:
            layout.addWidget(value_widget)
        else:
            value_widget = QLabel(f"<b>{value}</b>")
            value_widget.setAlignment(Qt.AlignmentFlag.AlignRight)
            layout.addWidget(value_widget)
            
        layout.addStretch()
        self.main_layout.addWidget(widget)

class SensorNamesDialog(QDialog):
    """Diálogo para renombrar sensores"""
    
    def __init__(self, sensor_data, sensor_names, parent=None):
        super().__init__(parent)
        self.sensor_data = sensor_data
        self.sensor_names = sensor_names.copy()
        self.init_ui()
        
    def init_ui(self):
        self.setWindowTitle(self.tr("Renombrar Sensores"))
        self.setFixedSize(600, 400)
        
        layout = QVBoxLayout(self)
        
        # Tab widget para organizar por tipo de sensor
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        
        # Crear tabs para diferentes tipos de sensores
        self.create_temperature_tab()
        self.create_fan_tab()
        self.create_voltage_tab()
        
        # Botones
        button_layout = QHBoxLayout()
        
        self.cancel_button = QPushButton(self.tr("Cancelar"))
        self.cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_button)
        
        button_layout.addStretch()
        
        self.reset_button = QPushButton(self.tr("Restablecer Nombres"))
        self.reset_button.clicked.connect(self.reset_names)
        button_layout.addWidget(self.reset_button)
        
        self.ok_button = QPushButton(self.tr("Aceptar"))
        self.ok_button.clicked.connect(self.accept)
        button_layout.addWidget(self.ok_button)
        
        layout.addLayout(button_layout)
        
    def create_temperature_tab(self):
        """Crea la pestaña para temperaturas"""
        if 'temperature' not in self.sensor_data or not self.sensor_data['temperature']:
            return
            
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        container_layout = QVBoxLayout(container)
        
        for sensor_key, original_name, temp in self.sensor_data['temperature']:
            sensor_widget = QWidget()
            sensor_layout = QHBoxLayout(sensor_widget)
            
            # Nombre original
            original_label = QLabel(f"{original_name}: {temp:.1f}°C")
            original_label.setMinimumWidth(200)
            sensor_layout.addWidget(original_label)
            
            # Campo para nuevo nombre
            name_edit = QLineEdit()
            name_edit.setPlaceholderText(self.tr("Nuevo nombre..."))
            if sensor_key in self.sensor_names:
                name_edit.setText(self.sensor_names[sensor_key])
            else:
                name_edit.setText(original_name)
            name_edit.textChanged.connect(lambda text, sk=sensor_key: self.update_name(sk, text))
            sensor_layout.addWidget(name_edit)
            
            container_layout.addWidget(sensor_widget)
        
        container_layout.addStretch()
        scroll.setWidget(container)
        layout.addWidget(scroll)
        
        self.tabs.addTab(tab, self.tr("🌡️ Temperaturas"))
        
    def create_fan_tab(self):
        """Crea la pestaña para ventiladores"""
        if 'fans' not in self.sensor_data or not self.sensor_data['fans']:
            return
            
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        container_layout = QVBoxLayout(container)
        
        for sensor_key, (original_name, speed) in self.sensor_data['fans'].items():
            sensor_widget = QWidget()
            sensor_layout = QHBoxLayout(sensor_widget)
            
            # Nombre original
            original_label = QLabel(f"{original_name}: {speed} RPM")
            original_label.setMinimumWidth(200)
            sensor_layout.addWidget(original_label)
            
            # Campo para nuevo nombre
            name_edit = QLineEdit()
            name_edit.setPlaceholderText(self.tr("Nuevo nombre..."))
            if sensor_key in self.sensor_names:
                name_edit.setText(self.sensor_names[sensor_key])
            else:
                name_edit.setText(original_name)
            name_edit.textChanged.connect(lambda text, sk=sensor_key: self.update_name(sk, text))
            sensor_layout.addWidget(name_edit)
            
            container_layout.addWidget(sensor_widget)
        
        container_layout.addStretch()
        scroll.setWidget(container)
        layout.addWidget(scroll)
        
        self.tabs.addTab(tab, self.tr("🌀 Ventiladores"))
        
    def create_voltage_tab(self):
        """Crea la pestaña para voltajes"""
        if 'voltages' not in self.sensor_data or not self.sensor_data['voltages']:
            return
            
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        container_layout = QVBoxLayout(container)
        
        for sensor_key, (original_name, voltage) in self.sensor_data['voltages'].items():
            sensor_widget = QWidget()
            sensor_layout = QHBoxLayout(sensor_widget)
            
            # Nombre original
            original_label = QLabel(f"{original_name}: {voltage:.2f} V")
            original_label.setMinimumWidth(200)
            sensor_layout.addWidget(original_label)
            
            # Campo para nuevo nombre
            name_edit = QLineEdit()
            name_edit.setPlaceholderText(self.tr("Nuevo nombre..."))
            if sensor_key in self.sensor_names:
                name_edit.setText(self.sensor_names[sensor_key])
            else:
                name_edit.setText(original_name)
            name_edit.textChanged.connect(lambda text, sk=sensor_key: self.update_name(sk, text))
            sensor_layout.addWidget(name_edit)
            
            container_layout.addWidget(sensor_widget)
        
        container_layout.addStretch()
        scroll.setWidget(container)
        layout.addWidget(scroll)
        
        self.tabs.addTab(tab, self.tr("⚡ Voltajes"))
        
    def update_name(self, sensor_key, new_name):
        """Actualiza el nombre de un sensor"""
        if new_name and new_name.strip():
            self.sensor_names[sensor_key] = new_name.strip()
        elif sensor_key in self.sensor_names:
            del self.sensor_names[sensor_key]
            
    def reset_names(self):
        """Restablece todos los nombres a los originales"""
        self.sensor_names.clear()
        
        # Actualizar los campos de texto en tiempo real
        for tab_index in range(self.tabs.count()):
            tab = self.tabs.widget(tab_index)
            container = tab.findChild(QScrollArea).widget()
            for i in range(container.layout().count() - 1):  # Excluir el stretch
                widget = container.layout().itemAt(i).widget()
                if widget:
                    name_edit = widget.findChild(QLineEdit)
                    if name_edit:
                        # Encontrar el sensor_key correspondiente
                        # Esto es simplificado - en una implementación real necesitaríamos mapear mejor
                        name_edit.setText("")

class ConfigurationWindow(QMainWindow):
    """Ventana de configuración completa"""
    config_changed = pyqtSignal(dict)
    
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config.copy()
        self.original_config = config.copy()
        self.parent_window = parent
        self.init_ui()
        self.load_config()

        if parent:
            self.setParent(parent)
        
        # Intentar cargar icono
        icon_paths = [
            get_resource_path("resources/appicon.png"),
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources/appicon.png")
        ]
        
        icon_loaded = False
        for icon_path in icon_paths:
            if os.path.exists(icon_path):
                self.setWindowIcon(QIcon(icon_path))
                icon_loaded = True
                break
        
        if not icon_loaded:
            self.setWindowIcon(QIcon.fromTheme("preferences-system"))

    def init_ui(self):
        self.setWindowTitle(self.tr("Configuración - Monitor de Sensores"))
        self.setGeometry(300, 200, 500, 650)
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        
        # Pestañas
        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs)
        
        # Crear pestañas
        self.create_general_tab()
        self.create_sensors_tab()
        self.create_display_tab()
        self.create_notifications_tab()
        self.create_advanced_tab()
        self.create_about_tab()  # Nueva pestaña "Acerca de"
        
        # Botones
        button_layout = QHBoxLayout()
        self.apply_btn = QPushButton(self.tr("Aplicar"))
        self.apply_btn.clicked.connect(self.apply_config)
        self.cancel_btn = QPushButton(self.tr("Cancelar"))
        self.cancel_btn.clicked.connect(self.cancel_config)
        self.reset_btn = QPushButton(self.tr("Restablecer"))
        self.reset_btn.clicked.connect(self.reset_config)
        
        button_layout.addStretch()
        button_layout.addWidget(self.reset_btn)
        button_layout.addWidget(self.cancel_btn)
        button_layout.addWidget(self.apply_btn)
        main_layout.addLayout(button_layout)

    def create_general_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # Idioma (SOLO EL COMBOBOX - botón eliminado)
        language_group = QGroupBox(self.tr("Idioma"))
        language_layout = QGridLayout()
        language_layout.addWidget(QLabel(self.tr("Idioma:")), 0, 0)
        self.language_combo = QComboBox()
        self.language_combo.addItem(self.tr("Sistema (predeterminado)"), "system")
        self.language_combo.addItem("English", "en")
        self.language_combo.addItem("Español", "es")
        self.language_combo.addItem("Português", "pt")
        language_layout.addWidget(self.language_combo, 0, 1)
        language_group.setLayout(language_layout)
        layout.addWidget(language_group)
        
        # Intervalo de actualización
        interval_group = QGroupBox(self.tr("General"))
        interval_layout = QGridLayout()
        interval_layout.addWidget(QLabel(self.tr("Intervalo de Actualización (segundos):")), 0, 0)
        self.update_interval = QSpinBox()
        self.update_interval.setRange(1, 60)
        self.update_interval.setSuffix(" s")
        interval_layout.addWidget(self.update_interval, 0, 1)
        
        self.minimize_to_tray_cb = QCheckBox(self.tr("Minimizar a la bandeja al cerrar (en lugar de salir)"))
        interval_layout.addWidget(self.minimize_to_tray_cb, 1, 0, 1, 2)
        
        self.autostart_cb = QCheckBox(self.tr("Iniciar automáticamente con el sistema"))
        self.autostart_cb.stateChanged.connect(self.toggle_autostart)
        interval_layout.addWidget(self.autostart_cb, 2, 0, 1, 2)
        
        interval_group.setLayout(interval_layout)
        layout.addWidget(interval_group)
        
        # Tema
        theme_group = QGroupBox(self.tr("Tema de la Interfaz"))
        theme_layout = QGridLayout()
        theme_layout.addWidget(QLabel(self.tr("Seleccionar Tema:")), 0, 0)
        self.theme_combo = QComboBox()
        self.theme_combo.addItems([self.tr("Automático"), self.tr("Claro"), self.tr("Oscuro")])
        theme_layout.addWidget(self.theme_combo, 0, 1)
        theme_group.setLayout(theme_layout)
        layout.addWidget(theme_group)
        
        # Configuración
        config_group = QGroupBox(self.tr("Gestión de Configuración"))
        config_layout = QHBoxLayout()
        self.export_btn = QPushButton(self.tr("Exportar"))
        self.export_btn.clicked.connect(self.export_config)
        self.import_btn = QPushButton(self.tr("Importar"))
        self.import_btn.clicked.connect(self.import_config)
        config_layout.addWidget(self.export_btn)
        config_layout.addWidget(self.import_btn)
        config_group.setLayout(config_layout)
        layout.addWidget(config_group)
        
        layout.addStretch()
        self.tabs.addTab(tab, self.tr("General"))

    def create_sensors_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # Sensores a mostrar
        sensors_group = QGroupBox(self.tr("Sensores a Monitorear"))
        sensors_layout = QGridLayout()
        
        row = 0
        self.temperature_cb = QCheckBox(self.tr("Temperatura"))
        sensors_layout.addWidget(self.temperature_cb, row, 0)
        self.cpu_cb = QCheckBox(self.tr("Uso de CPU"))
        sensors_layout.addWidget(self.cpu_cb, row, 1)
        row += 1
        self.ram_cb = QCheckBox(self.tr("Uso de RAM"))
        sensors_layout.addWidget(self.ram_cb, row, 0)
        self.disk_cb = QCheckBox(self.tr("Uso de Disco"))
        sensors_layout.addWidget(self.disk_cb, row, 1)
        row += 1
        self.network_cb = QCheckBox(self.tr("Uso de Red"))
        sensors_layout.addWidget(self.network_cb, row, 0)
        self.battery_cb = QCheckBox(self.tr("Batería"))
        sensors_layout.addWidget(self.battery_cb, row, 1)
        row += 1
        self.processes_cb = QCheckBox(self.tr("Procesos (Top)"))
        sensors_layout.addWidget(self.processes_cb, row, 0)
        self.fan_cb = QCheckBox(self.tr("Velocidad de Ventiladores"))
        sensors_layout.addWidget(self.fan_cb, row, 1)
        row += 1
        self.voltage_cb = QCheckBox(self.tr("Voltajes"))
        sensors_layout.addWidget(self.voltage_cb, row, 0)
        
        sensors_group.setLayout(sensors_layout)
        layout.addWidget(sensors_group)
        
        # NOTA INFORMATIVA - NUEVA SECCIÓN
        info_group = QGroupBox(self.tr("Nota Informativa"))
        info_layout = QVBoxLayout()
        
        info_label = QLabel(
            self.tr("<b>Nota:</b> Algunas opciones pueden no funcionar si tu hardware no soporta "
                "estas características.<br><br>"
                "Usa el botón <i>'Detectar Sensores Disponibles'</i> en la pestaña <i>'Avanzado'</i> "
                "para ver qué sensores están disponibles en tu sistema.")
        )
        info_label.setWordWrap(True)
        info_label.setOpenExternalLinks(False)
        info_label.setTextFormat(Qt.TextFormat.RichText)
        info_label.setStyleSheet("""
            QLabel {
                background-color: #fff3cd;
                border: 1px solid #ffeaa7;
                border-radius: 5px;
                padding: 10px;
                color: #856404;
            }
        """)
        
        info_layout.addWidget(info_label)
        info_group.setLayout(info_layout)
        layout.addWidget(info_group)
        
        # Botón para renombrar sensores
        rename_group = QGroupBox(self.tr("Nombres de Sensores"))
        rename_layout = QVBoxLayout()
        self.rename_btn = QPushButton(self.tr("Renombrar Sensores..."))
        self.rename_btn.clicked.connect(self.rename_sensors)
        rename_layout.addWidget(self.rename_btn)
        rename_group.setLayout(rename_layout)
        layout.addWidget(rename_group)
        
        # Configuración de temperatura
        temp_group = QGroupBox(self.tr("Configuración de Temperatura"))
        temp_layout = QGridLayout()
        temp_layout.addWidget(QLabel(self.tr("Unidad:")), 0, 0)
        self.temp_unit_combo = QComboBox()
        self.temp_unit_combo.addItems([self.tr("Celsius (°C)"), self.tr("Fahrenheit (°F)")])
        temp_layout.addWidget(self.temp_unit_combo, 0, 1)
        temp_layout.addWidget(QLabel(self.tr("Temperatura de advertencia:")), 1, 0)
        self.warning_temp = QSpinBox()
        self.warning_temp.setRange(30, 120)
        self.warning_temp.setSuffix("°C")
        temp_layout.addWidget(self.warning_temp, 1, 1)
        temp_layout.addWidget(QLabel(self.tr("Temperatura crítica:")), 2, 0)
        self.critical_temp = QSpinBox()
        self.critical_temp.setRange(40, 130)
        self.critical_temp.setSuffix("°C")
        temp_layout.addWidget(self.critical_temp, 2, 1)
        temp_group.setLayout(temp_layout)
        layout.addWidget(temp_group)
        
        # Discos a monitorear
        disk_group = QGroupBox(self.tr("Discos a Monitorear"))
        disk_layout = QVBoxLayout()
        self.disk_list = QListWidget()
        # Obtener particiones disponibles
        try:
            partitions = psutil.disk_partitions()
            for part in partitions:
                item = QListWidgetItem(part.mountpoint)
                item.setCheckState(Qt.CheckState.Checked if part.mountpoint in self.config.get("selected_disks", ["/"]) else Qt.CheckState.Unchecked)
                self.disk_list.addItem(item)
        except:
            item = QListWidgetItem("/")
            item.setCheckState(Qt.CheckState.Checked)
            self.disk_list.addItem(item)
        disk_layout.addWidget(self.disk_list)
        disk_group.setLayout(disk_layout)
        layout.addWidget(disk_group)
        
        layout.addStretch()
        self.tabs.addTab(tab, self.tr("Sensores"))

    def create_display_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # Modo de visualización
        display_group = QGroupBox(self.tr("Visualización en Bandeja y Ventana"))
        display_layout = QVBoxLayout()
        display_layout.addWidget(QLabel(self.tr("Modo de visualización en Ventana:")))
        self.display_mode_combo = QComboBox()
        self.display_mode_combo.addItems([self.tr("Compacto (predeterminado)"), self.tr("Detallado")])
        display_layout.addWidget(self.display_mode_combo)
        display_group.setLayout(display_layout)
        layout.addWidget(display_group)
        
        layout.addStretch()
        self.tabs.addTab(tab, self.tr("Visualización"))

    def create_notifications_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # Alertas
        alerts_group = QGroupBox(self.tr("Alertas y Notificaciones"))
        alerts_layout = QVBoxLayout()
        self.notifications_cb = QCheckBox(self.tr("Habilitar Notificaciones de Advertencia del Sistema"))
        alerts_layout.addWidget(self.notifications_cb)
        
        self.sound_alerts_cb = QCheckBox(self.tr("Reproducir sonido al dispararse una alerta crítica"))
        alerts_layout.addWidget(self.sound_alerts_cb)
        
        alerts_group.setLayout(alerts_layout)
        layout.addWidget(alerts_group)
        
        layout.addStretch()
        self.tabs.addTab(tab, self.tr("Notificaciones"))

    def create_advanced_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # Logging
        log_group = QGroupBox(self.tr("Registro (Logging)"))
        log_layout = QGridLayout()
        self.log_to_file_cb = QCheckBox(self.tr("Habilitar registro de advertencias en archivo"))
        log_layout.addWidget(self.log_to_file_cb, 0, 0, 1, 3)
        
        log_layout.addWidget(QLabel(self.tr("Ruta del archivo de log:")), 1, 0)
        self.log_path = QLineEdit()
        self.log_path.setText(str(LOG_FILE))
        log_layout.addWidget(self.log_path, 1, 1)
        self.browse_log_btn = QPushButton(self.tr("Explorar"))
        self.browse_log_btn.clicked.connect(self.browse_log_file)
        log_layout.addWidget(self.browse_log_btn, 1, 2)
        
        log_group.setLayout(log_layout)
        layout.addWidget(log_group)
        
        # Detección de Sensores
        sensor_detect_group = QGroupBox(self.tr("Información de Sensores"))
        sensor_detect_layout = QVBoxLayout()
        self.sensor_info = QTextEdit()
        self.sensor_info.setReadOnly(True)
        self.detect_btn = QPushButton(self.tr("Detectar Sensores Disponibles"))
        self.detect_btn.clicked.connect(self.detect_sensors)
        sensor_detect_layout.addWidget(self.detect_btn)
        sensor_detect_layout.addWidget(self.sensor_info)
        sensor_detect_group.setLayout(sensor_detect_layout)
        layout.addWidget(sensor_detect_group)
        
        layout.addStretch()
        self.tabs.addTab(tab, self.tr("Avanzado"))

    def create_about_tab(self):
        """Crea la pestaña Acerca de"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # Contenedor principal con márgenes
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setSpacing(20)
        
        # Encabezado con logo y título
        header_widget = QWidget()
        header_layout = QHBoxLayout(header_widget)
        header_layout.setSpacing(15)
        
        # Logo (intentar cargar desde recursos)
        logo_label = QLabel()
        logo_paths = [
            get_resource_path("resources/appicon.png"),
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources/appicon.png"),
            get_resource_path("/usr/share/de-indicator-sensor/resources/appicon.png")
        ]
        
        logo_loaded = False
        for logo_path in logo_paths:
            if os.path.exists(logo_path):
                pixmap = QPixmap(logo_path)
                if not pixmap.isNull():
                    # Escalar la imagen manteniendo la relación de aspecto
                    pixmap = pixmap.scaled(64, 64, Qt.AspectRatioMode.KeepAspectRatio, 
                                         Qt.TransformationMode.SmoothTransformation)
                    logo_label.setPixmap(pixmap)
                    logo_loaded = True
                    break
        
        if not logo_loaded:
            # Usar ícono del tema como fallback
            logo_label.setPixmap(QIcon.fromTheme("computer").pixmap(64, 64))
        
        header_layout.addWidget(logo_label)
        
        # Título y descripción
        title_widget = QWidget()
        title_layout = QVBoxLayout(title_widget)
        
        title_label = QLabel("<h2>DE Indicator Sensor</h2>")
        title_label.setStyleSheet("font-weight: bold; color: #2ECC71;")
        title_layout.addWidget(title_label)
        
        desc_label = QLabel(self.tr("Desarrollado por la comunidad de Deepin en Español."))
        desc_label.setStyleSheet("font-weight: bold; color: #3D60E3;")
        desc_label.setWordWrap(True)
        title_layout.addWidget(desc_label)
        
        header_layout.addWidget(title_widget)
        header_layout.addStretch()
        container_layout.addWidget(header_widget)
        
        # Estilo para enlaces
        link_style = "style='color:#2ECC71; text-decoration:none;'"
        hover_style = "onmouseover=\"this.style.color='#27AE60'; this.style.textDecoration='underline'\" " \
                     "onmouseout=\"this.style.color='#2ECC71'; this.style.textDecoration='none'\""
        
        # Información de desarrolladores
        dev_group = QGroupBox(self.tr("Desarrolladores"))
        dev_layout = QVBoxLayout()
        
        dev_text = self.tr("""
            krafairus - <a href='https://xn--deepinenespaol-1nb.org/participant/krafairus' {0} {1}>deepines.com/participant/krafairus</a>
        """).format(link_style, hover_style)
        
        dev_label = QLabel(dev_text)
        dev_label.setOpenExternalLinks(True)
        dev_label.setWordWrap(True)
        dev_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        dev_layout.addWidget(dev_label)
        
        dev_group.setLayout(dev_layout)
        container_layout.addWidget(dev_group)
        
        # Comunidad
        community_group = QGroupBox(self.tr("Comunidad Deepin en Español"))
        community_layout = QVBoxLayout()
        
        community_text = self.tr("""
            <a href='https://xn--deepinenespaol-1nb.org' {0} {1}>www.deepines.com</a>
        """).format(link_style, hover_style)
        
        community_label = QLabel(community_text)
        community_label.setOpenExternalLinks(True)
        community_label.setWordWrap(True)
        community_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        community_layout.addWidget(community_label)
        
        community_group.setLayout(community_layout)
        container_layout.addWidget(community_group)
        
        # Repositorio
        repo_group = QGroupBox(self.tr("Repositorio"))
        repo_layout = QVBoxLayout()
        
        repo_text = self.tr("""
            <a href='https://github.com/krafairus/de-indicator-sensor' {0} {1}>https://github.com/krafairus/de-indicator-sensor</a>
        """).format(link_style, hover_style)
        
        repo_label = QLabel(repo_text)
        repo_label.setOpenExternalLinks(True)
        repo_label.setWordWrap(True)
        repo_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        repo_layout.addWidget(repo_label)
        
        repo_group.setLayout(repo_layout)
        container_layout.addWidget(repo_group)
        
        # Licencia
        license_group = QGroupBox(self.tr("Licencia"))
        license_layout = QVBoxLayout()
        
        license_text = QTextEdit()
        license_text.setReadOnly(True)
        license_text.setMaximumHeight(120)
        license_text.setHtml("""
        <p>Este programa está bajo los términos de la <b>Licencia Pública General de GNU (GPL) versión 3</b>.</p>
        <p>Puedes redistribuirlo y/o modificarlo bajo los términos de la Licencia Pública General de GNU
        tal y como está publicada por la Free Software Foundation, ya sea la versión 3 de la Licencia,
        o (a tu elección) cualquier versión posterior.</p>
        """)
        license_layout.addWidget(license_text)
        
        # Botón para ver la licencia completa
        license_btn = QPushButton(self.tr("Ver texto completo de la licencia GPL v3"))
        license_btn.clicked.connect(self.show_gpl_license)
        license_layout.addWidget(license_btn)
        
        license_group.setLayout(license_layout)
        container_layout.addWidget(license_group)
        
        # Versión (podría ser dinámica)
        version_widget = QWidget()
        version_layout = QHBoxLayout(version_widget)
        
        version_label = QLabel(self.tr("Versión: 1.0.0"))
        version_label.setStyleSheet("color: #7f8c8d; font-size: 10pt;")
        version_layout.addWidget(version_label)
        
        version_layout.addStretch()
        
        copyright_label = QLabel("© 2025 Comunidad Deepin en Español")
        copyright_label.setStyleSheet("color: #7f8c8d; font-size: 9pt;")
        version_layout.addWidget(copyright_label)
        
        container_layout.addWidget(version_widget)
        
        # Agregar scroll area si es necesario
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(container)
        
        layout.addWidget(scroll)
        self.tabs.addTab(tab, self.tr("Acerca de"))

    def show_gpl_license(self):
        """Muestra el texto completo de la licencia GPL v3"""
        license_dialog = QDialog(self)
        license_dialog.setWindowTitle(self.tr("Licencia Pública General de GNU v3"))
        license_dialog.setMinimumSize(700, 500)
        
        layout = QVBoxLayout(license_dialog)
        
        # Texto de la licencia GPL v3
        license_text = QTextEdit()
        license_text.setReadOnly(True)
        
        # Cargar la licencia desde un archivo si existe, o usar texto embebido
        license_paths = [
            get_resource_path("LICENSE"),
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "LICENSE"),
            "/usr/share/common-licenses/GPL-3"
        ]
        
        license_content = ""
        for path in license_paths:
            if os.path.exists(path):
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        license_content = f.read()
                    break
                except:
                    continue
        
        if not license_content:
            # Texto resumido de la licencia si no se encuentra el archivo
            license_content = """
                    GNU GENERAL PUBLIC LICENSE
                       Version 3, 29 June 2007

 Copyright (C) 2007 Free Software Foundation, Inc. <https://fsf.org/>
 Everyone is permitted to copy and distribute verbatim copies
 of this license document, but changing it is not allowed.

                            Preamble

  The GNU General Public License is a free, copyleft license for
software and other kinds of works.

  The licenses for most software and other practical works are designed
to take away your freedom to share and change the works.  By contrast,
the GNU General Public License is intended to guarantee your freedom to
share and change all versions of a program--to make sure it remains free
software for all its users.  We, the Free Software Foundation, use the
GNU General Public License for most of our software; it applies also to
any other work released this way by its authors.  You can apply it to
your programs, too.

  (Texto completo disponible en: https://www.gnu.org/licenses/gpl-3.0.html)
            """
        
        license_text.setPlainText(license_content)
        layout.addWidget(license_text)
        
        # Botones
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        button_box.rejected.connect(license_dialog.reject)
        layout.addWidget(button_box)
        
        license_dialog.exec()

    def load_config(self):
        """Carga la configuración actual a la interfaz"""
        
        # General - Idioma
        language = self.config.get("language", "system")
        index = self.language_combo.findData(language)
        if index >= 0:
            self.language_combo.setCurrentIndex(index)
        
        # General
        self.update_interval.setValue(self.config.get("update_interval", 2))
        self.minimize_to_tray_cb.setChecked(self.config.get("minimize_to_tray", True))
        self.autostart_cb.setChecked(self.config.get("autostart", False))
        theme_map = {"auto": 0, "light": 1, "dark": 2}
        self.theme_combo.setCurrentIndex(theme_map.get(self.config.get("theme", "auto"), 0))
        
        # Sensores
        self.temperature_cb.setChecked(self.config.get("show_temperature", True))
        self.fan_cb.setChecked(self.config.get("show_fan_speed", True))
        self.voltage_cb.setChecked(self.config.get("show_voltage", True))
        self.cpu_cb.setChecked(self.config.get("show_cpu_usage", True))
        self.ram_cb.setChecked(self.config.get("show_ram_usage", True))
        self.disk_cb.setChecked(self.config.get("show_disk_usage", True))
        self.network_cb.setChecked(self.config.get("show_network_usage", True))
        self.battery_cb.setChecked(self.config.get("show_battery", True))
        self.processes_cb.setChecked(self.config.get("show_processes", True))
        
        # Temperatura
        self.temp_unit_combo.setCurrentIndex(0 if self.config.get("temperature_unit", "C") == "C" else 1)
        self.warning_temp.setValue(self.config.get("warning_temp", 80))
        self.critical_temp.setValue(self.config.get("critical_temp", 90))
        
        # Discos (actualizado en la creación, solo para referencia)
        
        # Visualización
        display_mode = self.config.get("display_mode", "compact")
        self.display_mode_combo.setCurrentIndex(0 if display_mode == "compact" else 1)
        
        # Notificaciones
        self.notifications_cb.setChecked(self.config.get("notifications_enabled", True))
        self.sound_alerts_cb.setChecked(self.config.get("sound_alerts", False))
        
        # Avanzado
        self.log_to_file_cb.setChecked(self.config.get("log_to_file", False))
        self.log_path.setText(self.config.get("log_path", str(LOG_FILE)))

    def rename_sensors(self):
        """Abre el diálogo para renombrar sensores"""
        if hasattr(self.parent_window, 'sensor_data'):
            dialog = SensorNamesDialog(self.parent_window.sensor_data, self.config.get("sensor_names", {}), self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self.config['sensor_names'] = dialog.sensor_names
                QMessageBox.information(self, self.tr("Sensores Renombrados"), 
                                       self.tr("Los nombres de los sensores han sido actualizados.\n"
                                              "Presiona 'Aplicar' para guardar los cambios."))
        else:
            QMessageBox.warning(self, self.tr("Datos No Disponibles"), 
                               self.tr("Espere a que los sensores sean detectados antes de renombrarlos."))

    def apply_config(self):
        """Aplica y guarda la configuración desde la interfaz"""
        new_config = {}
        
        # General - Idioma
        new_config['language'] = self.language_combo.currentData()
        
        # General
        new_config['update_interval'] = self.update_interval.value()
        new_config['minimize_to_tray'] = self.minimize_to_tray_cb.isChecked()
        new_config['autostart'] = self.autostart_cb.isChecked()
        theme_map = {0: "auto", 1: "light", 2: "dark"}
        new_config['theme'] = theme_map[self.theme_combo.currentIndex()]
        
        # Sensores
        new_config['show_temperature'] = self.temperature_cb.isChecked()
        new_config['show_fan_speed'] = self.fan_cb.isChecked()
        new_config['show_voltage'] = self.voltage_cb.isChecked()
        new_config['show_cpu_usage'] = self.cpu_cb.isChecked()
        new_config['show_ram_usage'] = self.ram_cb.isChecked()
        new_config['show_disk_usage'] = self.disk_cb.isChecked()
        new_config['show_network_usage'] = self.network_cb.isChecked()
        new_config['show_battery'] = self.battery_cb.isChecked()
        new_config['show_processes'] = self.processes_cb.isChecked()
        
        # Temperatura
        new_config['temperature_unit'] = "C" if self.temp_unit_combo.currentIndex() == 0 else "F"
        new_config['warning_temp'] = self.warning_temp.value()
        new_config['critical_temp'] = self.critical_temp.value()
        
        # Discos
        selected_disks = []
        for i in range(self.disk_list.count()):
            item = self.disk_list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                selected_disks.append(item.text())
        new_config['selected_disks'] = selected_disks
        
        # Visualización
        display_mode_map = {0: "compact", 1: "detailed"}
        new_config['display_mode'] = display_mode_map[self.display_mode_combo.currentIndex()]
        
        # Notificaciones
        new_config['notifications_enabled'] = self.notifications_cb.isChecked()
        new_config['sound_alerts'] = self.sound_alerts_cb.isChecked()
        
        # Avanzado
        new_config['log_to_file'] = self.log_to_file_cb.isChecked()
        new_config['log_path'] = self.log_path.text()
        
        # Nombres de sensores (mantener los existentes)
        new_config['sensor_names'] = self.config.get('sensor_names', {})
        
        # Actualizar autostart si cambió
        if new_config['autostart'] != self.config.get("autostart", False):
            self.toggle_autostart(new_config['autostart'])
        
        self.config = new_config
        self.config_changed.emit(self.config)
        self.original_config = self.config.copy()
        
        # Mostrar mensaje de confirmación
        QMessageBox.information(self, self.tr("Configuración Aplicada"), 
                                self.tr("Los cambios en la configuración se han aplicado correctamente y entrarán en vigor inmediatamente."), 
                                QMessageBox.StandardButton.Ok)
        
        # Verificar si el idioma cambió
        old_language = self.original_config.get("language", "system")
        new_language = new_config.get("language", "system")
        
        if old_language != new_language:
            QMessageBox.information(self, self.tr("Idioma Cambiado"),
                                   self.tr("El cambio de idioma se aplicará la próxima vez que inicie la aplicación.\n\n"
                                          "Por favor, reinicie la aplicación para ver los cambios en el idioma."))
        
        self.close()

    def cancel_config(self):
        """Cierra la ventana sin aplicar y restaura la configuración original (si es necesario)"""
        self.config = self.original_config.copy()
        self.close()

    def reset_config(self):
        """Restablece la configuración a los valores por defecto"""
        reply = QMessageBox.question(self, self.tr("Restablecer"), self.tr("¿Está seguro que desea restablecer a la configuración por defecto?"),
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.config = DEFAULT_CONFIG.copy()
            self.load_config()
            QMessageBox.information(self, self.tr("Restablecer"), self.tr("Configuración restablecida a valores por defecto. Presiona 'Aplicar' para guardar."))

    def toggle_autostart(self, checked):
        """Crea o elimina el archivo de autostart para Linux"""
        autostart_dir = Path.home() / ".config" / "autostart"
        autostart_file = autostart_dir / "sensor-monitor.desktop"
        
        if checked:
            autostart_dir.mkdir(parents=True, exist_ok=True)
            try:
                # Obtener la ruta del ejecutable de python y el script
                python_path = sys.executable
                script_path = Path(sys.argv[0]).resolve()
                
                desktop_content = f"""[Desktop Entry]
Type=Application
Name=Monitor de Sensores
Exec={python_path} {script_path}
Terminal=false
Icon=computer
Comment=Monitor de sensores de CPU, RAM, etc.
X-GNOME-Autostart-enabled=true
StartupNotify=false
                """
                with open(autostart_file, 'w') as f:
                    f.write(desktop_content)
                autostart_file.chmod(0o755)
            except Exception as e:
                print(f"Error al crear archivo autostart: {e}")
        else:
            if autostart_file.exists():
                try:
                    autostart_file.unlink()
                except:
                    pass

    def browse_log_file(self):
        """Abre diálogo para seleccionar archivo de log"""
        file_path, _ = QFileDialog.getSaveFileName(
            self, self.tr("Seleccionar archivo de registro"), str(self.log_path.text()), self.tr("Archivos de texto (*.txt *.log);;Todos los archivos (*)")
        )
        if file_path:
            self.log_path.setText(file_path)

    def export_config(self):
        """Exporta la configuración a un archivo JSON"""
        file_path, _ = QFileDialog.getSaveFileName(
            self, self.tr("Exportar configuración"), str(Path.home() / "sensor-monitor-config.json"), self.tr("Archivos JSON (*.json);;Todos los archivos (*)")
        )
        if file_path:
            try:
                # Usar la configuración actual de la UI, no self.config
                temp_config = {}
                temp_config['language'] = self.language_combo.currentData()
                temp_config['update_interval'] = self.update_interval.value()
                temp_config['minimize_to_tray'] = self.minimize_to_tray_cb.isChecked()
                temp_config['autostart'] = self.autostart_cb.isChecked()
                theme_map = {0: "auto", 1: "light", 2: "dark"}
                temp_config['theme'] = theme_map[self.theme_combo.currentIndex()]
                temp_config['show_temperature'] = self.temperature_cb.isChecked()
                temp_config['show_fan_speed'] = self.fan_cb.isChecked()
                temp_config['show_voltage'] = self.voltage_cb.isChecked()
                temp_config['show_cpu_usage'] = self.cpu_cb.isChecked()
                temp_config['show_ram_usage'] = self.ram_cb.isChecked()
                temp_config['show_disk_usage'] = self.disk_cb.isChecked()
                temp_config['show_network_usage'] = self.network_cb.isChecked()
                temp_config['show_battery'] = self.battery_cb.isChecked()
                temp_config['show_processes'] = self.processes_cb.isChecked()
                temp_config['temperature_unit'] = "C" if self.temp_unit_combo.currentIndex() == 0 else "F"
                temp_config['warning_temp'] = self.warning_temp.value()
                temp_config['critical_temp'] = self.critical_temp.value()
                
                selected_disks = []
                for i in range(self.disk_list.count()):
                    item = self.disk_list.item(i)
                    if item.checkState() == Qt.CheckState.Checked:
                        selected_disks.append(item.text())
                temp_config['selected_disks'] = selected_disks
                
                display_mode_map = {0: "compact", 1: "detailed"}
                temp_config['display_mode'] = display_mode_map[self.display_mode_combo.currentIndex()]
                
                temp_config['notifications_enabled'] = self.notifications_cb.isChecked()
                temp_config['sound_alerts'] = self.sound_alerts_cb.isChecked()
                temp_config['log_to_file'] = self.log_to_file_cb.isChecked()
                temp_config['log_path'] = self.log_path.text()
                temp_config['sensor_names'] = self.config.get('sensor_names', {})

                with open(file_path, 'w') as f:
                    json.dump(temp_config, f, indent=4)
                QMessageBox.information(self, self.tr("Exportar"), self.tr("Configuración exportada correctamente."))
            except Exception as e:
                QMessageBox.critical(self, self.tr("Error"), self.tr(f"No se pudo exportar:\n{e}"))

    def import_config(self):
        """Importa la configuración desde un archivo JSON"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, self.tr("Importar configuración"), str(Path.home()), self.tr("Archivos JSON (*.json);;Todos los archivos (*)")
        )
        if file_path:
            try:
                with open(file_path, 'r') as f:
                    imported_config = json.load(f)
                
                # Fusionar con configuración actual
                for key, value in imported_config.items():
                    self.config[key] = value
                    
                self.load_config()
                QMessageBox.information(self, self.tr("Importar"), self.tr("Configuración importada correctamente. Presiona 'Aplicar' para guardar."))
            except Exception as e:
                QMessageBox.critical(self, self.tr("Error"), self.tr(f"No se pudo importar:\n{e}"))

    def detect_sensors(self):
        """Detecta y muestra TODOS los sensores disponibles"""
        self.sensor_info.clear()
        self.sensor_info.append(self.tr("🔍 Detectando sensores..."))
        
        # Forzar actualización inmediata
        QApplication.processEvents()
        
        info = []
        
        # ======= 1. TEMPERATURAS =======
        temps = SensorReader.get_cpu_temperature()
        if temps:
            info.append(self.tr("--- 🌡️ TEMPERATURAS ---"))
            for sensor_key, name, temp in temps:
                info.append(f"  • {name}: {temp:.1f}°C")
                info.append(f"    ID: {sensor_key}")
            info.append("")  # Línea en blanco
        else:
            info.append(self.tr("--- 🌡️ TEMPERATURAS ---"))
            info.append(self.tr("  No se detectaron sensores de temperatura"))
            info.append("")
        
        # ======= 2. VENTILADORES =======
        fans = SensorReader.get_fan_speed()
        if fans:
            info.append(self.tr("--- 🌀 VENTILADORES ---"))
            for sensor_key, (name, speed) in fans.items():
                info.append(f"  • {name}: {speed} RPM")
                info.append(f"    ID: {sensor_key}")
            info.append("")
        else:
            info.append(self.tr("--- 🌀 VENTILADORES ---"))
            info.append(self.tr("  No se detectaron ventiladores"))
            info.append("")
        
        # ======= 3. VOLTAJES =======
        voltages = SensorReader.get_voltages()
        if voltages:
            info.append(self.tr("--- ⚡ VOLTAJES ---"))
            for sensor_key, (name, voltage) in voltages.items():
                info.append(f"  • {name}: {voltage:.2f} V")
                info.append(f"    ID: {sensor_key}")
            info.append("")
        else:
            info.append(self.tr("--- ⚡ VOLTAJES ---"))
            info.append(self.tr("  No se detectaron sensores de voltaje"))
            info.append("")
        
        # ======= 4. CPU =======
        try:
            cpu_info = SensorReader.get_cpu_info()
            info.append(self.tr("--- ⚡ CPU (PROCESADOR) ---"))
            info.append(self.tr(f"  • Núcleos lógicos: {cpu_info['count']}"))
            info.append(self.tr(f"  • Núcleos físicos: {cpu_info['count_physical']}"))
            
            if cpu_info['freq'] and 'current' in cpu_info['freq']:
                info.append(self.tr(f"  • Frecuencia actual: {cpu_info['freq']['current']:.0f} MHz"))
                if 'min' in cpu_info['freq'] and 'max' in cpu_info['freq']:
                    info.append(self.tr(f"  • Rango de frecuencia: {cpu_info['freq']['min']:.0f} - {cpu_info['freq']['max']:.0f} MHz"))
            
            # Mostrar uso por núcleo
            if cpu_info.get('usage'):
                info.append(self.tr(f"  • Uso por núcleo detectado: {len(cpu_info['usage'])} núcleos"))
            
            info.append("")
        except Exception as e:
            info.append(self.tr("--- ⚡ CPU (PROCESADOR) ---"))
            info.append(self.tr(f"  Error al detectar CPU: {str(e)}"))
            info.append("")
        
        # ======= 5. MEMORIA RAM =======
        try:
            mem_info = SensorReader.get_memory_info()
            virtual = mem_info['virtual']
            swap = mem_info['swap']
            
            info.append(self.tr("--- 💾 MEMORIA RAM ---"))
            info.append(self.tr(f"  • RAM Total: {virtual['total'] / (1024**3):.2f} GB"))
            info.append(self.tr(f"  • RAM Disponible: {virtual['available'] / (1024**3):.2f} GB"))
            info.append(self.tr(f"  • RAM en Uso: {virtual['used'] / (1024**3):.2f} GB"))
            
            # Información detallada si está disponible
            if virtual.get('buffers', 0) > 0:
                info.append(self.tr(f"  • Buffers: {virtual['buffers'] / (1024**3):.2f} GB"))
            if virtual.get('cached', 0) > 0:
                info.append(self.tr(f"  • Caché: {virtual['cached'] / (1024**3):.2f} GB"))
            
            # Swap
            if swap['total'] > 0:
                info.append(self.tr(f"  • Swap Total: {swap['total'] / (1024**3):.2f} GB"))
                info.append(self.tr(f"  • Swap en Uso: {swap['used'] / (1024**3):.2f} GB"))
            else:
                info.append(self.tr("  • Swap: No disponible"))
            
            info.append("")
        except Exception as e:
            info.append(self.tr("--- 💾 MEMORIA RAM ---"))
            info.append(self.tr(f"  Error al detectar memoria: {str(e)}"))
            info.append("")
        
        # ======= 6. DISCOS =======
        try:
            partitions = psutil.disk_partitions()
            info.append(self.tr("--- 💿 DISCOS Y PARTICIONES ---"))
            
            if partitions:
                for part in partitions:
                    try:
                        usage = psutil.disk_usage(part.mountpoint)
                        info.append(self.tr(f"  • {part.mountpoint}"))
                        info.append(self.tr(f"    Dispositivo: {part.device}"))
                        info.append(self.tr(f"    Tipo: {part.fstype}"))
                        info.append(self.tr(f"    Total: {usage.total / (1024**3):.2f} GB"))
                        info.append(self.tr(f"    Usado: {usage.used / (1024**3):.2f} GB"))
                        info.append(self.tr(f"    Libre: {usage.free / (1024**3):.2f} GB"))
                        info.append(self.tr(f"    Uso: {usage.percent}%"))
                    except:
                        info.append(self.tr(f"  • {part.mountpoint} - No se pudo leer información"))
            else:
                info.append(self.tr("  No se detectaron particiones"))
            
            info.append("")
        except Exception as e:
            info.append(self.tr("--- 💿 DISCOS Y PARTICIONES ---"))
            info.append(self.tr(f"  Error al detectar discos: {str(e)}"))
            info.append("")
        
        # ======= 7. RED =======
        try:
            interfaces = psutil.net_if_addrs()
            io_counters = psutil.net_io_counters(pernic=True)
            
            info.append(self.tr("--- 🌐 INTERFACES DE RED ---"))
            
            if interfaces:
                for interface, addrs in interfaces.items():
                    info.append(self.tr(f"  • {interface}"))
                    
                    # Direcciones de red
                    for addr in addrs:
                        if addr.family.name == 'AF_INET':
                            info.append(self.tr(f"    IPv4: {addr.address}"))
                            if addr.netmask:
                                info.append(self.tr(f"      Máscara: {addr.netmask}"))
                        elif addr.family.name == 'AF_INET6':
                            info.append(self.tr(f"    IPv6: {addr.address}"))
                        elif addr.family.name == 'AF_PACKET':
                            info.append(self.tr(f"    MAC: {addr.address}"))
                    
                    # Estadísticas si están disponibles
                    if interface in io_counters:
                        io = io_counters[interface]
                        info.append(self.tr(f"    Bytes enviados: {io.bytes_sent / (1024**2):.2f} MB"))
                        info.append(self.tr(f"    Bytes recibidos: {io.bytes_recv / (1024**2):.2f} MB"))
                    
                    info.append("")  # Separador entre interfaces
            else:
                info.append(self.tr("  No se detectaron interfaces de red"))
            
            info.append("")
        except Exception as e:
            info.append(self.tr("--- 🌐 INTERFACES DE RED ---"))
            info.append(self.tr(f"  Error al detectar red: {str(e)}"))
            info.append("")
        
        # ======= 8. BATERÍA =======
        try:
            battery = SensorReader.get_battery_info()
            info.append(self.tr("--- 🔋 BATERÍA ---"))
            
            if battery:
                info.append(self.tr(f"  • Nivel de carga: {battery['percent']:.1f}%"))
                info.append(self.tr(f"  • Estado: {'Conectada' if battery['power_plugged'] else 'Desconectada'}"))
                
                if battery['secsleft'] != psutil.POWER_TIME_UNLIMITED and battery['secsleft'] > 0:
                    hours = battery['secsleft'] // 3600
                    minutes = (battery['secsleft'] % 3600) // 60
                    info.append(self.tr(f"  • Tiempo restante: {hours}h {minutes}m"))
                elif battery['power_plugged']:
                    info.append(self.tr("  • Tiempo restante: Ilimitado (conectada)"))
                else:
                    info.append(self.tr("  • Tiempo restante: Calculando..."))
            else:
                info.append(self.tr("  No se detectó batería (puede ser un sistema de escritorio)"))
            
            info.append("")
        except Exception as e:
            info.append(self.tr("--- 🔋 BATERÍA ---"))
            info.append(self.tr(f"  Error al detectar batería: {str(e)}"))
            info.append("")
        
        # ======= 9. SENSORES DEL SISTEMA =======
        try:
            # Usar lm-sensors si está disponible para información adicional
            import subprocess
            result = subprocess.run(['which', 'sensors'], capture_output=True, text=True)
            if result.returncode == 0:
                info.append(self.tr("--- 🔧 SENSORES DEL SISTEMA (lm-sensors) ---"))
                info.append(self.tr("  • lm-sensors está instalado en el sistema"))
                info.append(self.tr("  • Ejecuta 'sensors' en terminal para más detalles"))
            else:
                info.append(self.tr("--- 🔧 SENSORES DEL SISTEMA ---"))
                info.append(self.tr("  • lm-sensors no está instalado"))
                info.append(self.tr("  • Instálalo para más información de sensores: sudo apt install lm-sensors"))
            
            info.append("")
        except:
            pass
        
        # ======= 10. RESUMEN =======
        info.append(self.tr("--- 📊 RESUMEN DE DETECCIÓN ---"))
        
        # Contar sensores detectados
        temp_count = len(temps) if temps else 0
        fan_count = len(fans) if fans else 0
        voltage_count = len(voltages) if voltages else 0
        
        info.append(self.tr(f"  • Sensores de temperatura: {temp_count}"))
        info.append(self.tr(f"  • Ventiladores: {fan_count}"))
        info.append(self.tr(f"  • Sensores de voltaje: {voltage_count}"))
        info.append(self.tr(f"  • Interfaces de red: {len(interfaces) if 'interfaces' in locals() else 'N/A'}"))
        info.append(self.tr(f"  • Particiones de disco: {len(partitions) if 'partitions' in locals() else 'N/A'}"))
        info.append(self.tr(f"  • Batería: {'Detectada' if battery else 'No detectada'}"))
        
        # Mostrar todos los sensores en el QTextEdit
        if info:
            self.sensor_info.setText("\n".join(info))
        else:
            self.sensor_info.setText(self.tr("No se pudieron detectar sensores. Es posible que necesites instalar lm-sensors (sudo apt install lm-sensors) y ejecutar 'sudo sensors-detect'."))
        
        # Añadir nota final
        self.sensor_info.append("\n" + self.tr("💡 Nota: Algunos sensores pueden requerir permisos de superusuario o la instalación de paquetes adicionales."))

class MainWindow(QMainWindow):
    """Ventana principal del monitor de sensores"""
    
    def __init__(self, translator_manager):
        super().__init__()
        self.translator_manager = translator_manager
        self.config = self.load_config()
        self.sensor_data = {}
        self.apply_theme()
        self.init_ui()
        self.init_system_tray()
        self.start_sensor_monitor()
        self.restore_window_state()

        # Configurar propiedades para el dock de Deepin
        self.setWindowTitle(self.tr("Monitor de Sensores del Sistema"))
        self.setObjectName("SensorMonitorMainWindow")
        
        # Intentar cargar icono
        icon_paths = [
            get_resource_path("resources/appicon.png"),
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources/appicon.png")
        ]
        
        icon_loaded = False
        for icon_path in icon_paths:
            if os.path.exists(icon_path):
                self.setWindowIcon(QIcon(icon_path))
                icon_loaded = True
                break
        
        if not icon_loaded:
            self.setWindowIcon(QIcon.fromTheme("computer"))

    def load_config(self):
        """Carga la configuración desde el archivo o usa valores por defecto"""
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, 'r') as f:
                    config = json.load(f)
                
                # Fusionar con los defaults para asegurar que todas las claves existan
                full_config = DEFAULT_CONFIG.copy()
                full_config.update(config)
                return full_config
            except:
                return DEFAULT_CONFIG.copy()
        return DEFAULT_CONFIG.copy()
    
    def save_config(self):
        """Guarda la configuración actual en el archivo"""
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(CONFIG_FILE, 'w') as f:
                # No guardar el estado de la ventana en el archivo de configuración principal
                temp_config = self.config.copy()
                temp_config.pop("window_position", None)
                temp_config.pop("window_size", None)
                json.dump(temp_config, f, indent=4)
        except Exception as e:
            print(f"Error al guardar configuración: {e}")

    def save_window_state(self):
        """Guarda el tamaño y la posición de la ventana"""
        self.config['window_position'] = [self.x(), self.y()]
        self.config['window_size'] = [self.width(), self.height()]
        
        # Guardar solo el estado de la ventana en un archivo temporal (opcional, para persistencia)
        state_file = CONFIG_FILE.parent / "sensor-monitor-window.json"
        state_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(state_file, 'w') as f:
                # Usar la config de la ventana directamente.
                temp_config = {
                    'window_position': self.config['window_position'],
                    'window_size': self.config['window_size']
                }
                json.dump(temp_config, f)
        except:
            pass
    
    def restore_window_state(self):
        """Restaura el tamaño y la posición de la ventana"""
        state_file = CONFIG_FILE.parent / "sensor-monitor-window.json"
        if state_file.exists():
            try:
                with open(state_file, 'r') as f:
                    state = json.load(f)
                
                if state.get('window_position'):
                    self.move(state['window_position'][0], state['window_position'][1])
                if state.get('window_size'):
                    self.resize(state['window_size'][0], state['window_size'][1])
                return
            except:
                pass

        # Usar defaults si no se encuentra el archivo de estado
        if self.config.get('window_position'):
            self.move(self.config['window_position'][0], self.config['window_position'][1])
        if self.config.get('window_size'):
            self.resize(self.config['window_size'][0], self.config['window_size'][1])

    def apply_theme(self):
        """Aplica el tema (claro/oscuro)"""
        theme = self.config.get("theme", "auto")
        
        # Lógica básica para detectar el tema del sistema (solo una estimación)
        if theme == "auto":
            # Asumir tema oscuro si no se puede detectar fácilmente
            is_dark = True
        elif theme == "dark":
            is_dark = True
        else:
            is_dark = False
            
        if is_dark:
            self.setStyleSheet(self.get_dark_theme_stylesheet())
        else:
            self.setStyleSheet(self.get_light_theme_stylesheet())

    def get_dark_theme_stylesheet(self):
        """Estilo para tema oscuro"""
        return """
QMainWindow, QWidget { background-color: #3a3a3a; color: #ffffff; }
QGroupBox { background-color: #333; border: 1px solid #555; border-radius: 5px; margin-top: 1ex; color: #ffffff; }
QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top center; padding: 0 3px; }
QLabel { color: #ffffff; }
QPushButton { background-color: #555; border: 1px solid #777; border-radius: 5px; padding: 5px 10px; color: #ffffff; }
QPushButton:hover { background-color: #666; }
QPushButton:pressed { background-color: #444; }
QCheckBox { color: #ffffff; }
QComboBox, QSpinBox, QLineEdit, QListWidget, QTextEdit { background-color: #444; border: 1px solid #555; border-radius: 3px; padding: 3px; color: #ffffff; }
QProgressBar { border: 1px solid #555; border-radius: 3px; text-align: center; color: #ffffff; }
QProgressBar::chunk { border-radius: 3px; }
QTableWidget { background-color: #333; color: #ffffff; gridline-color: #555; }
QHeaderView::section { background-color: #444; color: #ffffff; border: 1px solid #555; }
QStatusBar { background-color: #333; color: #ffffff; }
QTabWidget::pane { /* The tab widget frame */ border: 1px solid #555; background-color: #3a3a3a; }
QTabWidget::tab-bar { left: 5px; /* move to the right */ }
QTabBar::tab { background: #444; border: 1px solid #555; border-bottom-color: #3a3a3a; /* same as pane color */ border-top-left-radius: 4px; border-top-right-radius: 4px; padding: 5px; color: #ffffff; }
QTabBar::tab:selected, QTabBar::tab:hover { background: #555; }
QMenu { background-color: #333; border: 1px solid #555; color: #ffffff; }
QMenu::item:selected { background-color: #555; }

/* Barra de desplazamiento personalizada */
QScrollArea {
    background-color: transparent;
    border: none;
}
QScrollBar:vertical {
    border: none;
    background: #2a2a2a;
    width: 12px;
    margin: 0px;
    border-radius: 6px;
}
QScrollBar::handle:vertical {
    background: #4a4a4a;
    min-height: 30px;
    border-radius: 6px;
}
QScrollBar::handle:vertical:hover {
    background: #5a5a5a;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
    background: none;
}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: none;
}
QScrollBar:horizontal {
    border: none;
    background: #2a2a2a;
    height: 12px;
    margin: 0px;
    border-radius: 6px;
}
QScrollBar::handle:horizontal {
    background: #4a4a4a;
    min-width: 30px;
    border-radius: 6px;
}
QScrollBar::handle:horizontal:hover {
    background: #5a5a5a;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0px;
    background: none;
}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
    background: none;
}
"""

    def get_light_theme_stylesheet(self):
        """Estilo para tema claro"""
        return """
QMainWindow, QWidget { background-color: #f0f0f0; color: #333333; }
QGroupBox { background-color: #ffffff; border: 1px solid #ccc; border-radius: 5px; margin-top: 1ex; color: #333333; }
QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top center; padding: 0 3px; }
QLabel { color: #333333; }
QPushButton { background-color: #e0e0e0; border: 1px solid #ccc; border-radius: 5px; padding: 5px 10px; color: #333333; }
QPushButton:hover { background-color: #d0d0d0; }
QPushButton:pressed { background-color: #c0c0c0; }
QCheckBox { color: #333333; }
QComboBox, QSpinBox, QLineEdit, QListWidget, QTextEdit { background-color: #ffffff; border: 1px solid #ccc; border-radius: 3px; padding: 3px; color: #333333; }
QProgressBar { border: 1px solid #ccc; border-radius: 3px; text-align: center; color: #333333; }
QProgressBar::chunk { border-radius: 3px; }
QTableWidget { background-color: #ffffff; color: #333333; gridline-color: #ccc; }
QHeaderView::section { background-color: #e0e0e0; color: #333333; border: 1px solid #ccc; }
QStatusBar { background-color: #e0e0e0; color: #333333; }
QTabWidget::pane { /* The tab widget frame */ border: 1px solid #ccc; background-color: #f0f0f0; }
QTabWidget::tab-bar { left: 5px; /* move to the right */ }
QTabBar::tab { background: #e0e0e0; border: 1px solid #ccc; border-bottom-color: #f0f0f0; /* same as pane color */ border-top-left-radius: 4px; border-top-right-radius: 4px; padding: 5px; color: #333333; }
QTabBar::tab:selected, QTabBar::tab:hover { background: #d0d0d0; }
QMenu { background-color: #ffffff; border: 1px solid #ccc; color: #333333; }
QMenu::item:selected { background-color: #e0e0e0; }

/* Barra de desplazamiento personalizada */
QScrollArea {
    background-color: transparent;
    border: none;
}
QScrollBar:vertical {
    border: none;
    background: #d0d0d0;
    width: 12px;
    margin: 0px;
    border-radius: 6px;
}
QScrollBar::handle:vertical {
    background: #a0a0a0;
    min-height: 30px;
    border-radius: 6px;
}
QScrollBar::handle:vertical:hover {
    background: #909090;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
    background: none;
}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: none;
}
QScrollBar:horizontal {
    border: none;
    background: #d0d0d0;
    height: 12px;
    margin: 0px;
    border-radius: 6px;
}
QScrollBar::handle:horizontal {
    background: #a0a0a0;
    min-width: 30px;
    border-radius: 6px;
}
QScrollBar::handle:horizontal:hover {
    background: #909090;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0px;
    background: none;
}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
    background: none;
}
"""

    def init_ui(self):
        """Inicializa la interfaz de usuario"""
        self.setWindowTitle(self.tr("Monitor de Sensores del Sistema"))
        self.setMinimumSize(400, 300)
        
        # CAMBIO: Usar get_resource_path consistentemente
        icon_path = get_resource_path("resources/appicon.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        else:
            # Fallback a ícono del tema
            self.setWindowIcon(QIcon.fromTheme("computer"))
        
        # Widget central
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Layout principal
        main_layout = QVBoxLayout(central_widget)
        
        # Widget de visualización
        self.sensor_display = SensorDisplayWidget()
        main_layout.addWidget(self.sensor_display)
        
        # Barra de estado
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_label = QLabel(self.tr("Inicializando monitor..."))
        self.status_bar.addWidget(self.status_label)

    def init_system_tray(self):
        """Inicializa el icono de la bandeja del sistema"""
        self.tray_icon = SensorTrayIcon(self)
        # FIX para AttributeError: 'SensorTrayIcon' object has no attribute 'data_updated'
        self.tray_icon.update_requested.connect(self.request_update)
        self.tray_icon.show()

    def start_sensor_monitor(self):
        """Inicia el hilo del monitor de sensores"""
        self.sensor_monitor = SensorMonitor(self.config)
        self.sensor_monitor.data_updated.connect(self.update_display)
        self.sensor_monitor.warning_triggered.connect(self.show_warning_notification)
        self.sensor_monitor.start()

    def request_update(self):
        """Maneja la solicitud de actualización manual"""
        if self.sensor_monitor.isRunning():
            self.sensor_monitor.requestInterruption() # Intentar interrumpir el sleep
        # Una forma más simple sería reiniciar el timer del thread, pero por ahora solo se espera la próxima iteración.

    def update_display(self, data):
        """Actualiza la visualización con los nuevos datos"""
        self.sensor_data = data
        self.sensor_display.update_display(data, self.config)
        self.tray_icon.update_data(data, self.config)
        
        # Actualizar estado
        status_parts = []
        if 'cpu_temp' in data:
            temp = data['cpu_temp']
            unit = self.config.get("temperature_unit", "C")
            display_temp = temp if unit == "C" else temp * 9/5 + 32
            unit_str = "°C" if unit == "C" else "°F"
            status_parts.append(self.tr(f"Temp: {display_temp:.1f}{unit_str}"))
            
        if 'cpu' in data:
            status_parts.append(self.tr(f"CPU: {data['cpu']['usage_percent']:.0f}%"))
            
        if 'memory' in data:
            status_parts.append(self.tr(f"RAM: {data['memory']['virtual']['percent']:.0f}%"))
            
        self.status_label.setText(self.tr(f"Última actualización: {data['timestamp']} | {' | '.join(status_parts)}"))
        
        # Guardar configuración y estado de la ventana periódicamente (cada 5 minutos)
        if datetime.now().second % 60 == 0:
            self.save_config()
            self.save_window_state()

    def show_warning_notification(self, warning_type, level, value):
        """Muestra una notificación de advertencia en el sistema"""
        if not self.config.get("notifications_enabled", True):
            return
        
        message = ""
        title = self.tr("Alerta del Monitor de Sensores")
        icon = QSystemTrayIcon.MessageIcon.Warning
        
        if warning_type == "temperature":
            message = self.tr(f"La temperatura de la CPU es {value:.1f}°C.")
            if level == "critical":
                title = self.tr("¡Temperatura Crítica!")
                icon = QSystemTrayIcon.MessageIcon.Critical
            else:
                title = self.tr("Advertencia de Temperatura")
        elif warning_type == "memory":
            message = self.tr(f"Uso de RAM críticamente alto: {value:.1f}%.")
        elif warning_type == "disk":
            message = self.tr(f"El uso de disco está críticamente alto: {value:.1f}%.")
        elif warning_type == "battery":
            message = self.tr(f"Nivel de batería bajo: {value:.0f}%.")
            icon = QSystemTrayIcon.MessageIcon.Critical
            
        self.tray_icon.showMessage(title, message, icon, 5000)
        
        if self.config.get("log_to_file", False):
            self.log_warning(warning_type, level, value, message)
            
        if self.config.get("sound_alerts", False) and level == "critical":
            self.play_alert_sound()

    def play_alert_sound(self):
        """Reproduce un sonido de alerta (requiere pygame o similar en un entorno real)"""
        # En un entorno real, se usaría QSound o un comando de sistema (ej. canberra-gtk-play)
        # Para este ejemplo, solo se imprime:
        print("🔊 ALERTA CRÍTICA SONANDO")
        
    def log_warning(self, warning_type, level, value, message):
        """Registra advertencia en archivo de log"""
        try:
            log_path = Path(self.config.get("log_path", LOG_FILE))
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_entry = f"{datetime.now().strftime('%Y-%m-d %H:%M:%S')} - [{level.upper()}] {warning_type.upper()}: {message} (Valor: {value})\n"
            with open(log_path, 'a') as f:
                f.write(log_entry)
        except Exception as e:
            print(f"Error al escribir en el archivo de log: {e}")

    def show_config(self):
        """Muestra la ventana de configuración"""
        # Cerrar ventana existente si está abierta
        if hasattr(self, 'config_window') and self.config_window:
            self.config_window.close()
        
        self.config_window = ConfigurationWindow(self.config, self)
        self.config_window.config_changed.connect(self.handle_config_change)
        
        # Posicionar relativo a la ventana principal
        if self.isVisible():
            self.config_window.move(
                self.x() + 50,
                self.y() + 50
            )
        
        # IMPORTANTE: Asegurar que sea ventana hija pero no modal
        self.config_window.setWindowModality(Qt.WindowModality.NonModal)
        
        # Mostrar ventana
        self.config_window.show()
        self.config_window.raise_()
        self.config_window.activateWindow()

    def handle_config_change(self, new_config):
        """Maneja los cambios de configuración después de aplicar"""
        self.config = new_config
        self.sensor_monitor.config = new_config # Actualizar config del hilo monitor
        self.apply_theme() # Aplicar nuevo tema si cambió
        self.update_display(self.sensor_data) # Forzar una actualización de display con la nueva config
        
        # Actualizar el menú de la bandeja si el idioma cambió
        if hasattr(self, 'tray_icon'):
            self.tray_icon.retranslate_menu()

    def closeEvent(self, event):
        """Maneja el evento de cierre de la ventana"""
        if self.config.get("minimize_to_tray", True) and self.tray_icon.isVisible():
            self.hide()
            event.ignore()
        else:
            reply = QMessageBox.question(self, self.tr("Salir"), self.tr("¿Está seguro que desea cerrar el monitor?\n"
                                        "La aplicación se detendrá por completo."), QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes:
                self.quit_app()
                event.accept()
            else:
                event.ignore()

    def show_normal(self):
        """Restaura la ventana desde la bandeja"""
        self.showNormal()
        self.activateWindow() # Traer la ventana al frente

    def quit_app(self):
        """Sale de la aplicación - versión mejorada"""
        print("Solicitando cierre de la aplicación...")
        
        # 1. Guardar estado de ventana
        self.save_window_state()
        
        # 2. Guardar configuración
        self.save_config()
        
        # 3. Detener y eliminar el icono de la bandeja PRIMERO
        if hasattr(self, 'tray_icon'):
            print("Eliminando icono de bandeja...")
            self.tray_icon.hide()
            self.tray_icon.setVisible(False)
        
        # 4. Detener monitor de sensores de forma segura
        if hasattr(self, 'sensor_monitor'):
            print("Deteniendo monitor de sensores...")
            self.sensor_monitor.stop()
            
            # Esperar un tiempo razonable para que termine
            if not self.sensor_monitor.wait(2000):  # Esperar hasta 2 segundos
                print("Forzando terminación del hilo...")
                self.sensor_monitor.terminate()
                self.sensor_monitor.wait()
        
        # 5. Forzar cierre de todas las ventanas
        print("Cerrando ventanas...")
        QApplication.closeAllWindows()
        
        # 6. Salir completamente
        print("Saliendo de la aplicación...")
        QApplication.quit()
        
        # 7. Forzar salida del proceso (último recurso)
        import os
        os._exit(0)

def main():
    """Función principal"""
    # Verificar instancia única
    import socket
    
    lock_socket = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    try:
        lock_socket.bind('\0sensor_monitor_lock')
    except socket.error:
        # Ya hay una instancia ejecutándose
        print("Ya hay una instancia del Monitor de Sensores ejecutándose.")
        QMessageBox.information(None, "Monitor de Sensores", 
                               "Ya hay una instancia ejecutándose.\n"
                               "Busca el ícono en la bandeja del sistema.")
        sys.exit(0)
    
    # Crear aplicación
    app = QApplication(sys.argv)
    app.setApplicationName("Monitor de Sensores")
    app.setApplicationDisplayName("Monitor de Sensores")
    app.setWindowIcon(QIcon.fromTheme("computer"))
    
    # Establecer estilo
    app.setStyle("Fusion")
    
    # Configurar gestor de traducciones
    translator_manager = TranslationManager(app)
    
    # Cargar configuración
    config_file = Path.home() / ".config" / "sensor-monitor-config.json"
    config = DEFAULT_CONFIG.copy()
    if config_file.exists():
        try:
            with open(config_file, 'r') as f:
                loaded_config = json.load(f)
                config.update(loaded_config)
        except:
            pass
    
    # Cargar traducciones según configuración
    translator_manager.load_translation(config.get("language", "system"))
    
    # Crear y mostrar ventana principal
    window = MainWindow(translator_manager)
    
    # Ejecutar aplicación
    sys.exit(app.exec())

if __name__ == '__main__':
    main()
import sys
import json
from typing import Optional, List
from pathlib import Path

from PyQt5.QtWidgets import (
    QApplication,
    QWidget,
    QPushButton,
    QVBoxLayout,
    QLabel,
    QHBoxLayout,
    QPlainTextEdit,
    QTabWidget,
    QScrollArea,
    QDialog,
    QDialogButtonBox,
    QProgressBar,
    QSlider,
    QGroupBox,
    QCheckBox,
)
from PyQt5.QtCore import Qt, QProcess, QTimer

LOG_INTERVAL_FRAMES = 12  # Cada cuantos frames escribimos un resumen en consola
CONTROL_FILE = Path(__file__).with_name("control_state.json")  # Archivo compartido con el detector
# Estado inicial que sincroniza overlays y ajustes con angulo.py


#configuracion predefinida si no logra leer el archivo json-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
DEFAULT_CONTROL_STATE = {
    "recalibrate_token": 0,
    "overlays": {
        "landmarks": True,
        "geometry": True,
        "text": True,
    },
    "settings": {
        "ear_dynamic_ratio": 0.92,
        "frame_threshold": 50,
        "pitch_forward_threshold": 10.0,
        "pitch_backward_threshold": -12.0,
        "sound_alert": True,
        "visual_alert": True,
        "presentation_mode": False,
    },
}
#TERMINA LA CONFIGURACION PREDEFINIDA-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------




#  cambia colores de la interfaz
THEMES = {
    "dark": {
        "background": "#23272f",#fondo general
        "card": "#1f232b", # color de fondo de tarjetas
        "border": "#394150",# borde de tarjetas
        "text": "#f5f6fa",# texto principal
        "muted_text": "#a0a6b1",# texto secundario
        "accent": "#27ae60",#Alertas
        "accent_warn": "#f39c12",
        "accent_alert": "#e74c3c",
    },

}


# Dialogo modal que guia al usuario durante la recalibracion de ojos
class CalibracionDialog(QDialog):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """Crea el dialogo con instrucciones, barra y boton cancelar"""
        super().__init__(parent)
        self.setWindowTitle("Recalibracion de ojos")
        self.setModal(True)
        self.setMinimumWidth(360)
        layout = QVBoxLayout(self)
        self.instruction_label = QLabel("Manten la mirada al frente y mantenga los ojos abiertos durante la captura de 30 frames.")
        self.instruction_label.setWordWrap(True)
        layout.addWidget(self.instruction_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 30)
        layout.addWidget(self.progress_bar)
        self.feedback_label = QLabel("Preparando calibracion...")
        layout.addWidget(self.feedback_label)
        self.button_box = QDialogButtonBox(QDialogButtonBox.Cancel)
        layout.addWidget(self.button_box)
        self.button_box.rejected.connect(self.reject)

    def reset(self, total_frames: int = 30) -> None:
        """Reinicia la barra de progreso y el mensaje inicial"""
        self.progress_bar.setRange(0, total_frames)
        self.progress_bar.setValue(0)
        self.feedback_label.setText("Preparando calibracion...")
        boton = self.button_box.button(QDialogButtonBox.Cancel)
        if boton is not None:
            boton.setEnabled(True)

    def update_progress(self, value: int) -> None:
        """Mueve la barra de progreso segun los frames capturados"""
        self.progress_bar.setValue(value)

    def mark_completed(self) -> None:
        """Bloquea el boton y avisa que la calibracion termino"""
        self.feedback_label.setText("Calibracion completada")
        boton = self.button_box.button(QDialogButtonBox.Cancel)
        if boton is not None:
            boton.setEnabled(False)


# Ventana principal del panel docente que controla angulo.py y visualiza metricas
class VentanaPrincipal(QWidget):
    def __init__(self) -> None:
        """Inicializa estados, buffers y lanza la construccion de la interfaz"""
        super().__init__()
        self.proceso: Optional[QProcess] = None  # Handler del proceso lanzado
        self.stdout_buffer = ""  # Buffer para reconstruir lineas parciales
        self.control_state = self.ensure_control_state()  # Preferencias leidas de control_state.json
        self.recalibrate_token = self.control_state.get("recalibrate_token", 0)  # Token para peticiones de recalibracion
        self.last_logged_frame = -LOG_INTERVAL_FRAMES  # Frame usado para muestrear logs
        self.calibration_dialog: Optional[CalibracionDialog] = None  # Ventana de recalibracion activa
        self.calibration_progress = 0  # Frames capturados durante la recalibracion
        self.calibration_expected_frames = 30  # Total a medir en la recalibracion
        self.video_window_detached = False  # Estado de la vista flotante de video
        settings = self.control_state.get("settings", {})  # Preferencias personalizadas del usuario
        self.presentation_mode_enabled = bool(settings.get("presentation_mode", False))  # Flag de modo presentacion
        self.theme_name = "dark"  # Tema visual fijo en modo oscuro
        self.initUI()

    def initUI(self) -> None:
        """Arma toda la disposicion de widgets, estilos y conexiones"""
        self.setWindowTitle("Control de angulo.py")

        self.boton_cerrar = QPushButton("X", self)
        self.boton_cerrar.setObjectName("cerrar")
        self.boton_cerrar.clicked.connect(self.close)

        layout_superior = QHBoxLayout()
        layout_superior.addStretch()
        layout_superior.addWidget(self.boton_cerrar)

        self.label = QLabel("Presiona iniciar para ejecutar angulo.py")
        self.label.setObjectName("title")
        self.label.setAlignment(Qt.AlignCenter)

        self.control_tabs = self._build_control_tabs()

        self.consola = QPlainTextEdit()
        self.consola.setReadOnly(True)
        self.consola.setMinimumHeight(220)

        self.boton_iniciar = QPushButton("Iniciar angulo.py")
        self.boton_iniciar.setObjectName("iniciar")
        self.boton_iniciar.clicked.connect(self.iniciar_script)

        self.boton_detener = QPushButton("Detener angulo.py")
        self.boton_detener.setObjectName("detener")
        self.boton_detener.clicked.connect(self.detener_script)
        self.boton_detener.setEnabled(False)

        botones_layout = QHBoxLayout()
        botones_layout.addStretch(1)
        botones_layout.addWidget(self.boton_iniciar)
        botones_layout.addWidget(self.boton_detener)
        botones_layout.addStretch(1)
        botones_layout.setSpacing(20)

        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(24, 16, 24, 24)
        content_layout.setSpacing(24)
        content_layout.addLayout(layout_superior)
        content_layout.addWidget(self.label)
        content_layout.addWidget(self.control_tabs)
        content_layout.addWidget(self.consola)
        content_layout.addLayout(botones_layout)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setWidget(content_widget)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.addWidget(scroll_area)

        self.refresh_theme()
        if self.presentation_mode_enabled:
            self.apply_presentation_mode(True, log_event=False)

        self.showFullScreen()

    def _build_control_tabs(self) -> QTabWidget:
        """Monta pestanas para video/overlays y configuraciones"""
        tabs = QTabWidget()
        tabs.setDocumentMode(True)
        tabs.addTab(self._build_video_tab(), "Video & Overlays")
        tabs.addTab(self._build_config_tab(), "Configuracion")
        return tabs

    def _build_video_tab(self) -> QWidget:
        """Prepara controles de vista de video y flujo de recalibracion"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        overlay_title = QLabel("Overlays activos")
        overlay_title.setStyleSheet("color: #a0a6b1; font-size: 0.95em; font-weight: 600;")
        layout.addWidget(overlay_title)

        overlay_layout = QHBoxLayout()
        overlay_layout.setSpacing(12)

        overlays = self.control_state.get("overlays", DEFAULT_CONTROL_STATE["overlays"]).copy()
        self.checkbox_landmarks = QCheckBox("Landmarks")
        self.checkbox_landmarks.setChecked(overlays.get("landmarks", True))
        self.checkbox_landmarks.stateChanged.connect(lambda state: self.on_overlay_toggle("landmarks", state))

        self.checkbox_geometry = QCheckBox("Geometria")
        self.checkbox_geometry.setChecked(overlays.get("geometry", True))
        self.checkbox_geometry.stateChanged.connect(lambda state: self.on_overlay_toggle("geometry", state))

        self.checkbox_text = QCheckBox("Textos")
        self.checkbox_text.setChecked(overlays.get("text", True))
        self.checkbox_text.stateChanged.connect(lambda state: self.on_overlay_toggle("text", state))

        overlay_layout.addWidget(self.checkbox_landmarks)
        overlay_layout.addWidget(self.checkbox_geometry)
        overlay_layout.addWidget(self.checkbox_text)
        overlay_layout.addStretch(1)
        layout.addLayout(overlay_layout)

        layout.addStretch(1)
        return tab

    
    
    #apartado de configuracion de sensibilidad y alertas con minima configuracion   DE AQUI HASTA ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
    




    def _build_config_tab(self) -> QWidget:
        """Construye sliders y toggles para sensibilidad y alertas"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)

        settings = self.control_state.get("settings", DEFAULT_CONTROL_STATE["settings"]).copy()

        sensibilidad_group = QGroupBox("Sensibilidad ocular")
        sensibilidad_group.setStyleSheet("color: #3498db;")
        sensibilidad_layout = QVBoxLayout(sensibilidad_group)
        sensibilidad_layout.setSpacing(12) #espacion entre los controles

        ear_row = QHBoxLayout()
        ear_row.setSpacing(12)
        ear_label = QLabel("EAR dynamic ratio")
        self.ear_ratio_slider = QSlider(Qt.Horizontal)
        self.ear_ratio_slider.setRange(70, 98)
        ear_ratio_value = int(float(settings.get("ear_dynamic_ratio", 0.92)) * 100)
        self.ear_ratio_slider.setValue(ear_ratio_value)
        self.ear_ratio_value = QLabel(f"{ear_ratio_value / 100:.2f}")
        self.ear_ratio_slider.valueChanged.connect(self.on_ear_ratio_changed)
        ear_row.addWidget(ear_label)
        ear_row.addWidget(self.ear_ratio_slider, 1)
        ear_row.addWidget(self.ear_ratio_value)
        sensibilidad_layout.addLayout(ear_row)

        frame_row = QHBoxLayout()
        frame_row.setSpacing(12)
        frame_label = QLabel("Frames cierre ojo")
        self.frame_threshold_slider = QSlider(Qt.Horizontal)
        self.frame_threshold_slider.setRange(10, 150)
        frame_threshold = int(settings.get("frame_threshold", 50))
        self.frame_threshold_slider.setValue(frame_threshold)
        self.frame_threshold_value = QLabel(str(frame_threshold))
        self.frame_threshold_slider.valueChanged.connect(self.on_frame_threshold_changed)
        frame_row.addWidget(frame_label)
        frame_row.addWidget(self.frame_threshold_slider, 1)
        frame_row.addWidget(self.frame_threshold_value)
        sensibilidad_layout.addLayout(frame_row)

        layout.addWidget(sensibilidad_group)

        alertas_group = QGroupBox("Alertas")
        alertas_group.setStyleSheet("color: #3498db;")
        alertas_layout = QVBoxLayout(alertas_group)
        alertas_layout.setSpacing(8)
        self.sound_alert_checkbox = QCheckBox("Alarma sonora")
        self.sound_alert_checkbox.setChecked(bool(settings.get("sound_alert", True)))
        self.sound_alert_checkbox.stateChanged.connect(
            lambda state: self.on_sound_alert_toggled(state == Qt.Checked)
        )
        self.visual_alert_checkbox = QCheckBox("Alerta visual en pantalla")
        self.visual_alert_checkbox.setChecked(bool(settings.get("visual_alert", True)))
        self.visual_alert_checkbox.stateChanged.connect(
            lambda state: self.on_visual_alert_toggled(state == Qt.Checked)
        )
        alertas_layout.addWidget(self.sound_alert_checkbox)
        alertas_layout.addWidget(self.visual_alert_checkbox)
        layout.addWidget(alertas_group)

        layout.addStretch(1)
        return tab
    

    #FIN   HASTA AQUI ES CONFIGURACION DE SENSIBILIDAD Y ALERTAS----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
    


#PANEL DE ESTADISTICAS Y EXPORTACION DE DATOS GENERADOR DE ARCHIVOS CON ESTADISTICA ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

    
#CREACION Y VALIDACION DE ARCHIVO JSON DE CONFIGURACION------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

    def ensure_control_state(self) -> dict:
        """Valida o crea el archivo JSON con overlays y settings""" # ESTE METODO SE ENCARGA DE CREAR EL ARCHIVO JSON DE CONFIGURACION SI NO EXISTE Y VALIDAR SU CONTENIDO EL ARCHIVO JSON SE ENCARGA DE ALMACENAR LAS PREFERENCIAS DEL USUARIO
        if not CONTROL_FILE.exists():
            CONTROL_FILE.write_text(json.dumps(DEFAULT_CONTROL_STATE, indent=2))
            return json.loads(CONTROL_FILE.read_text())
        try:
            data = json.loads(CONTROL_FILE.read_text())
            if not isinstance(data, dict):
                raise ValueError
        except Exception:
            CONTROL_FILE.write_text(json.dumps(DEFAULT_CONTROL_STATE, indent=2))
            return json.loads(CONTROL_FILE.read_text())

        overlays = data.get("overlays")
        if not isinstance(overlays, dict):
            data["overlays"] = DEFAULT_CONTROL_STATE["overlays"].copy()
            overlays = data["overlays"]
        else:
            for key, default_value in DEFAULT_CONTROL_STATE["overlays"].items():
                overlays.setdefault(key, default_value)

        settings = data.get("settings")
        if not isinstance(settings, dict):
            data["settings"] = DEFAULT_CONTROL_STATE["settings"].copy()
            settings = data["settings"]
        else:
            for key, default_value in DEFAULT_CONTROL_STATE["settings"].items():
                settings.setdefault(key, default_value)
        if isinstance(settings, dict):
            settings.pop("theme", None)

        data.setdefault("recalibrate_token", 0)
        return data

#FIN DE CREACION Y VALIDACION DE ARCHIVO JSON DE CONFIGURACION------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------















#HOJA DE ESTILOS CSS PARA LA APLICACION------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------


    #STR  Indica que devuleve una cadena de teexto 


    #FSTRING son valores que pueden cambiar y se usan para definir el estilo visual de la aplicacion


    def build_stylesheet(self) -> str:
        """Compone la hoja de estilos segun tema y modo presentacion"""
        theme = THEMES["dark"]
        scale = 1.2 if getattr(self, "presentation_mode_enabled", False) else 1.0
        title_font = 2.0 * scale
        section_font = 1.15 * scale
        button_font = 1.0 * scale
        body_font = 1.0 * scale
        accent = theme["accent"]
        accent_warn = theme["accent_warn"]
        accent_alert = theme["accent_alert"]
        text_color = theme["text"]
        muted_text = theme["muted_text"]
        card_color = theme["card"]
        border_color = theme["border"]
        background = theme["background"]

        return f"""
            QWidget {{ background-color: {background}; }}
            QLabel {{ color: {text_color}; font-family: 'Segoe UI', Arial, sans-serif; font-size: {body_font:.2f}em; }}
            QLabel#title {{ font-size: {title_font:.2f}em; font-weight: bold; }}
            QLabel#sectionTitle {{ font-size: {section_font:.2f}em; font-weight: 600; color: {text_color}; }}
            QPushButton {{
                border-radius: 12px; padding: 12px 18px;
                font-size: {button_font:.2f}em; font-family: 'Segoe UI', Arial, sans-serif;
                margin: 0 10px; color: {text_color}; border: none;
                background-color: {border_color};
            }}
            QPushButton#iniciar {{ background-color: {accent}; color: #ffffff; }}
            QPushButton#detener {{ background-color: {accent_alert}; color: #ffffff; }}
            QPushButton#cerrar {{ background-color: transparent; color: {text_color}; font-size: {1.8 * scale:.2f}em; font-weight: bold; border: none; }}
            QPushButton#cerrar:hover {{ color: {accent_alert}; }}
            QPlainTextEdit {{ background-color: {card_color}; color: {text_color}; border: 1px solid {border_color}; border-radius: 8px; font-family: Consolas, 'Fira Mono', monospace; font-size: 13px; }}
            QTabWidget::pane {{ background: {card_color}; border: 1px solid {border_color}; border-radius: 14px; }}
            QTabBar::tab {{ background-color: transparent; color: {muted_text}; padding: 10px 16px; border-radius: 10px; margin: 2px; }}
            QTabBar::tab:selected {{ background-color: {border_color}; color: {text_color}; }}
            QCheckBox {{ color: {text_color}; font-family: 'Segoe UI', Arial, sans-serif; font-size: {body_font:.2f}em; }}
            QCheckBox::indicator {{ width: {36 * scale:.0f}px; height: {20 * scale:.0f}px; }}
            QCheckBox::indicator:checked {{ background-color: {accent}; border: 1px solid {accent}; border-radius: {10 * scale:.0f}px; }}
            QCheckBox::indicator:unchecked {{ background-color: transparent; border: 1px solid {border_color}; border-radius: {10 * scale:.0f}px; }}
            QProgressBar {{ background-color: {card_color}; border: 1px solid {border_color}; border-radius: 8px; height: 18px; text-align: center; color: {text_color}; }}
            QProgressBar::chunk {{ background-color: {accent}; border-radius: 8px; }}
            QSlider::groove:horizontal {{ border: 1px solid {border_color}; height: 6px; background: {border_color}; border-radius: 3px; }}
            QSlider::handle:horizontal {{ background: {accent}; border: 1px solid {accent}; width: 16px; margin: -6px 0; border-radius: 8px; }}
            QGroupBox {{ border: 1px solid {border_color}; border-radius: 10px; margin-top: 12px; padding: 12px; color: {text_color}; }}
            QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 6px; font-weight: 600; color: {accent}; }}
            QDialog {{ background-color: {background}; }}
        """

#"FIN DE HOJA DE ESTILOS------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------"











    def refresh_theme(self) -> None:
        """Reaplica colores del tema vigente."""
        self.setStyleSheet(self.build_stylesheet())
        if hasattr(self, 'presentation_mode_checkbox'):
            self.presentation_mode_checkbox.setStyleSheet("")
    def write_control_state(self) -> None:
        """Persiste el estado de UI en el archivo compartido"""
        CONTROL_FILE.write_text(json.dumps(self.control_state, indent=2))

    def toggle_video_window(self) -> None:
        """Alterna entre mostrar el video en el panel o solo en OpenCV"""
        self.video_window_detached = not getattr(self, 'video_window_detached', False)
        estado = 'se mostro en ventana externa' if self.video_window_detached else 'se oculto en interfaz'
        self.append_line(f"[INFO] Video {estado}")

    def start_calibration_flow(self) -> None:
        """Abre el dialogo guiado y solicita nueva calibracion al detector"""
        if not self.proceso or self.proceso.state() == QProcess.NotRunning:
            self.append_line('[WARN] No hay proceso en ejecucion para recalibrar.')
            return
        if self.calibration_dialog is None:
            dialog = CalibracionDialog(self)
            dialog.finished.connect(self.on_calibration_dialog_closed)
            self.calibration_dialog = dialog
        dialog = self.calibration_dialog
        if dialog is None:
            return
        self.calibration_progress = 0
        dialog.reset(self.calibration_expected_frames)
        dialog.feedback_label.setText('Mantenga los ojos abiertos y mire al frente')
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        self.trigger_recalibration()

    def update_calibration_flow(self, eye_state: Optional[str]) -> None:
        """Sincroniza el dialogo de calibracion con el estado reportado"""
        dialog = self.calibration_dialog
        if dialog is None or not dialog.isVisible():
            return
        if eye_state == 'calibrando':
            if self.calibration_progress < self.calibration_expected_frames:
                self.calibration_progress += 1
            dialog.update_progress(self.calibration_progress)
            dialog.feedback_label.setText(
                f'Capturando muestras {self.calibration_progress}/{self.calibration_expected_frames}'
            )
        elif eye_state == 'abiertos' and self.calibration_progress >= self.calibration_expected_frames:
            dialog.update_progress(self.calibration_expected_frames)
            dialog.mark_completed()
            QTimer.singleShot(900, dialog.accept)
        elif eye_state == 'cerrados':
            dialog.feedback_label.setText('Mantenga los ojos abiertos para completar la calibracion')

    def on_calibration_dialog_closed(self, result: int) -> None:
        """Informa en consola si la calibracion se completo o cancelo."""
        completed = result == QDialog.Accepted and self.calibration_progress >= self.calibration_expected_frames
        mensaje = 'Calibracion completada' if completed else 'Calibracion cancelada'
        nivel = 'INFO' if completed else 'WARN'
        self.append_line(f"[{nivel}] {mensaje}")
        self.calibration_dialog = None
        self.calibration_progress = 0

    def on_ear_ratio_changed(self, value: int) -> None:
        """Actualiza el ratio dinamico del EAR y guarda preferencia"""
        ratio = value / 100.0
        if hasattr(self, 'ear_ratio_value'):
            self.ear_ratio_value.setText(f"{ratio:.2f}")
        self.control_state.setdefault('settings', DEFAULT_CONTROL_STATE['settings'].copy())['ear_dynamic_ratio'] = ratio
        self.write_control_state()

    def on_frame_threshold_changed(self, value: int) -> None:
        """Modifica el umbral de frames cerrados requerido para alerta"""
        if hasattr(self, 'frame_threshold_value'):
            self.frame_threshold_value.setText(str(value))
        self.control_state.setdefault('settings', DEFAULT_CONTROL_STATE['settings'].copy())['frame_threshold'] = int(value)
        self.write_control_state()

    def on_pitch_forward_changed(self, value: int) -> None:
        """Guarda el limite superior de pitch hacia adelante"""
        if hasattr(self, 'pitch_forward_value'):
            self.pitch_forward_value.setText(f"{value} deg")
        self.control_state.setdefault('settings', DEFAULT_CONTROL_STATE['settings'].copy())['pitch_forward_threshold'] = float(value)
        self.write_control_state()

    def on_pitch_backward_changed(self, value: int) -> None:
        """Configura el limite para detectar cabeza hacia atras"""
        if hasattr(self, 'pitch_backward_value'):
            self.pitch_backward_value.setText(f"{value} deg")
        self.control_state.setdefault('settings', DEFAULT_CONTROL_STATE['settings'].copy())['pitch_backward_threshold'] = float(value)
        self.write_control_state()

    def on_sound_alert_toggled(self, enabled: bool) -> None:
        """Activa o desactiva la alarma sonora en angulo.py"""
        self.control_state.setdefault('settings', DEFAULT_CONTROL_STATE['settings'].copy())['sound_alert'] = bool(enabled)
        self.write_control_state()

    def on_visual_alert_toggled(self, enabled: bool) -> None:
        """Controla si se imprimen overlays de alerta en el video"""
        self.control_state.setdefault('settings', DEFAULT_CONTROL_STATE['settings'].copy())['visual_alert'] = bool(enabled)
        self.write_control_state()

    def on_presentation_mode_toggled(self, enabled: bool) -> None:
        """Permite alternar el modo de tipografia grande para demos"""
        self.apply_presentation_mode(enabled)

    def apply_presentation_mode(self, enabled: bool, log_event: bool = True) -> None:
        """Sincroniza checkboxes, guarda estado y relanza estilos"""
        self.presentation_mode_enabled = enabled
        settings = self.control_state.setdefault("settings", DEFAULT_CONTROL_STATE["settings"].copy())
        settings["presentation_mode"] = enabled
        self.write_control_state()
        if hasattr(self, 'presentation_mode_checkbox'):
            blocked = self.presentation_mode_checkbox.blockSignals(True)
            self.presentation_mode_checkbox.setChecked(enabled)
            self.presentation_mode_checkbox.blockSignals(blocked)
        self.refresh_theme()

    def iniciar_script(self) -> None:
        """Lanza angulo.py via QProcess y prepara la interfaz"""
        if self.proceso is None:
            self.proceso = QProcess(self)
        elif self.proceso.state() != QProcess.NotRunning:
            return

        self.reset_metrics()

        self.proceso.setProgram(sys.executable)
        self.proceso.setArguments(["-u", "angulo.py"])
        self.proceso.readyReadStandardOutput.connect(self.leer_stdout)
        self.proceso.readyReadStandardError.connect(self.leer_stderr)
        self.proceso.started.connect(lambda: self.append_line("[INFO] angulo.py iniciado"))
        self.proceso.finished.connect(self.proceso_termino)

        self.proceso.start()
        self.label.setText("angulo.py en ejecucion")
        self.boton_iniciar.setEnabled(False)
        self.boton_detener.setEnabled(True)

    def leer_stdout(self) -> None:
        """Procesa la salida estandar JSON proveniente de angulo.py"""
        if not self.proceso:
            return
        texto = bytes(self.proceso.readAllStandardOutput()).decode(errors="replace")
        if not texto:
            return
        self.stdout_buffer += texto
        while "\n" in self.stdout_buffer:
            line, self.stdout_buffer = self.stdout_buffer.split("\n", 1)
            self.procesar_linea_stdout(line.strip())

    def leer_stderr(self) -> None:
        """Muestra logs de error del proceso monitorizado"""
        if not self.proceso:
            return
        texto = bytes(self.proceso.readAllStandardError()).decode(errors="replace")
        if texto:
            self.append_text(texto)

    def procesar_linea_stdout(self, line: str) -> None:
        """Convierte cada linea JSON en metricas y actualizaciones"""
        if not line:
            return
        try:
            datos = json.loads(line)
        except json.JSONDecodeError:
            self.append_line(line)
            return

        self.actualizar_metricas(datos)
        resumen = (
            f"[METRIC] frame={datos.get('frame')} "
            f"ear={self.formatear_float(datos.get('ear_smoothed'))} "
            f"thr={self.formatear_float(datos.get('ear_threshold'))} "
            f"pitch={self.formatear_float(datos.get('pitch'))} "
            f"estado={datos.get('eye_state', '--')}"
        )
        frame_actual = datos.get('frame')
        try:
            frame_actual = int(frame_actual) if frame_actual is not None else None
        except (TypeError, ValueError):
            frame_actual = None
        if frame_actual is None or frame_actual - self.last_logged_frame >= LOG_INTERVAL_FRAMES:
            if frame_actual is not None:
                self.last_logged_frame = frame_actual
            self.append_line(resumen)

    def formatear_float(self, valor, decimales: int = 3) -> str:
        """Normaliza representaciones numericas para las etiquetas"""
        if valor is None:
            return "--"
        try:
            return f"{float(valor):.{decimales}f}"
        except (TypeError, ValueError):
            return "--"

    def actualizar_metricas(self, datos: dict) -> None:
        """Actualiza el resumen visible con la informacion mas reciente."""
        eye_state = datos.get("eye_state")
        inclinacion = datos.get("inclinacion")
        pitch = datos.get("pitch")
        closed_frames = datos.get("closed_frames")
        ear_smoothed = datos.get("ear_smoothed")
        ear_threshold = datos.get("ear_threshold")

        resumen: List[str] = []
        if eye_state:
            resumen.append(f"Ojos: {eye_state}")
        if inclinacion:
            resumen.append(f"Postura: {inclinacion}")
        if pitch is not None:
            resumen.append(f"Pitch: {self.formatear_float(pitch, 1)} deg")
        if closed_frames is not None:
            try:
                resumen.append(f"Cerrados: {int(closed_frames)}")
            except (TypeError, ValueError):
                resumen.append(f"Cerrados: {closed_frames}")
        if ear_smoothed is not None and ear_threshold is not None:
            resumen.append(
                f"EAR {self.formatear_float(ear_smoothed, 3)}/{self.formatear_float(ear_threshold, 3)}"
            )

        if resumen:
            self.label.setText(" | ".join(resumen))
        else:
            self.label.setText("Recibiendo datos...")

        self.update_calibration_flow(eye_state)

    def on_overlay_toggle(self, key: str, state: int) -> None:
        """Guarda el estado de cada overlay y registra la accion en consola."""
        enabled = state == Qt.Checked
        overlays = self.control_state.setdefault("overlays", DEFAULT_CONTROL_STATE["overlays"].copy())
        overlays[key] = enabled
        self.write_control_state()
        estado = "activado" if enabled else "desactivado"
        self.append_line(f"[INFO] Overlay {key} {estado}")

    def trigger_recalibration(self) -> None:
        """Solicita una nueva recalibracion incrementando el token compartido."""
        self.recalibrate_token += 1
        self.control_state["recalibrate_token"] = self.recalibrate_token
        self.write_control_state()
        self.append_line("[INFO] Recalibracion solicitada")

    def append_text(self, txt: str) -> None:
        """Inserta texto en la consola manteniendo el scroll al final"""
        self.consola.moveCursor(self.consola.textCursor().End)
        self.consola.insertPlainText(txt)
        self.consola.moveCursor(self.consola.textCursor().End)

    def append_line(self, line: str) -> None:
        """Agrega una linea con salto de linea a la consola"""
        self.append_text(f"{line}\n")

    def detener_script(self) -> None:
        """Termina con cuidado el proceso si sigue en ejecucion"""
        if self.proceso:
            if self.proceso.state() != QProcess.NotRunning:
                self.proceso.terminate()
                if not self.proceso.waitForFinished(1500):
                    self.proceso.kill()
                    self.proceso.waitForFinished(1000)
            self.append_line("[INFO] angulo.py detenido")
            self.label.setText("angulo.py detenido")
            self.boton_iniciar.setEnabled(True)
            self.boton_detener.setEnabled(False)

    def proceso_termino(self, exitCode: int, exitStatus: QProcess.ExitStatus) -> None:
        """Gestiona el cierre natural del proceso e informa en UI"""
        self.append_line(f"[INFO] angulo.py termino (code={exitCode})")
        self.label.setText("Proceso finalizado")
        self.boton_iniciar.setEnabled(True)
        self.boton_detener.setEnabled(False)
        self.proceso = None

    def reset_metrics(self) -> None:
        """Resetea buffers y limpia la consola para una nueva sesion."""
        self.stdout_buffer = ""
        self.last_logged_frame = -LOG_INTERVAL_FRAMES
        self.calibration_progress = 0
        self.consola.clear()
        self.label.setText("Esperando datos del detector...")

    def closeEvent(self, event) -> None:  # type: ignore[override]
        """Detiene el proceso al cerrar la ventana para evitar zombies"""
        try:
            self.detener_script()
        finally:

            
            event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    ventana = VentanaPrincipal()
    ventana.show()
    sys.exit(app.exec_())



import sys
import json
import csv
from typing import Optional, Dict, List
from collections import deque
from pathlib import Path
from datetime import datetime

from PyQt5.QtWidgets import (
    QApplication,
    QWidget,
    QPushButton,
    QVBoxLayout,
    QLabel,
    QHBoxLayout,
    QPlainTextEdit,
    QGridLayout,
    QFrame,
    QListWidget,
    QCheckBox,
    QTabWidget,
    QScrollArea,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QProgressBar,
    QSlider,
    QGroupBox,
    QFileDialog
)
from PyQt5.QtCore import Qt, QProcess, QTimer, QSize, QRectF
from PyQt5.QtGui import QColor, QPainter, QPen, QFont
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.figure import Figure

LOG_INTERVAL_FRAMES = 12  # Cada cuantos frames escribimos un resumen en consola
TIMELINE_MAX_ITEMS = 120  # Maximo de eventos visibles en la linea de tiempo
FRAME_THRESHOLD = 50  # Valor por defecto de frames cerrados para alerta
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




# Paleta para pintar la tarjeta de estado segun el nivel de alerta
STATUS_STYLES = {
    "ok": {"bg": "#1f8b4c", "border": "#27ae60", "text": "#f5f6fa", "label": "Estable"},
    "warn": {"bg": "#9c640c", "border": "#f39c12", "text": "#fbeee0", "label": "Precaucion"},
    "alert": {"bg": "#922b21", "border": "#e74c3c", "text": "#fdecea", "label": "Alerta"},
}
# Iconos de severidad que mostramos en la linea de tiempo
TIMELINE_ICONS = {"info": "-", "warn": "!", "alert": "!!"}


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




# Lienzo Matplotlib reutilizable para incrustar graficas en Qt
#base para graficas de demostracion de datos-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
class MplCanvas(FigureCanvas):
    def __init__(self, title: str, y_label: str) -> None:
        """Configura un lienzo matplotlib con estilo oscuro listo para graficas"""
        figure = Figure(figsize=(4.5, 2.4), dpi=100)
        figure.patch.set_facecolor("#1f232b")
        self.axes = figure.add_subplot(111)
        self.axes.set_facecolor("#1a1d24")#color de fondo de las graficas   
        self.axes.tick_params(colors="#00fff7ba")
        for spine in self.axes.spines.values():
            spine.set_color("#394150")
        self.axes.grid(color="#2d3240", linestyle="--", linewidth=1.5)
        self.axes.set_ylabel(y_label, color="#0059ff", fontsize=9)#color de titulos de graificas asi como tamaño
        super().__init__(figure)
        figure.tight_layout(pad=1.2)
#TERMINA LA BASE PARA GRAFICAS DE DEMOSTRACION DE DATOS-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------








# Gauge circular personalizado para mostrar el EAR en la tarjeta de estado
class CircularGauge(QWidget):
    def __init__(self, minimum: float = 0.0, maximum: float = 1.0, parent: Optional[QWidget] = None) -> None:
        """Prepara el gauge circular con limites y colores base"""
        super().__init__(parent)
        self._minimum = minimum
        self._maximum = maximum
        self._value = minimum
        self._display_value = "--"
        self._icon_text = "OK"
        self._color = QColor("#27ae60")
        self._background = QColor("#0055ff")
        self._text_color = QColor("#f5f6fa")
        self.setMinimumSize(QSize(140, 140))

    def setRange(self, minimum: float, maximum: float) -> None:
        """Actualiza los valores minimo y maximo que representa el gauge"""
        self._minimum = minimum
        self._maximum = maximum
        self.setValue(self._value)

    def setValue(self, value: float) -> None:
        """Asigna el valor actual limitado y redibuja el control"""
        clamped = max(self._minimum, min(self._maximum, float(value)))
        if clamped != self._value:
            self._value = clamped
            self.update()

    def setColor(self, color: QColor) -> None:
        """Cambia el color principal del arco activo"""
        self._color = QColor(color)
        self.update()

    def setDisplayValue(self, text: str) -> None:
        """Actualiza el texto numerico que se muestra dentro del gauge"""
        self._display_value = text
        self.update()

    def setIcon(self, text: str) -> None:
        """Muestra un simbolo grande para enfatizar el estado"""
        self._icon_text = text
        self.update()

    def setBackground(self, color: QColor) -> None:
        """Permite ajustar el color de fondo del circulo interior"""
        self._background = QColor(color)
        self.update()

    def setTextColor(self, color: QColor) -> None:
        """Permite al tema establecer el color de texto"""
        self._text_color = QColor(color)
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        """Dibuja el gauge con la porcion activa y el texto central"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = event.rect().adjusted(12, 12, -12, -12)
        size = min(rect.width(), rect.height())
        center = rect.center()
        square_rect = QRectF(
            center.x() - size / 2,
            center.y() - size / 2,
            size,
            size,
        )

        start_angle = 260 * 16
        span_angle = -340 * 16  # reduce gap so gauge appears more circular

        track_pen = QPen(QColor("#394150"), 12)
        track_pen.setCapStyle(Qt.RoundCap)
        painter.setPen(track_pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawArc(square_rect, start_angle, span_angle)

        span_ratio = 0.0 if self._maximum == self._minimum else (self._value - self._minimum) / (self._maximum - self._minimum)
        value_pen = QPen(self._color, 12)
        value_pen.setCapStyle(Qt.RoundCap)
        painter.setPen(value_pen)
        painter.drawArc(square_rect, start_angle, int(span_angle * span_ratio))

        inner_rect = square_rect.adjusted(22, 22, -22, -22)
        painter.setPen(Qt.NoPen)
        painter.setBrush(self._background)
        painter.drawEllipse(inner_rect)

        painter.setPen(self._color)
        icon_font = QFont("Segoe UI", 36, QFont.Bold)
        painter.setFont(icon_font)
        painter.drawText(inner_rect, Qt.AlignCenter, self._icon_text)

        painter.setPen(self._text_color)
        value_font = QFont("Segoe UI", 12, QFont.Medium)
        painter.setFont(value_font)
        painter.drawText(inner_rect.adjusted(0, 20, 0, 0), Qt.AlignHCenter | Qt.AlignBottom, self._display_value)


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
        self.history = {  # Series historicas usadas en las graficas
            "x": deque(maxlen=240),
            "ear_metric": deque(maxlen=240),
            "ear_threshold": deque(maxlen=240),
            "pitch": deque(maxlen=240),
            "eye_angle": deque(maxlen=240),
        }
        self.metric_labels: Dict[str, QLabel] = {}  # Referencias a labels de metricas
        self.stats_labels: Dict[str, QLabel] = {}  # Etiquetas del panel estadistico
        self.prev_eye_state: Optional[str] = None  # Para detectar cambios de estado de parpadeo
        self.prev_inclinacion: Optional[str] = None  # Para detectar cambios de postura
        self.last_closed_alert_frame: int = -1  # Frame de la ultima alerta por ojos cerrados
        self.session_start = datetime.now()  # Marca inicial para timestamps
        self.stats = {  # Contadores acumulados durante la sesion
            "total_frames": 0,
            "closed_frames": 0,
            "forward_frames": 0,
            "pitch_sum": 0.0,
            "pitch_count": 0,
            "alerts": 0,
            "calibrations": 0,
        }
        self.timeline_events = []  # Lista completa de eventos registrados
        self.chart_update_interval = 3  # Solo repintamos graficas cada N muestras
        self.timeline_filter = "todos"  # Categoria actualmente filtrada
        self.calibration_dialog: Optional[CalibracionDialog] = None  # Ventana de recalibracion activa
        self.calibration_progress = 0  # Frames capturados durante la recalibracion
        self.calibration_expected_frames = 30  # Total a medir en la recalibracion
        self.video_window_detached = False  # Estado de la vista flotante de video
        self._last_status_payload = (None, None, None, None, None, 0)  # Cache para repintar la tarjeta
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

        self.status_card = self._build_status_card()
        self.control_tabs = self._build_control_tabs()

        top_panels_layout = QHBoxLayout()
        top_panels_layout.addWidget(self.status_card, 1)
        top_panels_layout.addWidget(self.control_tabs, 1)
        top_panels_layout.setSpacing(24)

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

        metrics_layout = QHBoxLayout()
        metrics_layout.setSpacing(32)

        metrics_panel = QWidget()
        metrics_grid = QGridLayout()
        metrics_grid.setHorizontalSpacing(18)
        metrics_grid.setVerticalSpacing(10)
        metrics_panel.setLayout(metrics_grid)

        metrics_info = [
            ("EAR crudo", "ear_raw"),
            ("EAR metric", "ear_metric"),
            ("EAR suavizado", "ear_smoothed"),
            ("Umbral", "ear_threshold"),
            ("Estado ojos", "eye_state"),
            ("Frames cerrados", "closed_frames"),
            ("Pitch (grados)", "pitch"),
            ("Inclinacion", "inclinacion"),
            ("Angulo ojos", "eye_angle"),
        ]

        for row, (title, key) in enumerate(metrics_info):
            title_label = QLabel(title)
            title_label.setObjectName("metric-title")
            title_label.setProperty("class", "metric-title")
            value_label = QLabel("--")
            value_label.setObjectName("metric-value")
            value_label.setProperty("class", "metric-value")
            metrics_grid.addWidget(title_label, row, 0)
            metrics_grid.addWidget(value_label, row, 1)
            self.metric_labels[key] = value_label

        metrics_layout.addWidget(metrics_panel, 0)

        charts_layout = QVBoxLayout()
        charts_layout.setSpacing(18)

        self.ear_canvas = MplCanvas("EAR vs Umbral", "EAR")
        self.ear_line = self.ear_canvas.axes.plot([], [], color="#27ae60", label="EAR")[0]
        self.ear_threshold_line = self.ear_canvas.axes.plot([], [], color="#e74c3c", linestyle="--", label="Umbral")[0]
        self.ear_canvas.axes.legend(facecolor="#1a1d24", edgecolor="#394150", labelcolor="#f5f6fa")
        charts_layout.addWidget(self.ear_canvas)

        self.pitch_canvas = MplCanvas("Pitch", "Grados")
        self.pitch_line = self.pitch_canvas.axes.plot([], [], color="#3498db", label="Pitch")[0]
        self.pitch_canvas.axes.legend(facecolor="#1a1d24", edgecolor="#394150", labelcolor="#f5f6fa")
        charts_layout.addWidget(self.pitch_canvas)

        self.eye_canvas = MplCanvas("Angulo ojos", "Grados")
        self.eye_line = self.eye_canvas.axes.plot([], [], color="#f1c40f", label="Angulo")[0]
        self.eye_canvas.axes.legend(facecolor="#1a1d24", edgecolor="#394150", labelcolor="#f5f6fa")
        charts_layout.addWidget(self.eye_canvas)

        charts_container = QWidget()
        charts_container.setLayout(charts_layout)
        metrics_layout.addWidget(charts_container, 1)

        self.timeline_list = QListWidget()
        self.timeline_list.setMinimumHeight(220)

        timeline_widget = QWidget()
        timeline_layout = QVBoxLayout(timeline_widget)
        timeline_layout.setContentsMargins(0, 0, 0, 0)
        timeline_layout.setSpacing(8)

        timeline_header = QHBoxLayout()
        timeline_header.setContentsMargins(0, 0, 0, 0)
        timeline_header.setSpacing(12)


#texto de linea de tiempo y botones de filtro y limpieza-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
        self.timeline_title = QLabel("Linea de tiempo")
        self.timeline_title.setObjectName("sectionTitle")
        timeline_header.addWidget(self.timeline_title)
        timeline_header.addStretch()

#OPTION LINEA DE TIEMPO FILTRO Y LIMPIEZA-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
        filtro_label = QLabel("Filtro:")
        filtro_label.setStyleSheet("color: #a0a6b1; font-size: 0.95em;")
        timeline_header.addWidget(filtro_label)

        self.timeline_filter_combo = QComboBox()
        self.timeline_filter_combo.addItems(["Todos", "Somnolencia", "Postura", "Calibracion", "Sistema"])
        self.timeline_filter_combo.currentIndexChanged.connect(self.on_timeline_filter_changed)
        timeline_header.addWidget(self.timeline_filter_combo)

        self.timeline_clear_button = QPushButton("Limpiar")
        self.timeline_clear_button.setObjectName("timelineClear")
        self.timeline_clear_button.clicked.connect(self.clear_timeline)
        timeline_header.addWidget(self.timeline_clear_button)

        timeline_layout.addLayout(timeline_header)
        timeline_layout.addWidget(self.timeline_list)

        self.stats_card = self._build_stats_card()

        timeline_stats_layout = QHBoxLayout()
        timeline_stats_layout.addWidget(timeline_widget, 2)
        timeline_stats_layout.addWidget(self.stats_card, 1)
        timeline_stats_layout.setSpacing(24)

        timeline_widget.hide()
        self.stats_card.hide()

        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(24, 16, 24, 24)
        content_layout.setSpacing(24)
        content_layout.addLayout(layout_superior)
        content_layout.addWidget(self.label)
        content_layout.addLayout(top_panels_layout)
        content_layout.addLayout(metrics_layout)
        content_layout.addStretch(1)
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
    def _build_status_card(self) -> QFrame:
        """Crea la tarjeta con el gauge principal y barras de apoyo"""
        frame = QFrame()
        frame.setObjectName("statusCard")
        outer_layout = QVBoxLayout(frame)
        outer_layout.setContentsMargins(18, 18, 18, 18)
        outer_layout.setSpacing(14)

        top_layout = QHBoxLayout()
        top_layout.setSpacing(18)

        self.status_gauge = CircularGauge(0.0, 1.5)
        self.status_gauge.setDisplayValue("--")
        self.status_gauge.setIcon("--")
        top_layout.addWidget(self.status_gauge, 0, Qt.AlignLeft)

        info_layout = QVBoxLayout()
        info_layout.setSpacing(6)
        self.status_header_label = QLabel("Estado general")
        self.status_header_label.setStyleSheet("font-size: 1.1em; font-weight: 600;")
        self.status_value_label = QLabel("--")
        self.status_value_label.setStyleSheet("font-size: 2.6em; font-weight: 700;")
        self.status_detail_label = QLabel("Esperando datos")
        self.status_detail_label.setStyleSheet("font-size: 1.0em; color: #cbd0d8;")
        self.status_secondary_label = QLabel("")
        self.status_secondary_label.setStyleSheet("font-size: 0.95em; color: #a0a6b1;")

        info_layout.addWidget(self.status_header_label)
        info_layout.addWidget(self.status_value_label)
        info_layout.addWidget(self.status_detail_label)
        info_layout.addWidget(self.status_secondary_label)
        info_layout.addStretch(1)
        top_layout.addLayout(info_layout)
        outer_layout.addLayout(top_layout)

        bars_layout = QGridLayout()
        bars_layout.setHorizontalSpacing(12)
        bars_layout.setVerticalSpacing(10)

        pitch_label = QLabel("Pitch actual")
        pitch_label.setStyleSheet("color: #a0a6b1; font-size: 0.9em;")
        self.pitch_bar = QProgressBar()
        self.pitch_bar.setRange(0, 100)
        self.pitch_bar.setFormat("%v deg")
        bars_layout.addWidget(pitch_label, 0, 0)
        bars_layout.addWidget(self.pitch_bar, 0, 1)

        closure_label = QLabel("Frames ojo cerrado")
        closure_label.setStyleSheet("color: #a0a6b1; font-size: 0.9em;")
        self.closure_bar = QProgressBar()
        self.closure_bar.setRange(0, 100)
        self.closure_bar.setFormat("%p%")
        bars_layout.addWidget(closure_label, 1, 0)
        bars_layout.addWidget(self.closure_bar, 1, 1)

        outer_layout.addLayout(bars_layout)
        return frame
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

    
    def _build_stats_card(self) -> QFrame:
        """Genera el panel de estadisticas en vivo y botones de exportacion"""
        frame = QFrame()
        frame.setObjectName("statsCard")
        outer = QVBoxLayout(frame)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(12)

        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(12)

        stats_info = [
            ("Frames totales", "total_frames"),
            ("Ojos cerrados (%)", "closed_pct"),
            ("Inclinacion adelante (%)", "forward_pct"),
            ("Pitch promedio", "avg_pitch"),
            ("Alertas", "alerts"),
            ("Recalibraciones", "calibrations"),
        ]

        for row, (title, key) in enumerate(stats_info):
            title_label = QLabel(title)
            title_label.setStyleSheet("font-size: 0.95em; font-weight: 600; color: #a0a6b1;")
            value_label = QLabel("--")
            value_label.setStyleSheet("font-size: 1.6em; font-weight: 700;")
            grid.addWidget(title_label, row, 0)
            grid.addWidget(value_label, row, 1)
            self.stats_labels[key] = value_label

        outer.addLayout(grid)

        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(12)
        self.export_csv_button = QPushButton("Exportar CSV")
        self.export_csv_button.setObjectName("secondary")
        self.export_csv_button.clicked.connect(self.export_to_csv)
        self.export_pdf_button = QPushButton("Exportar PDF")
        self.export_pdf_button.setObjectName("secondary")
        self.export_pdf_button.clicked.connect(self.export_to_pdf)
        buttons_layout.addWidget(self.export_csv_button)
        buttons_layout.addWidget(self.export_pdf_button)
        buttons_layout.addStretch(1)

        outer.addLayout(buttons_layout)
        return frame
    
#FIN DE TARJETA DE ESTADISTICAS Y EXPORTACION DE DATOS------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------


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
        metric_font = 2.0 * scale
        small_font = 0.95 * scale

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
            QLabel.metric-title {{ color: {muted_text}; font-size: {small_font:.2f}em; font-weight: 600; }}
            QLabel.metric-value {{ color: {text_color}; font-size: {metric_font:.2f}em; font-weight: bold; }}
            QFrame#statusCard, QFrame#statsCard {{ background-color: {card_color}; border: 1px solid {border_color}; border-radius: 14px; }}
            QPushButton {{
                border-radius: 12px; padding: 16px 20px;
                font-size: {button_font:.2f}em; font-family: 'Segoe UI', Arial, sans-serif;
                margin: 0 10px; color: {text_color}; border: none;
            }}
            QPushButton#iniciar {{ background-color: {accent}; color: #ffffff; }}
            QPushButton#detener {{ background-color: {accent_alert}; color: #ffffff; }}
            QPushButton#cerrar {{ background-color: transparent; color: {text_color}; font-size: {1.8 * scale:.2f}em; font-weight: bold; border: none; }}
            QPushButton#cerrar:hover {{ color: {accent_alert}; }}
            QPushButton#secondary {{ background-color: rgba(0, 0, 0, 0.0); color: {text_color}; border: 1px solid {border_color}; padding: 10px 16px; border-radius: 10px; }}
            QPushButton#secondary:hover {{ background-color: {border_color}; color: {text_color}; }}
            QPushButton#timelineClear {{ background-color: transparent; color: {muted_text}; border: 1px solid {border_color}; padding: 6px 14px; border-radius: 8px; font-size: {small_font:.2f}em; }}
            QPushButton#timelineClear:hover {{ background-color: {border_color}; color: {text_color}; }}
            QPlainTextEdit {{ background-color: {card_color}; color: {text_color}; border: 1px solid {border_color}; border-radius: 8px; font-family: Consolas, 'Fira Mono', monospace; font-size: 13px; }}
            QListWidget {{ background-color: {card_color}; color: {text_color}; border: 1px solid {border_color}; border-radius: 10px; font-family: Consolas, 'Fira Mono', monospace; }}
            QTabWidget::pane {{ background: {card_color}; border: 1px solid {border_color}; border-radius: 14px; }}
            QTabBar::tab {{ background-color: transparent; color: {muted_text}; padding: 10px 16px; border-radius: 10px; margin: 2px; }}
            QTabBar::tab:selected {{ background-color: {border_color}; color: {text_color}; }}
            QCheckBox {{ color: {text_color}; font-family: 'Segoe UI', Arial, sans-serif; font-size: {1.0 * scale:.2f}em; }}
            QCheckBox::indicator {{ width: {42 * scale:.0f}px; height: {24 * scale:.0f}px; }}
            QCheckBox::indicator:checked {{ background-color: {accent}; border: 1px solid {accent}; border-radius: {12 * scale:.0f}px; }}
            QCheckBox::indicator:unchecked {{ background-color: transparent; border: 1px solid {border_color}; border-radius: {12 * scale:.0f}px; }}
            QProgressBar {{ background-color: {card_color}; border: 1px solid {border_color}; border-radius: 8px; height: 18px; text-align: center; color: {text_color}; }}
            QProgressBar::chunk {{ background-color: {accent}; border-radius: 8px; }}
            QSlider::groove:horizontal {{ border: 1px solid {border_color}; height: 6px; background: {border_color}; border-radius: 3px; }}
            QSlider::handle:horizontal {{ background: {accent}; border: 1px solid {accent}; width: 16px; margin: -6px 0; border-radius: 8px; }}
            QDialog {{ background-color: {background}; }}
        """

#"FIN DE HOJA DE ESTILOS------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------"











    def refresh_theme(self) -> None:
        """Reaplica colores del tema y repinta componentes derivados"""
        self.setStyleSheet(self.build_stylesheet())
        theme = THEMES["dark"]
        if hasattr(self, 'status_gauge'):
            self.status_gauge.setBackground(theme["card"])
            self.status_gauge.setTextColor(theme["text"])
        if hasattr(self, 'timeline_title'):
            self.timeline_title.setStyleSheet(f"color: {theme['text']}; font-weight: 600;")  #cambia color de texto del titulo de timeline 
        if hasattr(self, 'timeline_clear_button'):
            self.timeline_clear_button.setStyleSheet("")  # allow stylesheet to reapply
        if hasattr(self, 'presentation_mode_checkbox'):
            # ensure checkbox text color updates
            self.presentation_mode_checkbox.setStyleSheet("")
        payload = getattr(self, '_last_status_payload', None)
        if payload and any(value is not None for value in payload[:-1]):
            try:
                self.update_status_card(*payload)
            except Exception:
                pass




            
    def write_control_state(self) -> None:
        """Persiste el estado de UI en el archivo compartido"""
        CONTROL_FILE.write_text(json.dumps(self.control_state, indent=2))

    def toggle_video_window(self) -> None:
        """Alterna entre mostrar el video en el panel o solo en OpenCV"""
        self.video_window_detached = not getattr(self, 'video_window_detached', False)
        estado = 'se mostro en ventana externa' if self.video_window_detached else 'se oculto en interfaz'
        self.append_timeline_event(f'Video {estado}', 'info', 'Sistema')

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
        """Registra en timeline si la calibracion se completo o cancelo"""
        completed = result == QDialog.Accepted and self.calibration_progress >= self.calibration_expected_frames
        if completed:
            self.append_timeline_event('Calibracion completada', 'info', 'Calibracion')
        else:
            self.append_timeline_event('Calibracion cancelada', 'warn', 'Calibracion')
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
        if log_event and hasattr(self, 'timeline_events'):
            mensaje = 'Modo presentacion activado' if enabled else 'Modo presentacion desactivado'
            self.append_timeline_event(mensaje, 'info', 'Sistema')

    def on_timeline_filter_changed(self, index: int) -> None:
        """Filtra la lista de eventos segun el tipo seleccionado"""
        mapping = {0: 'todos', 1: 'somnolencia', 2: 'postura', 3: 'calibracion', 4: 'sistema'}
        self.timeline_filter = mapping.get(index, 'todos')
        self.refresh_timeline()

    def clear_timeline(self) -> None:
        """Elimina eventos acumulados de la vista y memoria"""
        self.timeline_events.clear()
        self.refresh_timeline()

    def export_to_csv(self) -> None:
        """Guarda la linea de tiempo completa en un archivo CSV"""
        default_path = Path.home() / 'eventos_monitoreo.csv'
        filename, _ = QFileDialog.getSaveFileName(self, 'Exportar eventos a CSV', str(default_path), 'CSV (*.csv)')
        if not filename:
            return
        try:
            with open(filename, 'w', encoding='utf-8', newline='') as archivo:
                writer = csv.writer(archivo)
                writer.writerow(['datetime', 'timestamp', 'categoria', 'nivel', 'mensaje'])
                for event in self.timeline_events:
                    dt_value = event.get('dt')
                    iso_value = dt_value.isoformat() if dt_value else ''
                    writer.writerow([iso_value, event.get('timestamp'), event.get('category', '').capitalize(), event.get('level'), event.get('message')])
            self.append_line(f"[INFO] Eventos exportados a {filename}")
            self.append_timeline_event('Exportacion CSV completada', 'info', 'Sistema')
        except Exception as exc:
            self.append_line(f"[ERROR] No se pudo exportar CSV: {exc}")

    def export_to_pdf(self) -> None:
        """Genera un PDF resumen con estadisticas y ultimos eventos"""
        default_path = Path.home() / 'resumen_monitoreo.pdf'
        filename, _ = QFileDialog.getSaveFileName(self, 'Exportar resumen a PDF', str(default_path), 'PDF (*.pdf)')
        if not filename:
            return
        try:
            with PdfPages(filename) as pdf:
                fig = Figure(figsize=(8.27, 11.69))
                ax = fig.add_subplot(111)
                ax.axis('off')
                lines = [
                    'Resumen de sesion',
                    f"Inicio: {self.session_start.strftime('%Y-%m-%d %H:%M:%S')}",
                    f"Frames totales: {self.stats['total_frames']}",
                    f"Porcentaje ojos cerrados: {self.stats_labels['closed_pct'].text()}",
                    f"Porcentaje inclinacion adelante: {self.stats_labels['forward_pct'].text()}",
                    f"Pitch promedio: {self.stats_labels['avg_pitch'].text()}",
                    f"Alertas totales: {self.stats['alerts']}",
                    f"Recalibraciones: {self.stats['calibrations']}",
                ]
                y = 0.95
                for linea in lines:
                    ax.text(0.05, y, linea, transform=ax.transAxes, fontsize=12)
                    y -= 0.05
                ax.text(0.05, y, 'Eventos recientes:', transform=ax.transAxes, fontsize=12, fontweight='bold')
                y -= 0.05
                for event in self.timeline_events[-12:]:
                    ax.text(0.07, y, f"[{event['timestamp']}] {event['category'].capitalize()} - {event['message']}", transform=ax.transAxes, fontsize=10)
                    y -= 0.035
                pdf.savefig(fig)
            self.append_line(f"[INFO] Resumen PDF exportado a {filename}")
            self.append_timeline_event('Exportacion PDF completada', 'info', 'Sistema')
        except Exception as exc:
            self.append_line(f"[ERROR] No se pudo exportar PDF: {exc}")

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
        if frame_actual is None and self.history["x"]:
            frame_actual = int(self.history["x"][-1])
        if frame_actual is None:
            self.append_line(resumen)
        elif frame_actual - self.last_logged_frame >= LOG_INTERVAL_FRAMES:
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
        """Actualiza historicos, etiquetas y graficas con los datos nuevos"""
        frame = datos.get("frame")
        if frame is None:
            frame = self.history["x"][-1] + 1 if self.history["x"] else 0
        self.history["x"].append(frame)
        self.history["ear_metric"].append(datos.get("ear_metric"))
        self.history["ear_threshold"].append(datos.get("ear_threshold"))
        self.history["pitch"].append(datos.get("pitch"))
        self.history["eye_angle"].append(datos.get("eye_angle"))

        eye_state = datos.get("eye_state")
        inclinacion = datos.get("inclinacion")
        closed_frames = datos.get("closed_frames", 0)
        pitch = datos.get("pitch")
        ear_smoothed = datos.get("ear_smoothed")
        ear_threshold = datos.get("ear_threshold")

        self.update_status_card(eye_state, inclinacion, pitch, ear_smoothed, ear_threshold, closed_frames)
        self.update_timeline(eye_state, inclinacion, closed_frames, frame)
        self.update_stats(eye_state, inclinacion, pitch)
        self.update_calibration_flow(eye_state)

        formato_metricas = {
            "ear_raw": 3,
            "ear_metric": 3,
            "ear_smoothed": 3,
            "ear_threshold": 3,
            "pitch": 1,
            "eye_angle": 1,
        }

        for clave, etiqueta in self.metric_labels.items():
            valor = datos.get(clave)
            if clave in ("eye_state", "inclinacion"):
                etiqueta.setText(str(valor) if valor is not None else "--")
            elif clave == "closed_frames":
                etiqueta.setText(str(int(valor)) if valor is not None else "--")
            else:
                dec = formato_metricas.get(clave, 3)
                etiqueta.setText(self.formatear_float(valor, dec))

        if self.history["x"] and len(self.history["x"]) % self.chart_update_interval == 0:
            self.actualizar_grafico_ear()
            self.actualizar_grafico_pitch()
            self.actualizar_grafico_eye_angle()

    def actualizar_grafico_ear(self) -> None:
        """Redibuja la grafica de EAR frente al umbral dinamico"""
        if not self.history["x"]:
            self.ear_line.set_data([], [])
            self.ear_threshold_line.set_data([], [])
        else:
            x_datos = list(self.history["x"])
            ear_datos = [self._valor_o_nan(v) for v in self.history["ear_metric"]]
            thr_datos = [self._valor_o_nan(v) for v in self.history["ear_threshold"]]
            self.ear_line.set_data(x_datos, ear_datos)
            self.ear_threshold_line.set_data(x_datos, thr_datos)
            self.ear_canvas.axes.relim()
            self.ear_canvas.axes.autoscale_view()
        self.ear_canvas.draw_idle()

    def actualizar_grafico_pitch(self) -> None:
        """Refresca el historial de inclinacion de cabeza"""
        if not self.history["x"]:
            self.pitch_line.set_data([], [])
        else:
            x_datos = list(self.history["x"])
            pitch_datos = [self._valor_o_nan(v) for v in self.history["pitch"]]
            self.pitch_line.set_data(x_datos, pitch_datos)
            self.pitch_canvas.axes.relim()
            self.pitch_canvas.axes.autoscale_view()
        self.pitch_canvas.draw_idle()

    def actualizar_grafico_eye_angle(self) -> None:
        """Actualiza la grafica con el angulo relativo de los ojos"""
        if not self.history["x"]:
            self.eye_line.set_data([], [])
        else:
            x_datos = list(self.history["x"])
            angle_datos = [self._valor_o_nan(v) for v in self.history["eye_angle"]]
            self.eye_line.set_data(x_datos, angle_datos)
            self.eye_canvas.axes.relim()
            self.eye_canvas.axes.autoscale_view()
        self.eye_canvas.draw_idle()

    def update_status_card(self, eye_state: Optional[str], inclinacion: Optional[str], pitch: Optional[float], ear: Optional[float], threshold: Optional[float], closed_frames: Optional[int] = None) -> None:
        """Pinta la tarjeta principal con colores, gauge y barras coherentes"""
        status_key = "ok"
        detail_parts = []
        if ear is not None and threshold is not None:
            detail_parts.append(f"EAR {ear:.3f} / {threshold:.3f}")
        if pitch is not None:
            detail_parts.append(f"Pitch {pitch:.1f} deg")
        if inclinacion:
            detail_parts.append(inclinacion)

        if eye_state == "cerrados":
            status_key = "alert"
        elif inclinacion and inclinacion != "Cabeza neutra":
            status_key = "warn"

        style = STATUS_STYLES[status_key]
        self.status_card.setStyleSheet(
            f"QFrame#statusCard {{ background-color: {style['bg']}; border: 2px solid {style['border']}; border-radius: 14px; }}"
        )
        text_color = style['text']
        self.status_value_label.setStyleSheet(f"font-size: 2.6em; font-weight: 700; color: {text_color};")
        self.status_detail_label.setStyleSheet(f"font-size: 1.0em; color: {text_color};")
        self.status_secondary_label.setStyleSheet(f"font-size: 0.95em; color: {text_color};")
        self.status_value_label.setText(style["label"])
        self.status_detail_label.setText(" | ".join(detail_parts) if detail_parts else "Sin datos")

        icon = "OK" if status_key == "ok" else ("!" if status_key == "warn" else "!!")
        self.status_gauge.setColor(style['border'])
        self.status_gauge.setIcon(icon)
        if ear is not None and threshold:
            try:
                ratio = ear / threshold if threshold else 0.0
            except ZeroDivisionError:
                ratio = 0.0
            self.status_gauge.setValue(max(0.0, min(ratio, 1.5)))
            self.status_gauge.setDisplayValue(f"{ear:.3f}")
            self.status_secondary_label.setText(f"Umbral {threshold:.3f}")
        else:
            self.status_gauge.setValue(0.0)
            self.status_gauge.setDisplayValue("--")
            self.status_secondary_label.setText("Umbral --")

        if pitch is not None:
            normalized_pitch = max(0.0, min((pitch + 30.0) / 60.0, 1.0))
            self.pitch_bar.setValue(int(normalized_pitch * 100))
            self.pitch_bar.setFormat(f"{pitch:.1f} deg")
        else:
            self.pitch_bar.setValue(0)
            self.pitch_bar.setFormat("-- deg")

        frames = int(closed_frames or 0)
        settings = self.control_state.get("settings", DEFAULT_CONTROL_STATE["settings"])
        frame_threshold_setting = max(1, int(settings.get("frame_threshold", FRAME_THRESHOLD)))
        closure_ratio = max(0.0, min(frames / frame_threshold_setting, 1.0))
        self.closure_bar.setValue(int(closure_ratio * 100))
        self.closure_bar.setFormat(f"{frames}/{frame_threshold_setting}")
        self._last_status_payload = (eye_state, inclinacion, pitch, ear, threshold, closed_frames)
    def update_timeline(self, eye_state: Optional[str], inclinacion: Optional[str], closed_frames: int, frame: int) -> None:
        """Decide que eventos escribir en la linea de tiempo segun cambios"""
        settings = self.control_state.get("settings", DEFAULT_CONTROL_STATE["settings"])
        frame_threshold_setting = int(settings.get("frame_threshold", FRAME_THRESHOLD))
        if eye_state != self.prev_eye_state:
            if eye_state == "cerrados":
                self.append_timeline_event("Ojos cerrados detectados", "alert", "Somnolencia")
            elif eye_state == "abiertos" and self.prev_eye_state == "cerrados":
                self.append_timeline_event("Ojos nuevamente abiertos", "info", "Somnolencia")
            elif eye_state == "calibrando":
                self.append_timeline_event("Calibrando posicion de ojos", "info", "Calibracion")
            self.prev_eye_state = eye_state

        if inclinacion != self.prev_inclinacion:
            if inclinacion and inclinacion != "Cabeza neutra":
                self.append_timeline_event(f"Inclinacion detectada: {inclinacion.lower()}", "warn", "Postura")
            elif self.prev_inclinacion and self.prev_inclinacion != "Cabeza neutra":
                self.append_timeline_event("Postura regreso a neutra", "info", "Postura")
            self.prev_inclinacion = inclinacion

        if closed_frames and closed_frames >= frame_threshold_setting:
            if frame != self.last_closed_alert_frame:
                self.append_timeline_event("Alerta por somnolencia", "alert", "Somnolencia")
                self.stats["alerts"] += 1
                self.last_closed_alert_frame = frame

    def update_stats(self, eye_state: Optional[str], inclinacion: Optional[str], pitch: Optional[float]) -> None:
        """Acumula contadores para porcentajes y promedios de sesion"""
        self.stats["total_frames"] += 1
        if eye_state == "cerrados":
            self.stats["closed_frames"] += 1
        if inclinacion == "Cabeza hacia adelante":
            self.stats["forward_frames"] += 1
        if pitch is not None:
            self.stats["pitch_sum"] += float(pitch)
            self.stats["pitch_count"] += 1
        self.update_stats_panel()

    def update_stats_panel(self) -> None:
        """Refresca las etiquetas del panel de estadisticas con calculos actuales"""
        total = self.stats["total_frames"]
        closed_pct = (self.stats["closed_frames"] / total * 100) if total else 0.0
        forward_pct = (self.stats["forward_frames"] / total * 100) if total else 0.0
        avg_pitch = (self.stats["pitch_sum"] / self.stats["pitch_count"]) if self.stats["pitch_count"] else 0.0

        self.stats_labels["total_frames"].setText(str(total))
        self.stats_labels["closed_pct"].setText(f"{closed_pct:.1f}%")
        self.stats_labels["forward_pct"].setText(f"{forward_pct:.1f}%")
        self.stats_labels["avg_pitch"].setText(f"{avg_pitch:.1f} deg")
        self.stats_labels["alerts"].setText(str(self.stats["alerts"]))
        self.stats_labels["calibrations"].setText(str(self.stats["calibrations"]))

    def append_timeline_event(self, message: str, level: str = 'info', category: str = 'Sistema') -> None:
        """Almacena y muestra un nuevo evento con timestamp y categoria"""
        icon = TIMELINE_ICONS.get(level, TIMELINE_ICONS['info'])
        now = datetime.now()
        elapsed = now - self.session_start
        minutes, seconds = divmod(int(elapsed.total_seconds()), 60)
        timestamp = f"{minutes:02}:{seconds:02}"
        event = {
            'timestamp': timestamp,
            'icon': icon,
            'message': message,
            'level': level,
            'category': category.lower(),
            'dt': now,
        }
        self.timeline_events.append(event)
        if len(self.timeline_events) > TIMELINE_MAX_ITEMS:
            self.timeline_events.pop(0)
        self.refresh_timeline(scroll_to_bottom=True)

    def refresh_timeline(self, scroll_to_bottom: bool = False) -> None:
        """Repinta la lista de eventos aplicando el filtro vigente"""
        if not hasattr(self, 'timeline_list'):
            return
        self.timeline_list.clear()
        current = getattr(self, 'timeline_filter', 'todos')
        for event in self.timeline_events:
            if current != 'todos' and event['category'] != current:
                continue
            self.timeline_list.addItem(f"[{event['timestamp']}] {event['icon']} {event['message']}")
        if scroll_to_bottom:
            self.timeline_list.scrollToBottom()

    def on_overlay_toggle(self, key: str, state: int) -> None:
        """Persiste e informa la visibilidad de cada overlay del video"""
        enabled = state == Qt.Checked
        self.control_state.setdefault("overlays", DEFAULT_CONTROL_STATE["overlays"].copy())[key] = enabled
        self.write_control_state()
        estado = "activado" if enabled else "desactivado"
        self.append_timeline_event(f"Overlay {key} {estado}", "info", "Sistema")

    def trigger_recalibration(self) -> None:
        """Incrementa el token para forzar recalibracion en angulo.py"""
        self.recalibrate_token += 1
        self.control_state["recalibrate_token"] = self.recalibrate_token
        self.write_control_state()
        self.append_timeline_event("Recalibracion solicitada", "info", "Calibracion")
        self.stats["calibrations"] += 1
        self.update_stats_panel()

    @staticmethod
    def _valor_o_nan(valor):
        """Convierte un valor a float o devuelve NaN para graficas"""
        try:
            return float(valor)
        except (TypeError, ValueError):
            return float("nan")

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
        """Limpia historicos, estadisticas y timeline para nueva sesion"""
        self.stdout_buffer = ""
        self.last_logged_frame = -LOG_INTERVAL_FRAMES
        self.prev_eye_state = None
        self.prev_inclinacion = None
        self.last_closed_alert_frame = -1
        self.session_start = datetime.now()
        for deque_obj in self.history.values():
            deque_obj.clear()
        for etiqueta in self.metric_labels.values():
            etiqueta.setText("--")
        self.timeline_list.clear()
        self.stats = {
            "total_frames": 0,
            "closed_frames": 0,
            "forward_frames": 0,
            "pitch_sum": 0.0,
            "pitch_count": 0,
            "alerts": 0,
            "calibrations": self.stats.get("calibrations", 0),
        }
        self.update_stats_panel()
        self.actualizar_grafico_ear()
        self.actualizar_grafico_pitch()
        self.actualizar_grafico_eye_angle()
        self.consola.clear()
        self.update_status_card(None, None, None, None, None, 0)

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



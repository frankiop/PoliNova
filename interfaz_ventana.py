import sys
import json
from typing import Optional, List
from pathlib import Path
from graficas import grafica

from PyQt5.QtWidgets import (
    QApplication,
    QWidget,
    QPushButton,
    QVBoxLayout,
    QLabel,
    QHBoxLayout,
    QSlider,
    QGroupBox,
    QCheckBox,
    QFrame,
    QGraphicsDropShadowEffect,
)
from PyQt5.QtCore import Qt, QProcess, QPoint, QTimer
from PyQt5.QtGui import QColor

LOG_INTERVAL_FRAMES = 12  # Cada cuantos frames escribimos un resumen en el log
CONTROL_FILE = Path(__file__).with_name("control_state.json")  # Archivo compartido con el detector
# Estado inicial que sincroniza overlays y ajustes con angulo.py


#configuracion predefinida si no logra leer el archivo json-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
DEFAULT_CONTROL_STATE = {
    "recalibrate_token": 0,
    "overlays": {
        "geometry": True,
        "text": True,
    },
    "settings": {
        "ear_dynamic_ratio": 0.92,
        "sound_alert": True,
        "visual_alert": True
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
# Ventana principal del panel docente que controla angulo.py y visualiza metricas
class VentanaPrincipal(QWidget):
    def __init__(self) -> None:
        """Inicializa estados, buffers y lanza la construccion de la interfaz"""
        super().__init__()
        self.ear_series: List[float] = []  # Serie temporal de EAR para graficar
        self.ear_baseline_series: List[float] = []  # Serie temporal de EAR baseline para graficar
        self.timer_grafica = QTimer(self)
        self.timer_grafica.setInterval(100)
        self.timer_grafica.timeout.connect(self._refrescar_grafica)
        self.proceso: Optional[QProcess] = None  # Handler del proceso lanzado
        self.stdout_buffer = ""  # Buffer para reconstruir lineas parciales
        self.control_state = self.ensure_control_state()  # Preferencias leidas de control_state.json
        self.last_logged_frame = -LOG_INTERVAL_FRAMES  # Frame usado para muestrear logs
        settings = self.control_state.get("settings", {})  # Preferencias personalizadas del usuario
        self.theme_name = "dark"  # Tema visual fijo en modo oscuro
        self._drag_pos: Optional[QPoint] = None  # Soporta arrastre de ventana flotante
        self.initUI()

    def initUI(self) -> None:
        """Arma toda la disposicion de widgets, estilos y conexiones"""
        self.setWindowTitle("Control de angulo.py")
        self.setWindowFlags(self.windowFlags() | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.resize(840, 620)#tamano de la ventana

        self.boton_cerrar = QPushButton("×", self)#boton para cerrar la ventana 
        self.boton_cerrar.setObjectName("cerrar")
        self.boton_cerrar.clicked.connect(self.close)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(18, 118, 18, 18)

        card = QFrame()
        card.setObjectName("card")
        card.setFrameShape(QFrame.NoFrame)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(24)
        shadow.setOffset(0, 10)
        shadow.setColor(QColor(0, 0, 0, 120))
        card.setGraphicsEffect(shadow)

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(24, 24, 24, 24)
        card_layout.setSpacing(20)

        header_layout = QHBoxLayout()
        header_layout.setSpacing(12)
        header_title = QLabel("Control de angulo.py")
        header_title.setObjectName("windowTitle")
        header_layout.addWidget(header_title)
        header_layout.addStretch(1)
        header_layout.addWidget(self.boton_cerrar)

        self.status_label = QLabel("Presiona iniciar para ejecutar deteccion")
        self.status_label.setObjectName("status")
        self.status_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.status_label.setWordWrap(True)


        self.boton_grafica = QPushButton("Mostrar grafica")
        self.boton_grafica.clicked.connect(self.mostrar_grafica)

        self.boton_iniciar = QPushButton("Iniciar")
        self.boton_iniciar.setObjectName("iniciar")
        self.boton_iniciar.clicked.connect(self.iniciar_script)

        self.boton_detener = QPushButton("Detener Deteccion")
        self.boton_detener.setObjectName("detener")
        self.boton_detener.clicked.connect(self.detener_script)
        self.boton_detener.setEnabled(False)

        overlays_panel = self._build_overlay_panel()
        settings_panel = self._build_settings_panel()

        botones_layout = QHBoxLayout()
        botones_layout.setSpacing(12)
        botones_layout.addStretch(1)
        botones_layout.addWidget(self.boton_iniciar)
        botones_layout.addWidget(self.boton_grafica)
        botones_layout.addWidget(self.boton_detener)

        card_layout.addLayout(header_layout)
        card_layout.addWidget(self.status_label)
        card_layout.addWidget(overlays_panel)
        card_layout.addWidget(settings_panel)
        card_layout.addStretch(1)
        card_layout.addLayout(botones_layout)

        root_layout.addWidget(card)

        self.refresh_theme()

    def _build_overlay_panel(self) -> QGroupBox:
        """Prepara controles de overlays dentro de un panel compacto."""
        group = QGroupBox("Overlays activos")
        group.setObjectName("overlaysGroup")
        layout = QVBoxLayout(group)
        layout.setSpacing(12)

        overlay_layout = QHBoxLayout()
        overlay_layout.setSpacing(16)

        overlays = self.control_state.get("overlays", DEFAULT_CONTROL_STATE["overlays"]).copy()
        self.checkbox_landmarks = QCheckBox("Landmarks")
        self.checkbox_landmarks.setChecked(overlays.get("landmarks", True))
        self.checkbox_landmarks.stateChanged.connect(lambda state: self.on_overlay_toggle("landmarks", state))

        

        self.checkbox_text = QCheckBox("Textos")
        self.checkbox_text.setChecked(overlays.get("text", True))
        self.checkbox_text.stateChanged.connect(lambda state: self.on_overlay_toggle("text", state))

        overlay_layout.addWidget(self.checkbox_landmarks)
        # overlay_layout.addWidget(self.checkbox_geometry)
        overlay_layout.addWidget(self.checkbox_text)
        overlay_layout.addStretch(1)
        layout.addLayout(overlay_layout)

        return group
    def _build_settings_panel(self) -> QWidget:
        """Construye sliders y toggles para sensibilidad y alertas"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        settings = self.control_state.get("settings", DEFAULT_CONTROL_STATE["settings"]).copy()

        sensibilidad_group = QGroupBox("Sensibilidad ocular")
        sensibilidad_group.setStyleSheet("color: #3498db;")#Color del texto  EAR y Frames (sensibilidad ocular)
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

        return panel
    #FIN   HASTA AQUI ES CONFIGURACION DE SENSIBILIDAD Y ALERTAS----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

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
            QWidget {{
                background-color: transparent;
                color: {text_color};
                font-family: 'Segoe UI', Arial, sans-serif;
            }}
            QFrame#card {{
                background-color: {background};
                border: 1px solid {border_color};
                border-radius: 20px;
            }}
            QLabel {{
                color: {text_color};
                font-size: {body_font:.2f}em;
            }}
            QLabel#windowTitle {{
                font-size: {title_font:.2f}em;
                font-weight: 700;
            }}
            QLabel#status {{
                color: {muted_text};
                font-size: {body_font:.2f}em;
            }}
            QPushButton {{
                border-radius: 12px;
                padding: 12px 18px;
                font-size: {button_font:.2f}em;
                font-family: 'Segoe UI', Arial, sans-serif;
                color: {text_color};
                border: none;
                background-color: {border_color};
            }}
            QPushButton#iniciar {{ background-color: {accent}; color: #ffffff; }}
            QPushButton#detener {{ background-color: {accent_alert}; color: #ffffff; }}
            QPushButton#cerrar {{
                background-color: transparent;
                color: {muted_text};
                font-size: {1.6 * scale:.2f}em;
                font-weight: bold;
                padding: 4px 8px;
                min-width: 32px;
            }}
            QPushButton#cerrar:hover {{ color: {accent_alert}; }}
            QCheckBox {{
                color: {text_color};
                font-size: {body_font:.2f}em;
            }}
            QCheckBox::indicator {{
                width: {32 * scale:.0f}px;
                height: {18 * scale:.0f}px;
            }}
            QCheckBox::indicator:checked {{
                background-color: {accent};
                border: 1px solid {accent};
                border-radius: {9 * scale:.0f}px;
            }}
            QCheckBox::indicator:unchecked {{
                background-color: transparent;
                border: 1px solid {border_color};
                border-radius: {9 * scale:.0f}px;
            }}
            QSlider::groove:horizontal {{
                border: 1px solid {border_color};
                height: 6px;
                background: {border_color};
                border-radius: 3px;
            }}
            QSlider::handle:horizontal {{
                background: {accent};
                border: 1px solid {accent};
                width: 16px;
                margin: -6px 0;
                border-radius: 8px;
            }}
            QGroupBox {{
                background-color: {card_color};
                border: 1px solid {border_color};
                border-radius: 16px;
                margin-top: 12px;
                padding: 16px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 18px;
                padding: 0 8px;
                font-weight: 600;
                color: {accent};
            }}
        """   
#"FIN DE HOJA DE ESTILOS------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------"
    def refresh_theme(self) -> None:
        """Reaplica colores del tema vigente."""
        self.setStyleSheet(self.build_stylesheet())

    def write_control_state(self) -> None:
        """Persiste el estado de UI en el archivo compartido"""
        CONTROL_FILE.write_text(json.dumps(self.control_state, indent=2))

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

    def on_sound_alert_toggled(self, enabled: bool) -> None:
        """Activa o desactiva la alarma sonora en angulo.py"""
        self.control_state.setdefault('settings', DEFAULT_CONTROL_STATE['settings'].copy())['sound_alert'] = bool(enabled)
        self.write_control_state()

    def on_visual_alert_toggled(self, enabled: bool) -> None:
        """Controla si se imprimen overlays de alerta en el video"""
        self.control_state.setdefault('settings', DEFAULT_CONTROL_STATE['settings'].copy())['visual_alert'] = bool(enabled)
        self.write_control_state()

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
        self.status_label.setText("Iniciando deteccion...")
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
            print(texto, end="")

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
        """Actualiza el resumen visible con la informacion mas reciente."""#informacion  de la parte superior de la ventana controles y funcionamiento de la frafica 
        eye_state = datos.get("eye_state")
        pitch = datos.get("pitch")
        closed_frames = datos.get("closed_frames")
        ear_smoothed = datos.get("ear_smoothed")
        ear_threshold = datos.get("ear_threshold")

        resumen: List[str] = []
        if eye_state:
            resumen.append(f"Ojos: {eye_state}")
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
            self.status_label.setText(" | ".join(resumen))
        else:
            self.status_label.setText("Recibiendo datos...")

        ear = datos.get("ear_smoothed")
        ear_thr = datos.get("ear_threshold")
        if ear is not None:
            self.ear_series.append(float(ear))
            if len(self.ear_series) > 600:
                del self.ear_series[0]
        if ear_thr is not None:
            self.ear_baseline_series.append(float(ear_thr))
            if len(self.ear_baseline_series) > 600:
                del self.ear_baseline_series[0]

    def _refrescar_grafica(self) -> None:
        """Actualiza la ventana de Matplotlib con las series acumuladas."""
        if not self.ear_series or not self.ear_baseline_series:
            return
        grafica(
            list(self.ear_baseline_series),
            list(self.ear_series),
        )





    def mostrar_grafica(self) -> None:
        """Invoca la grafica de EAR si existen datos acumulados."""
        if not self.ear_series or not self.ear_baseline_series:
            self.append_line("[WARN] Aun no hay datos suficientes para graficar.")
            self.status_label.setText("Sin datos para graficar")
            return

        self._refrescar_grafica()
        if not self.timer_grafica.isActive():
            self.timer_grafica.start()
#---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------




    def on_overlay_toggle(self, key: str, state: int) -> None:
        """Guarda el estado de cada overlay y registra la accion en el log."""
        enabled = state == Qt.Checked
        overlays = self.control_state.setdefault("overlays", DEFAULT_CONTROL_STATE["overlays"].copy())
        overlays[key] = enabled
        self.write_control_state()
        estado = "activado" if enabled else "desactivado"
        self.append_line(f"[INFO] Overlay {key} {estado}")

    def append_line(self, line: str) -> None:
        """Registra una linea en el log de la aplicacion."""
        print(line)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        """Permite arrastrar la ventana flotante al hacer click sostenido."""
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        """Actualiza la posicion durante el arrastre."""
        if self._drag_pos is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPos() - self._drag_pos)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        """Reinicia el estado de arrastre al soltar el click."""
        if event.button() == Qt.LeftButton:
            self._drag_pos = None
        super().mouseReleaseEvent(event)

    def detener_script(self) -> None:
        """Termina con cuidado el proceso si sigue en ejecucion"""
        if self.proceso:
            if self.proceso.state() != QProcess.NotRunning:
                self.proceso.terminate()
                if not self.proceso.waitForFinished(1500):
                    self.proceso.kill()
                    self.proceso.waitForFinished(1000)
            self.append_line("[INFO] angulo.py detenido")
            self.status_label.setText("angulo.py detenido")
            self.boton_iniciar.setEnabled(True)
            self.boton_detener.setEnabled(False)
            self.timer_grafica.stop()

    def proceso_termino(self, exitCode: int, exitStatus: QProcess.ExitStatus) -> None:
        """Gestiona el cierre natural del proceso e informa en UI"""
        self.append_line(f"[INFO] angulo.py termino (code={exitCode})")
        self.status_label.setText("Proceso finalizado")
        self.boton_iniciar.setEnabled(True)
        self.boton_detener.setEnabled(False)
        self.proceso = None  

        

    def reset_metrics(self) -> None:
        """Resetea buffers para una nueva sesion."""
        self.stdout_buffer = ""
        self.last_logged_frame = -LOG_INTERVAL_FRAMES
        self.status_label.setText("Esperando datos del detector...")
        self.timer_grafica.stop()
        self.ear_series.clear()
        self.ear_baseline_series.clear()

    def closeEvent(self, event) -> None:  # type: ignore[override]
        """Detiene el proceso al cerrar la ventana para evitar zombies"""
        self.timer_grafica.stop()
        try:
            self.detener_script()
        finally:

            event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    ventana = VentanaPrincipal()
    ventana.show()
    sys.exit(app.exec_())

import os
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'  # Oculta advertencias de TensorFlow
import winsound
import cv2
import mediapipe as mp
import numpy as np
import matplotlib.pyplot as plt 
from collections import deque 
import json
from math import acos, degrees
from collections import deque
from pathlib import Path
from pathlib import Path
#from playsound import playsound

ALERT_SOUND = Path(__file__).with_name("alarma.mp3")

def eye_aspect_ratio(coordinates):
    d_A = np.linalg.norm(np.array(coordinates[1]) - np.array(coordinates[5]))
    d_B = np.linalg.norm(np.array(coordinates[2]) - np.array(coordinates[4]))
    d_C = np.linalg.norm(np.array(coordinates[0]) - np.array(coordinates[3]))# Evitar division por cero

    return (d_A + d_B) / (2 * d_C)  # Calcular la relacion de aspecto del ojo

def landmark_to_point(landmark, width, height):# Convierte un punto de referencia normalizado a coordenadas de pixel
    return np.array([landmark.x * width, landmark.y * height, landmark.z * width], dtype=np.float32)


def eye_vertical_ratio(face_landmarks, width, height, vertical_pairs, horizontal_pair):#
    p_start = landmark_to_point(face_landmarks.landmark[horizontal_pair[0]], width, height)
    p_end = landmark_to_point(face_landmarks.landmark[horizontal_pair[1]], width, height)
    horizontal_dist = np.linalg.norm(p_start - p_end)
    if horizontal_dist < 1e-5:
        return 0.0

    distances = []
    for top_idx, bottom_idx in vertical_pairs:
        top_point = landmark_to_point(face_landmarks.landmark[top_idx], width, height)
        bottom_point = landmark_to_point(face_landmarks.landmark[bottom_idx], width, height)
        distances.append(np.linalg.norm(top_point - bottom_point))

    distances.sort()
    if len(distances) >= 2:
        vertical_metric = float(np.mean(distances[:2]))
    else:
        vertical_metric = float(distances[0]) if distances else 0.0

    return vertical_metric / horizontal_dist

CONTROL_FILE = Path(__file__).with_name("control_state.json")
DEFAULT_CONTROL_STATE = {
    "recalibrate_token": 0,
    "overlays": {
        "landmarks": True,
        "geometry": True,
        "text": True
    },
    "settings": {
        "ear_dynamic_ratio": 0.92,
        "frame_threshold": 50,
        "pitch_forward_threshold": 12.0,
        "pitch_backward_threshold": -8.0,
        "sound_alert": True,
        "visual_alert": True,
        "theme": "dark",
        "presentation_mode": False
    }
}


def ensure_control_state_file() -> dict:
    if not CONTROL_FILE.exists():
        CONTROL_FILE.write_text(json.dumps(DEFAULT_CONTROL_STATE, indent=2))
        return DEFAULT_CONTROL_STATE.copy()
    try:
        data = json.loads(CONTROL_FILE.read_text())
        if not isinstance(data, dict):
            raise ValueError("Invalid control state format")
        overlays = data.get("overlays")
        if not isinstance(overlays, dict):
            data["overlays"] = DEFAULT_CONTROL_STATE["overlays"].copy()
            overlays = data["overlays"]
        else:
            for key, value in DEFAULT_CONTROL_STATE["overlays"].items():
                overlays.setdefault(key, value)

        settings = data.get("settings")
        if not isinstance(settings, dict):
            data["settings"] = DEFAULT_CONTROL_STATE["settings"].copy()
        else:
            for key, value in DEFAULT_CONTROL_STATE["settings"].items():
                settings.setdefault(key, value)
        if "recalibrate_token" not in data:
            data["recalibrate_token"] = 0
        return data
    
    except Exception:
        CONTROL_FILE.write_text(json.dumps(DEFAULT_CONTROL_STATE, indent=2))
        return DEFAULT_CONTROL_STATE.copy()

def load_control_state(previous_state: dict) -> dict:
    try:
        data = json.loads(CONTROL_FILE.read_text())
        if isinstance(data, dict):
            overlays = data.get("overlays", {})
            if not isinstance(overlays, dict):
                overlays = previous_state.get("overlays", {}).copy()
            settings = data.get("settings", {})
            if not isinstance(settings, dict):
                settings = previous_state.get("settings", DEFAULT_CONTROL_STATE["settings"].copy())
            merged = previous_state.copy()
            merged.update({
                "recalibrate_token": data.get("recalibrate_token", previous_state.get("recalibrate_token", 0)),
                "overlays": {
                    "landmarks": overlays.get("landmarks", True),
                    "geometry": overlays.get("geometry", True),
                    "text": overlays.get("text", True),
                },
                "settings": {
                    "ear_dynamic_ratio": float(settings.get("ear_dynamic_ratio", DEFAULT_CONTROL_STATE["settings"]["ear_dynamic_ratio"])),
                    "frame_threshold": int(settings.get("frame_threshold", DEFAULT_CONTROL_STATE["settings"]["frame_threshold"])),
                    "pitch_forward_threshold": float(settings.get("pitch_forward_threshold", DEFAULT_CONTROL_STATE["settings"]["pitch_forward_threshold"])),
                    "pitch_backward_threshold": float(settings.get("pitch_backward_threshold", DEFAULT_CONTROL_STATE["settings"]["pitch_backward_threshold"])),
                    "sound_alert": bool(settings.get("sound_alert", DEFAULT_CONTROL_STATE["settings"]["sound_alert"])),
                    "visual_alert": bool(settings.get("visual_alert", DEFAULT_CONTROL_STATE["settings"]["visual_alert"])),
                    "theme": settings.get("theme", DEFAULT_CONTROL_STATE["settings"]["theme"]),
                    "presentation_mode": bool(settings.get("presentation_mode", DEFAULT_CONTROL_STATE["settings"]["presentation_mode"])),
                },
            })
            return merged
    except Exception:
        pass
    return previous_state




# Inicializar MediaPipe Face Mesh
mp_face_mesh = mp.solutions.face_mesh
mp_face_detection = mp.solutions.face_detection
index_left_eye = [33, 160, 158, 133, 153, 144]
index_right_eye = [362, 385, 387, 263, 373, 380]
LEFT_EYE_VERTICAL_PAIRS = [(159, 145), (158, 144), (160, 153)]
RIGHT_EYE_VERTICAL_PAIRS = [(386, 374), (385, 380), (387, 381)]
LEFT_EYE_HORIZONTAL_PAIR = (33, 133) 
RIGHT_EYE_HORIZONTAL_PAIR = (362, 263)




CAMERA_INDEX = 1
CAPTURE_BACKEND = getattr(cv2, "CAP_DSHOW", None)
CAMERA_TARGET_FPS = 30
CAMERA_WIDTH = 640
CAMERA_HEIGHT = 480
FOURCC_CODE = "MJPG"

control_state = ensure_control_state_file()
last_recalibrate_token = control_state.get("recalibrate_token", 0)

# Iniciar la captura de video desde la camara
if CAPTURE_BACKEND is not None:
    cap = cv2.VideoCapture(CAMERA_INDEX, CAPTURE_BACKEND) 
else:
    cap = cv2.VideoCapture(CAMERA_INDEX)

if not cap.isOpened():
    print("No se pudo abrir la camara. Verifica que este conectada y disponible.")
    exit()

if hasattr(cv2, "CAP_PROP_BUFFERSIZE"):
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_WIDTH)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_HEIGHT)
if CAMERA_TARGET_FPS:
    cap.set(cv2.CAP_PROP_FPS, CAMERA_TARGET_FPS)
if FOURCC_CODE and hasattr(cv2, "VideoWriter_fourcc"):
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*FOURCC_CODE))

EAR_THRESH = 0.26  # Umbral base para la relacion de aspecto del ojo
FRAME_THRESHOLD = 50  # Numero de frames para considerar que el ojo esta cerrado
EAR_SMOOTHING_WINDOW = 3  # Ventana corta para suavizar el EAR sin retraso
CALIBRATION_FRAMES = 30  # Frames iniciales para calibrar el EAR abierto
EAR_DYNAMIC_RATIO = 0.85  # Factor para generar umbral dinamico desde la linea base
MIN_DYNAMIC_EAR = 0.18  # Limite inferior para el umbral dinamico
EAR_BASELINE_ALPHA = 0.06  # Peso para actualizar la linea base del EAR
EAR_BASELINE_GUARD_RATIO = 0.85  # Evita que la linea base caiga con ojos cerrados
EAR_MIN_MARGIN = 0.015  # Diferencia minima entre la linea base y el umbral


closed_frames = 0

# Buffers para mejorar la estabilidad de la medida
ear_history = deque(maxlen=EAR_SMOOTHING_WINDOW)
ear_baseline_values = deque(maxlen=CALIBRATION_FRAMES)# es un histortial en donde se borra el valor mas antiguo al agregar uno nuevo
ear_baseline = None
frame_counter = 0

# Inicializar Face Detection
face_detection = mp_face_detection.FaceDetection(model_selection=0, min_detection_confidence=0.5)

# Configurar Face Mesh para detectar un maximo de un rostro
with mp_face_mesh.FaceMesh(
    min_detection_confidence=0.5,
    static_image_mode=False,  # Modo dinamico para video en tiempo real
    max_num_faces=1,
    refine_landmarks=True) as face_mesh:

    while True:
        control_state = load_control_state(control_state)
        overlays = control_state.get("overlays", {})
        show_landmarks = overlays.get("landmarks", True)
        show_geometry = overlays.get("geometry", True)
        show_text = overlays.get("text", True)

        settings = control_state.get("settings", DEFAULT_CONTROL_STATE["settings"])
        ear_dynamic_ratio_cfg = float(settings.get("ear_dynamic_ratio", EAR_DYNAMIC_RATIO))
        frame_threshold_cfg = max(1, int(settings.get("frame_threshold", FRAME_THRESHOLD)))

        sound_alert_enabled = bool(settings.get("sound_alert", True))
        visual_alert_enabled = bool(settings.get("visual_alert", True))

        newly_requested_recalibration = control_state.get("recalibrate_token", 0)
        if newly_requested_recalibration != last_recalibrate_token:
            last_recalibrate_token = newly_requested_recalibration
            ear_baseline = None
            ear_baseline_values.clear()
            ear_history.clear()
            closed_frames = 0

        # Leer un frame de la camara
        ret, frame = cap.read()
        if not ret:
            break

        # Voltear el frame horizontalmente para una vista tipo espejo
        frame = cv2.flip(frame, 1)
        frame_counter += 1
        eye_angle = None
        pitch_angle_value = None
        inclinacion_value = "Sin rostro"
        eye_state = "calibrando"

        height, width, _ = frame.shape
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = face_mesh.process(frame_rgb)
        resultados = face_detection.process(frame_rgb)

        coordinates_left_eye = []
        coordinates_right_eye = []
        d_eyes = None


        if results.multi_face_landmarks is not None:
            for face_landmarks in results.multi_face_landmarks:
                for index in index_left_eye:
                    landmark = face_landmarks.landmark[index]
                    x = int(landmark.x * width)
                    y = int(landmark.y * height)
                    if show_landmarks:
                        cv2.circle(frame, (x, y), 2, (0, 255, 0), -1)
                    coordinates_left_eye.append([landmark.x * width, landmark.y * height, landmark.z * width])

                for index in index_right_eye:
                    landmark = face_landmarks.landmark[index]
                    x = int(landmark.x * width)
                    y = int(landmark.y * height)
                    if show_landmarks:
                        cv2.circle(frame, (x, y), 2, (0, 255, 0), -1)
                    coordinates_right_eye.append([landmark.x * width, landmark.y * height, landmark.z * width])

                if coordinates_left_eye and coordinates_right_eye:
                    ear_left_eye = eye_aspect_ratio(coordinates_left_eye)
                    ear_right_eye = eye_aspect_ratio(coordinates_right_eye)
                    ear_raw = (ear_left_eye + ear_right_eye) / 2

                    vertical_left = eye_vertical_ratio(face_landmarks, width, height, LEFT_EYE_VERTICAL_PAIRS, LEFT_EYE_HORIZONTAL_PAIR)
                    vertical_right = eye_vertical_ratio(face_landmarks, width, height, RIGHT_EYE_VERTICAL_PAIRS, RIGHT_EYE_HORIZONTAL_PAIR)
                    ear_metric_left = min(ear_left_eye, vertical_left)
                    ear_metric_right = min(ear_right_eye, vertical_right)
                    ear = (ear_metric_left + ear_metric_right) / 2

                    ear_history.append(ear)
                    ear_smoothed = sum(ear_history) / len(ear_history)

                    if ear_baseline is None:
                        ear_baseline_values.append(ear_smoothed)
                        if len(ear_baseline_values) >= CALIBRATION_FRAMES:
                            ear_baseline = float(np.median(ear_baseline_values))
                    else:
                        # Ajuste suave solo cuando el EAR sigue en la zona abierta
                        if ear_smoothed >= ear_baseline * EAR_BASELINE_GUARD_RATIO:
                            ear_baseline_values.append(ear_smoothed)
                            baseline_objetivo = float(np.median(ear_baseline_values))
                            ear_baseline = float(ear_baseline * (1 - EAR_BASELINE_ALPHA) + baseline_objetivo * EAR_BASELINE_ALPHA)

                    if ear_baseline is not None:
                        drop_from_ratio = ear_baseline * (1 - ear_dynamic_ratio_cfg)
                        drop = max(EAR_MIN_MARGIN, drop_from_ratio)
                        ear_threshold = max(MIN_DYNAMIC_EAR, ear_baseline - drop)
                    else:
                        ear_threshold = EAR_THRESH

                    if show_text:
                        cv2.putText(frame, f"EAR: {ear_smoothed:.3f}", (20, height - 140), 1, 1.5, (0, 255, 255), 2)
                        cv2.putText(frame, f"Umbral: {ear_threshold:.3f}", (20, height - 110), 1, 1.5, (0, 255, 255), 2)

                    if ear_baseline is None:
                        if show_text:
                            cv2.putText(frame, "Calibrando ojos... mantelos abiertos", (20, height - 170), 0, 0.7, (0, 255, 255), 2)
                        closed_frames = 0
                        eye_state = "calibrando"
                    else:
                        if ear_smoothed < ear_threshold:
                            closed_frames += 1
                            eye_state = "cerrados"
                        else:
                            closed_frames = 0
                            eye_state = "abiertos"

                        if closed_frames >= frame_threshold_cfg:
                            if visual_alert_enabled and show_text:
                                cv2.putText(frame, "ALERTA", (75, 75), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
                            if sound_alert_enabled:
                                winsound.Beep(1000, 100)


                metrics_payload = {
                    "frame": frame_counter,
                    "ear_raw": float(ear_raw),
                    "ear_metric": float(ear),
                    "ear_smoothed": float(ear_smoothed),
                    "ear_threshold": float(ear_threshold),
                    "eye_state": eye_state,
                    "closed_frames": int(closed_frames),
                    "pitch": float(pitch_angle_value) if pitch_angle_value is not None else None,
                    "inclinacion": inclinacion_value,
                    "eye_angle": float(eye_angle) if eye_angle is not None else None
                }
                print(json.dumps(metrics_payload), flush=True)
        else:
            closed_frames = 0


        # Mostrar el video en una ventana
        cv2.imshow("Video.Capture", frame)

        # Esperar a que el usuario presione la tecla 'Esc' para salir
        k = cv2.waitKey(20) & 0xFF
        if k == 27:  # Codigo ASCII para 'Esc'
            break

# Liberar la camara y cerrar las ventanas
cap.release()
cv2.destroyAllWindows()

import numpy as np
import matplotlib.pyplot as plt

# Objetos globales para reutilizar la ventana de Matplotlib entre invocaciones
_figure = None
_line_baseline = None
_line_actual = None


def grafica(ear_baseline_values, ear_values):
    """Muestra/actualiza la grafica con el EAR actual y su umbral."""
    global _figure, _line_baseline, _line_actual

    if not ear_baseline_values or not ear_values:
        return None

    length = min(len(ear_baseline_values), len(ear_values))
    if length == 0:
        return None

    xs = np.arange(length)
    baseline = np.array(ear_baseline_values[-length:])
    actual = np.array(ear_values[-length:])

    if _figure is None or _line_baseline is None or _line_actual is None:
        plt.style.use("ggplot")
        plt.ion()
        _figure, ax = plt.subplots()
        _line_baseline, = ax.plot(xs, baseline, "b-", label="EAR Threshold")
        _line_actual, = ax.plot(xs, actual, "r-", label="EAR Actual")
        ax.set_ylabel("EAR Value", fontsize=18)
        ax.set_xlim(0, max(xs[-1], 1))
        ax.legend()
    else:
        ax = _line_baseline.axes
        _line_baseline.set_data(xs, baseline)
        _line_actual.set_data(xs, actual)
        ax.set_xlim(0, max(xs[-1], 1))

    ymin = min(baseline.min(), actual.min())
    ymax = max(baseline.max(), actual.max())
    if ymin != ymax:
        padding = max((ymax - ymin) * 0.1, 0.01)
        ax = _line_baseline.axes
        ax.set_ylim(ymin - padding, ymax + padding)

    _figure.canvas.draw()
    _figure.canvas.flush_events()
    return _line_baseline, _line_actual


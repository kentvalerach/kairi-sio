# KAIRI-SIO - Configuracion de Sensores y Umbrales
# NOTA: Las API keys van en .env, nunca aqui

EMBALSES = {
    "E32_VADOMOJON": {
        "H_min": 0.0, "H_max": 100.0,
        "Q_min": 0.0, "Q_max": 5000.0,
        "P_min": 0.0, "P_max": 300.0,
    },
    "E33_SRRA_BOYERA": {
        "H_min": 0.0, "H_max": 100.0,
        "Q_min": 0.0, "Q_max": 5000.0,
        "P_min": 0.0, "P_max": 300.0,
    },
    "E37_BEMBEZAR": {
        "H_min": 0.0, "H_max": 100.0,
        "Q_min": 0.0, "Q_max": 5000.0,
        "P_min": 0.0, "P_max": 300.0,
    },
}

WEIGHTS = {"w_f": 0.40, "w_l": 0.30, "w_t": 0.20, "w_h": 0.10}

THRESHOLDS = {
    "CERTIFICADA": 0.85,
    "DEGRADADA":   0.50,
}

# ── Latencia por confederación ─────────────────────────────────────────────────
# LAT_CRITICAL_S: umbral en segundos a partir del cual L(lat) = 0.1
# Fundamentado: intervalo nominal de transmisión SAIH (TEC_Formulas v1.1 §4)
# Estructura: breakpoints [t1, t2, LAT_CRITICAL_S] con penalizaciones [1.0, 0.7, 0.4, 0.1]
#
# Para añadir una confederación nueva, copiar el bloque y ajustar LAT_CRITICAL_S
# según el intervalo de transmisión nominal documentado por la confederación.

LATENCY_DEFAULTS = {
    "lat_breakpoints_s": [60, 300, 900],   # [t1, t2, LAT_CRITICAL_S]
    "lat_scores":        [1.0, 0.7, 0.4, 0.1],
}

LATENCY_BY_CONFEDERATION = {
    # Guadalquivir — intervalo nominal 900s (fuente: SAIH CHG)
    "CHG": {
        "lat_breakpoints_s": [60, 300, 900],
        "lat_scores":        [1.0, 0.7, 0.4, 0.1],
    },
    # Ebro — placeholder; actualizar con intervalo nominal CHE
    "CHE": {
        "lat_breakpoints_s": [60, 300, 900],
        "lat_scores":        [1.0, 0.7, 0.4, 0.1],
    },
    # Tajo — placeholder; actualizar con intervalo nominal CHT
    "CHT": {
        "lat_breakpoints_s": [60, 300, 900],
        "lat_scores":        [1.0, 0.7, 0.4, 0.1],
    },
    # Duero — placeholder; actualizar con intervalo nominal CHD
    "CHD": {
        "lat_breakpoints_s": [60, 300, 900],
        "lat_scores":        [1.0, 0.7, 0.4, 0.1],
    },
}


def get_latency_config(confederation: str | None = None) -> dict:
    """
    Return latency breakpoints and scores for a confederation.

    Falls back to LATENCY_DEFAULTS if confederation is None or unknown.

    Parameters
    ----------
    confederation : str or None
        Confederation code, e.g. 'CHG', 'CHE', 'CHT', 'CHD'.

    Returns
    -------
    dict with keys:
        'lat_breakpoints_s' : list[int]  — [t1, t2, LAT_CRITICAL_S] in seconds
        'lat_scores'        : list[float] — [score_0, score_1, score_2, score_3]
        'lat_critical_s'    : int        — convenience: breakpoints[-1]
        'confederation'     : str        — resolved confederation code or 'DEFAULT'
    """
    if confederation and confederation.upper() in LATENCY_BY_CONFEDERATION:
        cfg = LATENCY_BY_CONFEDERATION[confederation.upper()].copy()
        cfg["confederation"] = confederation.upper()
    else:
        cfg = LATENCY_DEFAULTS.copy()
        cfg["confederation"] = "DEFAULT"

    cfg["lat_critical_s"] = cfg["lat_breakpoints_s"][-1]
    return cfg

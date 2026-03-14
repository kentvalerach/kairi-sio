"""
KAIRI-SIO — src/ingestion/aemet_connector.py
Conector AEMET OpenData REST API.

Obtiene precipitación y avisos meteorológicos para las estaciones
más cercanas a los embalses monitorizados (CHG y CHE).

AEMET API quirk: todas las peticiones requieren DOS llamadas:
  1ª → devuelve {datos: "https://..."} con la URL real
  2ª → devuelve los datos JSON

Rate limit: 50 requests/minuto.

Variables obtenidas:
  - Observación horaria: precipitación, temperatura, viento
  - Avisos CAP activos: nivel rojo/naranja por zona

Uso:
  python src/ingestion/aemet_connector.py --mode obs --embalse ITOIZ
  python src/ingestion/aemet_connector.py --mode avisos
  python src/ingestion/aemet_connector.py --mode all

Variables de entorno requeridas (.env):
  AEMET_API_KEY=tu_api_key
"""

import os
import time
import logging
import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Configuración ─────────────────────────────────────────────────────────────
BASE_URL  = "https://opendata.aemet.es/opendata"
API_KEY   = os.getenv("AEMET_API_KEY", "")
RATE_LIMIT_DELAY = 2.0   # segundos entre peticiones (50 req/min = 1.2s mínimo)

ROOT     = Path(__file__).resolve().parents[2]
OUT_DIR  = ROOT / "data" / "raw" / "aemet"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ── Estaciones AEMET más cercanas por embalse ─────────────────────────────────
# Fuente: inventario AEMET filtrado por proximidad geográfica
# Pendiente: validar con AEMET /api/valores/climatologicos/inventarioestaciones
ESTACIONES_POR_EMBALSE = {
    # CHG — Guadalquivir
    "E32_VADOMOJON":   {"id": "5402", "nombre": "Córdoba Aeropuerto",     "dist_km": 25},
    "E33_SRRA_BOYERA": {"id": "5402", "nombre": "Córdoba Aeropuerto",     "dist_km": 30},
    "E37_BEMBEZAR":    {"id": "5402", "nombre": "Córdoba Aeropuerto",     "dist_km": 20},
    # CHE — Ebro
    "ITOIZ":           {"id": "9263D", "nombre": "Pamplona/Noain",        "dist_km": 35},
    "MEQUINENZA":      {"id": "9390",  "nombre": "Zaragoza Aeropuerto",   "dist_km": 45},
    "YESA":            {"id": "9263D", "nombre": "Pamplona/Noain",        "dist_km": 40},
}

# Zonas de aviso CAP por confederación
ZONAS_AVISO = {
    "CHG": ["AND01", "AND02", "AND03"],   # Andalucía cuenca alta/media/baja
    "CHE": ["ARA01", "NAV01"],            # Aragón, Navarra
}


class AEMETConnector:
    """Cliente AEMET OpenData con manejo automático de la doble llamada."""

    def __init__(self, api_key: str = ""):
        self.api_key  = api_key or API_KEY
        self.session  = requests.Session()
        self.session.headers.update({
            "api_key":    self.api_key,
            "Accept":     "application/json",
            "cache-control": "no-cache",
        })
        if not self.api_key:
            log.warning("AEMET_API_KEY no configurada. Establécela en .env")

    def _get(self, endpoint: str) -> Optional[dict]:
        """Primera llamada — devuelve metadata con URL de datos."""
        url = f"{BASE_URL}{endpoint}"
        try:
            r = self.session.get(url, timeout=15)
            r.raise_for_status()
            return r.json()
        except requests.exceptions.HTTPError as e:
            log.error(f"HTTP {r.status_code} en {endpoint}: {e}")
            return None
        except Exception as e:
            log.error(f"Error en {endpoint}: {e}")
            return None

    def _get_datos(self, datos_url: str) -> Optional[list]:
        """Segunda llamada — obtiene los datos reales desde la URL devuelta."""
        try:
            time.sleep(RATE_LIMIT_DELAY)
            r = self.session.get(datos_url, timeout=30)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            log.error(f"Error obteniendo datos de {datos_url}: {e}")
            return None

    def fetch(self, endpoint: str) -> Optional[list]:
        """
        Ejecuta la doble llamada AEMET y devuelve los datos.
        Retorna None si algún paso falla.
        """
        meta = self._get(endpoint)
        if not meta:
            return None

        estado = meta.get("estado", 0)
        if estado != 200:
            descripcion = meta.get("descripcion", "sin descripción")
            log.warning(f"AEMET estado={estado}: {descripcion}")
            return None

        datos_url = meta.get("datos")
        if not datos_url:
            log.error(f"No hay URL de datos en respuesta: {meta}")
            return None

        time.sleep(RATE_LIMIT_DELAY)
        datos = self._get_datos(datos_url)
        return datos

    # ── Endpoints específicos ─────────────────────────────────────────────────

    def get_observacion_estacion(self, estacion_id: str) -> Optional[list]:
        """Observación convencional actual de una estación."""
        endpoint = f"/api/observacion/convencional/datos/estacion/{estacion_id}"
        log.info(f"  Obteniendo observación estación {estacion_id}...")
        return self.fetch(endpoint)

    def get_observacion_todas(self) -> Optional[list]:
        """Observación convencional actual de todas las estaciones."""
        log.info("  Obteniendo observación todas las estaciones...")
        return self.fetch("/api/observacion/convencional/todas")

    def get_avisos_activos(self) -> Optional[list]:
        """Avisos CAP últimos elaborados."""
        log.info("  Obteniendo avisos CAP activos...")
        return self.fetch("/api/avisos_cap/ultimoelaborado/area/terrestre")

    def get_climatologia_diaria(
        self,
        estacion_id: str,
        fecha_ini: str,
        fecha_fin: str,
    ) -> Optional[list]:
        """
        Climatología diaria para una estación y rango de fechas.
        Fechas en formato: YYYY-MM-DDTHH:MM:SSUTC
        """
        endpoint = (
            f"/api/valores/climatologicos/diarios/datos"
            f"/fechaini/{fecha_ini}/fechafin/{fecha_fin}"
            f"/estacion/{estacion_id}"
        )
        log.info(f"  Climatología diaria {estacion_id} [{fecha_ini} → {fecha_fin}]...")
        return self.fetch(endpoint)

    def get_inventario_estaciones(self) -> Optional[list]:
        """Inventario completo de estaciones AEMET."""
        log.info("  Obteniendo inventario de estaciones...")
        return self.fetch("/api/valores/climatologicos/inventarioestaciones/todasestaciones")


# ── Funciones de alto nivel ───────────────────────────────────────────────────

def fetch_obs_embalse(connector: AEMETConnector, embalse_id: str) -> dict:
    """
    Obtiene la observación actual de la estación más cercana a un embalse.
    Devuelve dict con los campos relevantes para KAIRI-SIO.
    """
    est_cfg = ESTACIONES_POR_EMBALSE.get(embalse_id)
    if not est_cfg:
        log.warning(f"No hay estación configurada para {embalse_id}")
        return {}

    est_id   = est_cfg["id"]
    est_nombre = est_cfg["nombre"]
    log.info(f"  {embalse_id} → estación {est_id} ({est_nombre}, ~{est_cfg['dist_km']}km)")

    datos = connector.get_observacion_estacion(est_id)
    if not datos:
        return {}

    # Tomar la observación más reciente
    obs = datos[-1] if isinstance(datos, list) else datos

    result = {
        "embalse_id":   embalse_id,
        "estacion_id":  est_id,
        "estacion":     est_nombre,
        "ts_aemet":     obs.get("fint", ""),
        "precip_mm":    _safe_float(obs.get("prec", obs.get("precipitacion", None))),
        "temp_c":       _safe_float(obs.get("ta",   obs.get("temperatura",   None))),
        "viento_ms":    _safe_float(obs.get("vv",   obs.get("viento",        None))),
        "humedad_pct":  _safe_float(obs.get("hr",   obs.get("humedad",       None))),
        "ts_fetch":     datetime.now(timezone.utc).isoformat(),
    }
    return result


def fetch_avisos(connector: AEMETConnector) -> list:
    """
    Obtiene avisos activos y filtra los relevantes para CHG/CHE.
    Retorna lista de avisos con nivel >= amarillo.
    """
    datos = connector.get_avisos_activos()
    if not datos:
        return []

    zonas_interes = set()
    for zonas in ZONAS_AVISO.values():
        zonas_interes.update(zonas)

    avisos_relevantes = []
    if isinstance(datos, list):
        for aviso in datos:
            zona = aviso.get("area", aviso.get("zona", ""))
            nivel = aviso.get("nivel", aviso.get("severity", "")).upper()
            if any(z in str(zona) for z in zonas_interes) or nivel in ("RED", "ORANGE", "ROJO", "NARANJA"):
                avisos_relevantes.append({
                    "zona":      zona,
                    "nivel":     nivel,
                    "tipo":      aviso.get("event", aviso.get("tipo", "")),
                    "inicio":    aviso.get("onset",   ""),
                    "fin":       aviso.get("expires", ""),
                    "descripcion": aviso.get("description", aviso.get("descripcion", "")),
                })

    log.info(f"  Avisos relevantes encontrados: {len(avisos_relevantes)}")
    return avisos_relevantes


def _safe_float(val) -> Optional[float]:
    """Convierte a float de forma segura, retorna None si falla."""
    if val is None:
        return None
    try:
        return float(str(val).replace(",", "."))
    except (ValueError, TypeError):
        return None


def run_obs_all(connector: AEMETConnector) -> list:
    """Obtiene observaciones para todos los embalses configurados."""
    results = []
    for embalse_id in ESTACIONES_POR_EMBALSE:
        obs = fetch_obs_embalse(connector, embalse_id)
        if obs:
            results.append(obs)
        time.sleep(RATE_LIMIT_DELAY)
    return results


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="KAIRI-SIO — Conector AEMET OpenData")
    parser.add_argument(
        "--mode",
        choices=["obs", "avisos", "all", "inventario"],
        default="all",
        help="Modo de operación",
    )
    parser.add_argument(
        "--embalse",
        type=str,
        default=None,
        help="Embalse específico (solo para --mode obs)",
    )
    args = parser.parse_args()

    if not API_KEY:
        log.error("AEMET_API_KEY no encontrada en .env")
        log.error("  → Añade: AEMET_API_KEY=tu_clave en C:\\KAIRI-SIO\\.env")
        return

    connector = AEMETConnector()
    log.info(f"KAIRI-SIO — AEMET Connector · modo={args.mode}")

    if args.mode in ("obs", "all"):
        log.info("\n── Observaciones ────────────────────────────")
        if args.embalse:
            results = [fetch_obs_embalse(connector, args.embalse)]
        else:
            results = run_obs_all(connector)

        if results:
            print("\nOBSERVACIONES AEMET:")
            print(f"{'Embalse':<20} {'Estación':<25} {'Precip':>8} {'Temp':>7} {'Viento':>8}")
            print(f"{'─'*20} {'─'*25} {'─'*8} {'─'*7} {'─'*8}")
            for r in results:
                if r:
                    prec = f"{r['precip_mm']:.1f}mm" if r['precip_mm'] is not None else "  N/A"
                    temp = f"{r['temp_c']:.1f}°C"    if r['temp_c']    is not None else "  N/A"
                    vien = f"{r['viento_ms']:.1f}m/s" if r['viento_ms'] is not None else "   N/A"
                    print(f"{r['embalse_id']:<20} {r['estacion']:<25} {prec:>8} {temp:>7} {vien:>8}")

    if args.mode in ("avisos", "all"):
        log.info("\n── Avisos CAP ───────────────────────────────")
        avisos = fetch_avisos(connector)
        if avisos:
            print("\nAVISOS ACTIVOS:")
            for a in avisos:
                print(f"  [{a['nivel']}] {a['zona']} — {a['tipo']} ({a['inicio']} → {a['fin']})")
        else:
            print("\n  ✅ Sin avisos activos en zonas CHG/CHE")

    if args.mode == "inventario":
        log.info("\n── Inventario estaciones ────────────────────")
        inv = connector.get_inventario_estaciones()
        if inv:
            print(f"\n  Total estaciones AEMET: {len(inv)}")
            # Mostrar estaciones en Andalucía y Aragón/Navarra
            for est in inv[:5]:
                print(f"  {est.get('indicativo','?')} — {est.get('nombre','?')} ({est.get('provincia','?')})")
            print("  ...")


if __name__ == "__main__":
    main()
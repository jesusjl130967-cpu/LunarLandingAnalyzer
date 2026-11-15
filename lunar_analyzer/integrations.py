"""Optional NASA data integrations with explicit local-model fallbacks."""

from __future__ import annotations

import json
import os
import re
import socket
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from math import acos, asin, atan2, degrees, isfinite, sqrt
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen

from lunar_analyzer.science import (
    ASTRONOMICAL_UNIT_KM,
    SOLAR_CONSTANT,
    _clamp,
    _normalize,
    _dot,
    icrf_vector_to_lunar_frame_approx,
    solar_ephemeris,
)

HORIZONS_URL = "https://ssd.jpl.nasa.gov/api/horizons.api"
ODE_URL = "https://oderest.rsl.wustl.edu/live2"
REQUEST_TIMEOUT_SECONDS = 8
MAX_RESPONSE_BYTES = 2_000_000
SPICE_META_KERNEL_ENV = "LUNAR_SPICE_META_KERNEL"


class IntegrationError(RuntimeError):
    """A NASA endpoint or local SPICE configuration could not be used."""


def _get_json(base_url, parameters, timeout=REQUEST_TIMEOUT_SECONDS):
    url = f"{base_url}?{urlencode(parameters)}"
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "LunarLandingAnalyzer/1.0"})
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = response.read(MAX_RESPONSE_BYTES + 1)
    except HTTPError as error:
        error.close()
        raise IntegrationError(f"El servicio respondió HTTP {error.code}.") from error
    except (URLError, TimeoutError, socket.timeout) as error:
        raise IntegrationError(f"No se pudo conectar con el servicio: {error.reason if isinstance(error, URLError) else error}.") from error
    if len(payload) > MAX_RESPONSE_BYTES:
        raise IntegrationError("La respuesta del servicio supera el límite de 2 MB.")
    try:
        data = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise IntegrationError("El servicio devolvió una respuesta JSON no válida.") from error
    if not isinstance(data, dict):
        raise IntegrationError("El servicio devolvió una respuesta JSON con formato inesperado.")
    return data


def _parse_horizons_vector(response):
    if response.get("error"):
        raise IntegrationError(f"JPL Horizons: {response['error']}")
    text = response.get("result", "")
    values = []
    for axis in "XYZ":
        match = re.search(
            rf"\b{axis}\s*=\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][-+]?\d+)?)",
            text,
        )
        if match is None:
            raise IntegrationError("JPL Horizons no devolvió los tres componentes de posición.")
        try:
            values.append(float(match.group(1).replace("D", "E").replace("d", "e")))
        except ValueError as error:
            raise IntegrationError("JPL Horizons devolvió un componente de posición no numérico.") from error
    return tuple(values)


def _horizons_vector(target, when):
    response = _get_json(
        HORIZONS_URL,
        {
            "format": "json",
            "COMMAND": target,
            "OBJ_DATA": "NO",
            "MAKE_EPHEM": "YES",
            "EPHEM_TYPE": "VECTORS",
            "CENTER": "500@301",
            "TLIST": f"'{when.strftime('%Y-%b-%d %H:%M:%S')}'",
            "TLIST_TYPE": "CAL",
            "TIME_TYPE": "UT",
            "REF_SYSTEM": "ICRF",
            "REF_PLANE": "FRAME",
            "OUT_UNITS": "KM-S",
            "VEC_TABLE": "2",
            "VEC_LABELS": "YES",
        },
    )
    return _parse_horizons_vector(response)


def _solar_from_vectors(base, when, sun_vector, earth_vector, source, spice=False):
    distance_km = sqrt(_dot(sun_vector, sun_vector))
    if distance_km <= 0 or sqrt(_dot(earth_vector, earth_vector)) <= 0:
        raise IntegrationError("El servicio devolvió un vector de posición nulo.")
    if spice:
        # IAU_MOON components are x=0° longitude, y=east, z=north.
        sun_lunar_raw = (sun_vector[1], sun_vector[2], sun_vector[0])
        earth_lunar_raw = (earth_vector[1], earth_vector[2], earth_vector[0])
    else:
        sun_lunar_raw = icrf_vector_to_lunar_frame_approx(when, sun_vector)
        earth_lunar_raw = icrf_vector_to_lunar_frame_approx(when, earth_vector)
    sun_lunar = _normalize(sun_lunar_raw)
    earth_lunar = _normalize(earth_lunar_raw)
    phase_cosine = _clamp(_dot(sun_lunar, earth_lunar))
    distance_au = distance_km / ASTRONOMICAL_UNIT_KM
    irradiance = SOLAR_CONSTANT / distance_au**2
    return {
        **base,
        "sun_vector_lunar": [round(value, 10) for value in sun_lunar],
        "earth_vector_lunar": [round(value, 10) for value in earth_lunar],
        "subsolar_latitude_deg": round(degrees(asin(_clamp(sun_lunar[1]))), 4),
        "subsolar_longitude_deg": round(degrees(atan2(sun_lunar[0], sun_lunar[2])), 4),
        "subearth_latitude_deg": round(degrees(asin(_clamp(earth_lunar[1]))), 4),
        "subearth_longitude_deg": round(degrees(atan2(earth_lunar[0], earth_lunar[2])), 4),
        "sun_moon_distance_km": round(distance_km, 1),
        "sun_moon_distance_au": round(distance_au, 10),
        "solar_irradiance_w_m2": round(irradiance, 3),
        "phase_angle_deg": round(degrees(acos(phase_cosine)), 4),
        "ephemeris_model": source,
        "topographic_shadows_available": False,
    }


_loaded_meta_kernel = None


def _spice_vectors(when):
    meta_kernel = os.environ.get(SPICE_META_KERNEL_ENV, "").strip()
    if not meta_kernel:
        raise IntegrationError(f"No hay kernels SPICE locales configurados ({SPICE_META_KERNEL_ENV}).")
    meta_kernel_path = Path(meta_kernel).expanduser().resolve()
    if not meta_kernel_path.is_file():
        raise IntegrationError(f"No se encontró el meta-kernel SPICE indicado: {meta_kernel_path}")
    try:
        import spiceypy
    except ImportError as error:
        raise IntegrationError("SpiceyPy no está instalado; instala las dependencias del proyecto.") from error

    global _loaded_meta_kernel
    if _loaded_meta_kernel != str(meta_kernel_path):
        spiceypy.kclear()
        try:
            spiceypy.furnsh(str(meta_kernel_path))
        except spiceypy.utils.exceptions.SpiceyError as error:
            raise IntegrationError(f"No se pudieron cargar los kernels SPICE: {error}") from error
        _loaded_meta_kernel = str(meta_kernel_path)
    try:
        et = spiceypy.str2et(when.strftime("%Y-%m-%dT%H:%M:%S UTC"))
        sun_vector = spiceypy.spkezr("SUN", et, "IAU_MOON", "NONE", "MOON")[0][:3]
        earth_vector = spiceypy.spkezr("EARTH", et, "IAU_MOON", "NONE", "MOON")[0][:3]
    except spiceypy.utils.exceptions.SpiceyError as error:
        raise IntegrationError(f"Los kernels SPICE no cubren la fecha o los marcos requeridos: {error}") from error
    return tuple(sun_vector), tuple(earth_vector)


@lru_cache(maxsize=128)
def _resolve_ephemeris(when_iso):
    from datetime import datetime

    when = datetime.fromisoformat(when_iso)
    solar = solar_ephemeris(when)
    integrations = {
        "horizons": {
            "available": False,
            "source": "JPL Horizons API",
            "message": "No se consultó todavía.",
        },
        "spice": {
            "available": False,
            "source": "NASA NAIF/SPICE",
            "message": "No se configuró un meta-kernel local.",
            "meta_kernel_configured": bool(os.environ.get(SPICE_META_KERNEL_ENV, "").strip()),
        },
        "pds": {
            "available": None,
            "source": "PDS Geosciences Node ODE REST",
            "message": "Búsqueda bajo demanda; requiere internet y no descarga ni procesa productos.",
        },
    }
    try:
        sun_vector = _horizons_vector("10", when)
        earth_vector = _horizons_vector("399", when)
        solar = _solar_from_vectors(
            solar,
            when,
            sun_vector,
            earth_vector,
            "JPL Horizons ICRF, proyectado al marco lunar síncrono aproximado (sin SPICE)",
        )
        integrations["horizons"] = {
            "available": True,
            "source": "JPL Horizons API",
            "message": "Vectores Sol/Tierra respecto a la Luna consultados para esta fecha.",
        }
    except IntegrationError as error:
        integrations["horizons"]["message"] = f"No disponible: {error} Se usa el modelo analítico local."

    if integrations["spice"]["meta_kernel_configured"]:
        try:
            sun_vector, earth_vector = _spice_vectors(when)
            solar = _solar_from_vectors(
                solar,
                when,
                sun_vector,
                earth_vector,
                "NASA SPICE con kernels locales; marco IAU_MOON",
                spice=True,
            )
            integrations["spice"] = {
                "available": True,
                "source": "NASA NAIF/SPICE",
                "message": "Vectores calculados con los kernels locales en el marco IAU_MOON.",
                "meta_kernel_configured": True,
            }
        except IntegrationError as error:
            integrations["spice"]["message"] = f"No disponible: {error} Se conserva la mejor efeméride disponible."
    else:
        integrations["spice"]["message"] = (
            f"No configurado. Define {SPICE_META_KERNEL_ENV} con la ruta a un meta-kernel local."
        )

    if not integrations["spice"]["available"] and not integrations["horizons"]["available"]:
        solar["ephemeris_model"] = "Modelo kepleriano analítico local de baja precisión (fallback sin conexión)"
    return solar, integrations


def resolve_ephemeris(when):
    """Return date-specific solar data and a user-visible status for each integration."""
    when_iso = when.isoformat()
    solar, integrations = _resolve_ephemeris(when_iso)
    return dict(solar), json.loads(json.dumps(integrations))


def integration_status():
    return {
        "horizons": {
            "source": "JPL Horizons API",
            "available": None,
            "message": "Se consulta al calcular una evaluación; requiere conexión a internet.",
        },
        "pds": {
            "source": "PDS Geosciences Node ODE REST",
            "available": None,
            "message": "Búsqueda de metadatos bajo demanda; requiere internet y no descarga datos.",
        },
        "spice": {
            "source": "NASA NAIF/SPICE",
            "available": False,
            "meta_kernel_configured": bool(os.environ.get(SPICE_META_KERNEL_ENV, "").strip()),
            "message": (
                "Configurado localmente; se comprobará al calcular."
                if os.environ.get(SPICE_META_KERNEL_ENV, "").strip()
                else f"Define {SPICE_META_KERNEL_ENV} para usar kernels locales."
            ),
        },
    }


def _normalise_products(response):
    if not isinstance(response, dict):
        raise IntegrationError("PDS ODE devolvió metadatos con formato inesperado.")
    results = response.get("ODEResults", {})
    if not isinstance(results, dict):
        raise IntegrationError("PDS ODE devolvió metadatos con formato inesperado.")
    if results.get("Status") == "ERROR" or results.get("Error"):
        raise IntegrationError(results.get("Error", "PDS ODE devolvió un error."))
    products = results.get("Products", {}).get("Product", [])
    if isinstance(products, dict):
        products = [products]
    return results, products if isinstance(products, list) else []


def _product_identifier(product):
    for key in ("ProductId", "ODEID", "PDSId"):
        if product.get(key):
            return str(product[key])
    for key in ("ProductURL", "FilesURL", "LabelURL"):
        query = parse_qs(urlparse(product.get(key, "")).query)
        for parameter in ("product_id", "odeid", "pdsid"):
            if query.get(parameter):
                return query[parameter][0]
    return "Producto LRO"


def search_lro_products(latitude, longitude):
    """Search Diviner and LOLA product metadata intersecting a small coordinate box."""
    if not isfinite(latitude) or not isfinite(longitude) or not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise ValueError("Las coordenadas deben estar dentro de los límites lunares.")
    span = 0.1
    west = max(-180.0, longitude - span)
    east = min(180.0, longitude + span)
    min_lat = max(-90.0, latitude - span)
    max_lat = min(90.0, latitude + span)
    instruments = (
        ("Diviner", "DLRE", "RDR4"),
        ("LOLA", "LOLA", "RDR4"),
    )
    def search_instrument(instrument):
        name, instrument_id, product_type = instrument
        try:
            response = _get_json(
                ODE_URL,
                {
                    "target": "moon",
                    "query": "products",
                    "results": "cm",
                    "output": "JSON",
                    "ihid": "LRO",
                    "iid": instrument_id,
                    "pt": product_type,
                    "minlat": f"{min_lat:.4f}",
                    "maxlat": f"{max_lat:.4f}",
                    "westernlon": f"{west:.4f}",
                    "easternlon": f"{east:.4f}",
                    "loc": "b",
                    "limit": "10",
                },
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            metadata, products = _normalise_products(response)
            return {
                "instrument": name,
                "available": True,
                "count": metadata.get("Count", len(products)),
                "products": [
                    {
                        "product_id": _product_identifier(item),
                        "observation_time": item.get("Observation_time", ""),
                        "description": item.get("Description", ""),
                        "product_url": item.get("ProductURL", ""),
                        "files_url": item.get("FilesURL", ""),
                        "label_url": item.get("LabelURL", ""),
                    }
                    for item in products[:10]
                ],
                "message": "Metadatos y enlaces; los productos no se descargaron ni procesaron.",
            }
        except IntegrationError as error:
            return {
                "instrument": name,
                "available": False,
                "count": 0,
                "products": [],
                "message": f"No se pudo consultar ODE: {error}",
            }

    with ThreadPoolExecutor(max_workers=2) as executor:
        result = list(executor.map(search_instrument, instruments))
    return {
        "source": ODE_URL,
        "search_area": {
            "latitude_min": round(min_lat, 4),
            "latitude_max": round(max_lat, 4),
            "longitude_west": round(west, 4),
            "longitude_east": round(east, 4),
        },
        "results": result,
        "limitations": "Resultados de catálogo por cobertura geográfica; no son observaciones validadas ni datos descargados.",
    }

"""Modelos orbitales y radiativos para cribado preliminar.

Las efemérides externas y los kernels SPICE son opcionales; el modelo analítico es el respaldo.
Este módulo no sustituye datos LRO/Diviner ni una evaluación de ingeniería.
"""

from datetime import timedelta, timezone
from math import acos, asin, atan2, cos, degrees, hypot, radians, sin, sqrt

SOLAR_CONSTANT = 1361.0
ASTRONOMICAL_UNIT_KM = 149_597_870.7
EARTH_RADIUS_KM = 6378.137
STEFAN_BOLTZMANN = 5.670374419e-8
LUNAR_ORBIT_INCLINATION_DEG = 5.145
LUNAR_AXIAL_OBLIQUITY_DEG = 1.542
LIMITATIONS = [
    "Horizons puede proporcionar vectores para el instante evaluado; sin kernels SPICE, la proyección al marco lunar sigue siendo aproximada.",
    "Los perfiles de 72 horas y el cribado de 30 días usan el modelo analítico local, incluso cuando hay efemérides externas para el instante seleccionado.",
    "Irradiancia: constante solar escalada por la distancia calculada Sol-Luna; no modela actividad solar ni eclipses.",
    "Iluminación: incidencia N·S sobre una esfera; no incorpora pendiente orientada, horizonte ni sombras de relieve porque no se incluye un DEM validado.",
    "Temperaturas: equilibrio radiativo local con propiedades de catálogo/demo; no son observaciones ni productos de LRO Diviner.",
    "Comunicación: visibilidad geométrica aproximada de la Tierra; no modela antenas, enlace RF, obstáculos ni satélites relay.",
    "Terreno y ciencia: pendientes/rasgos del catálogo son referencias demostrativas; no equivalen a un DEM validado ni confirman hielo.",
    "El indicador de viabilidad es orientativo y no es una certificación ni recomendación oficial de NASA.",
]


def _clamp(value, lower=-1.0, upper=1.0):
    return max(lower, min(upper, value))


def _normalize(vector):
    length = sqrt(sum(component * component for component in vector))
    if length == 0:
        raise ValueError("No se puede normalizar un vector nulo.")
    return tuple(component / length for component in vector)


def _dot(left, right):
    return sum(a * b for a, b in zip(left, right))


def _cross(left, right):
    return (
        left[1] * right[2] - left[2] * right[1],
        left[2] * right[0] - left[0] * right[2],
        left[0] * right[1] - left[1] * right[0],
    )


def _julian_day(when):
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when.astimezone(timezone.utc).timestamp() / 86400.0 + 2440587.5


def _sun_position_ecliptic_au(julian_day):
    """Approximate geocentric Sun vector in the mean ecliptic of date."""
    centuries = (julian_day - 2451545.0) / 36525.0
    mean_longitude = (280.46646 + 36000.76983 * centuries + 0.0003032 * centuries**2) % 360.0
    mean_anomaly = (357.52911 + 35999.05029 * centuries - 0.0001537 * centuries**2) % 360.0
    eccentricity = 0.016708634 - 0.000042037 * centuries - 0.0000001267 * centuries**2
    anomaly = radians(mean_anomaly)
    equation_of_center = (
        (1.914602 - 0.004817 * centuries - 0.000014 * centuries**2) * sin(anomaly)
        + (0.019993 - 0.000101 * centuries) * sin(2 * anomaly)
        + 0.000289 * sin(3 * anomaly)
    )
    true_longitude = radians(mean_longitude + equation_of_center)
    true_anomaly = radians(mean_anomaly + equation_of_center)
    distance_au = 1.000001018 * (1 - eccentricity**2) / (1 + eccentricity * cos(true_anomaly))
    return (
        distance_au * cos(true_longitude),
        distance_au * sin(true_longitude),
        0.0,
    ), mean_longitude, mean_anomaly


def _moon_position_ecliptic_km(julian_day, sun_mean_longitude, sun_mean_anomaly):
    """Low-precision lunar orbit plus principal longitude/latitude perturbations."""
    days = julian_day - 2451543.5
    node_deg = (125.1228 - 0.0529538083 * days) % 360.0
    inclination = radians(LUNAR_ORBIT_INCLINATION_DEG)
    periapsis_deg = (318.0634 + 0.1643573223 * days) % 360.0
    semi_major_axis_earth_radii = 60.2666
    eccentricity = 0.054900
    mean_anomaly_deg = (115.3654 + 13.0649929509 * days) % 360.0
    mean_anomaly = radians(mean_anomaly_deg)
    eccentric_anomaly = mean_anomaly
    for _ in range(5):
        eccentric_anomaly -= (
            eccentric_anomaly - eccentricity * sin(eccentric_anomaly) - mean_anomaly
        ) / (1 - eccentricity * cos(eccentric_anomaly))

    orbital_x = semi_major_axis_earth_radii * (cos(eccentric_anomaly) - eccentricity)
    orbital_y = semi_major_axis_earth_radii * sqrt(1 - eccentricity**2) * sin(eccentric_anomaly)
    radius_earth_radii = hypot(orbital_x, orbital_y)
    true_anomaly = atan2(orbital_y, orbital_x)
    node = radians(node_deg)
    argument = true_anomaly + radians(periapsis_deg)
    x = radius_earth_radii * (cos(node) * cos(argument) - sin(node) * sin(argument) * cos(inclination))
    y = radius_earth_radii * (sin(node) * cos(argument) + cos(node) * sin(argument) * cos(inclination))
    z = radius_earth_radii * sin(argument) * sin(inclination)
    base_longitude = atan2(y, x)
    base_latitude = atan2(z, hypot(x, y))

    mean_lunar_longitude = node_deg + periapsis_deg + mean_anomaly_deg
    elongation = radians(mean_lunar_longitude - sun_mean_longitude)
    argument_latitude = radians(mean_lunar_longitude - node_deg)
    moon_anomaly = radians(mean_anomaly_deg)
    sun_anomaly = radians(sun_mean_anomaly)
    longitude_correction = (
        -1.274 * sin(moon_anomaly - 2 * elongation)
        + 0.658 * sin(2 * elongation)
        - 0.186 * sin(sun_anomaly)
        - 0.059 * sin(2 * moon_anomaly - 2 * elongation)
        - 0.057 * sin(moon_anomaly - 2 * elongation + sun_anomaly)
        + 0.053 * sin(moon_anomaly + 2 * elongation)
        + 0.046 * sin(2 * elongation - sun_anomaly)
        + 0.041 * sin(moon_anomaly - sun_anomaly)
        - 0.035 * sin(elongation)
        - 0.031 * sin(moon_anomaly + sun_anomaly)
        - 0.015 * sin(2 * argument_latitude - 2 * elongation)
        + 0.011 * sin(moon_anomaly - 4 * elongation)
    )
    latitude_correction = (
        -0.173 * sin(argument_latitude - 2 * elongation)
        - 0.055 * sin(moon_anomaly - argument_latitude - 2 * elongation)
        - 0.046 * sin(moon_anomaly + argument_latitude - 2 * elongation)
        + 0.033 * sin(argument_latitude + 2 * elongation)
        + 0.017 * sin(2 * moon_anomaly + argument_latitude)
    )
    longitude = base_longitude + radians(longitude_correction)
    latitude = base_latitude + radians(latitude_correction)
    distance_km = radius_earth_radii * EARTH_RADIUS_KM
    position = (
        distance_km * cos(latitude) * cos(longitude),
        distance_km * cos(latitude) * sin(longitude),
        distance_km * sin(latitude),
    )
    return position, node, inclination


def _lunar_frame_basis(moon_position_km, ascending_node, inclination):
    """Approximate east, north, and prime-meridian axes in ecliptic coordinates."""
    orbital_normal = _normalize(
        (
            sin(ascending_node) * sin(inclination),
            -cos(ascending_node) * sin(inclination),
            cos(inclination),
        )
    )
    ascending_node_axis = (cos(ascending_node), sin(ascending_node), 0.0)
    obliquity = radians(LUNAR_AXIAL_OBLIQUITY_DEG)
    north = _normalize(
        tuple(
            orbital_normal[index] * cos(obliquity) + ascending_node_axis[index] * sin(obliquity)
            for index in range(3)
        )
    )
    earth_direction = _normalize(tuple(-value for value in moon_position_km))
    toward_earth_equatorial = _normalize(
        tuple(earth_direction[index] - north[index] * _dot(earth_direction, north) for index in range(3))
    )
    east = _normalize(_cross(north, toward_earth_equatorial))
    return east, north, toward_earth_equatorial


def icrf_vector_to_lunar_frame_approx(when, vector):
    """Project an ICRF/J2000 position vector into the app's approximate lunar axes."""
    julian_day = _julian_day(when)
    _, sun_mean_longitude, sun_mean_anomaly = _sun_position_ecliptic_au(julian_day)
    moon_position_km, ascending_node, inclination = _moon_position_ecliptic_km(
        julian_day, sun_mean_longitude, sun_mean_anomaly
    )
    obliquity = radians(23.439291111)
    vector_ecliptic = (
        vector[0],
        vector[1] * cos(obliquity) + vector[2] * sin(obliquity),
        -vector[1] * sin(obliquity) + vector[2] * cos(obliquity),
    )
    basis = _lunar_frame_basis(moon_position_km, ascending_node, inclination)
    return tuple(_dot(vector_ecliptic, axis) for axis in basis)


def solar_ephemeris(when):
    """Return analytic Sun/Moon geometry and vectors in a synchronous lunar frame.

    Lunar-frame components are ordered east, north, and toward the mean sub-Earth
    point. This is a geometric approximation, not a SPICE/IAU precision frame.
    """
    julian_day = _julian_day(when)
    sun_position_au, sun_mean_longitude, sun_mean_anomaly = _sun_position_ecliptic_au(julian_day)
    moon_position_km, ascending_node, inclination = _moon_position_ecliptic_km(
        julian_day, sun_mean_longitude, sun_mean_anomaly
    )
    sun_position_km = tuple(value * ASTRONOMICAL_UNIT_KM for value in sun_position_au)
    sun_from_moon = tuple(sun_position_km[index] - moon_position_km[index] for index in range(3))
    sun_moon_distance_km = sqrt(_dot(sun_from_moon, sun_from_moon))
    sun_direction = _normalize(sun_from_moon)

    east, north, toward_earth_equatorial = _lunar_frame_basis(
        moon_position_km, ascending_node, inclination
    )
    earth_direction = _normalize(tuple(-value for value in moon_position_km))
    sun_lunar = (
        _dot(sun_direction, east),
        _dot(sun_direction, north),
        _dot(sun_direction, toward_earth_equatorial),
    )
    earth_lunar = (
        _dot(earth_direction, east),
        _dot(earth_direction, north),
        _dot(earth_direction, toward_earth_equatorial),
    )
    distance_au = sun_moon_distance_km / ASTRONOMICAL_UNIT_KM
    irradiance = SOLAR_CONSTANT / distance_au**2
    phase_cosine = _clamp(_dot(sun_direction, earth_direction))
    return {
        "sun_vector_lunar": [round(value, 10) for value in sun_lunar],
        "earth_vector_lunar": [round(value, 10) for value in earth_lunar],
        "subsolar_latitude_deg": round(degrees(asin(_clamp(sun_lunar[1]))), 4),
        "subsolar_longitude_deg": round(degrees(atan2(sun_lunar[0], sun_lunar[2])), 4),
        "subearth_latitude_deg": round(degrees(asin(_clamp(earth_lunar[1]))), 4),
        "subearth_longitude_deg": round(degrees(atan2(earth_lunar[0], earth_lunar[2])), 4),
        "sun_moon_distance_km": round(sun_moon_distance_km, 1),
        "sun_moon_distance_au": round(distance_au, 10),
        "solar_irradiance_w_m2": round(irradiance, 3),
        "phase_angle_deg": round(degrees(acos(phase_cosine)), 4),
        "global_illuminated_surface_percent": 50.0,
        "global_dark_surface_percent": 50.0,
        "visible_disk_illuminated_percent": round((1 + phase_cosine) * 50, 3),
        "ephemeris_model": "Kepleriano analítico de baja precisión; sin SPICE",
        "topographic_shadows_available": False,
    }


def _surface_normal(latitude, longitude):
    latitude = radians(latitude)
    longitude = radians(longitude)
    return (
        cos(latitude) * sin(longitude),
        sin(latitude),
        cos(latitude) * cos(longitude),
    )


def surface_illumination(latitude, longitude, when, ephemeris=None, albedo=0.12):
    """Evaluate local incidence N·S on a spherical, horizontal reference surface."""
    ephemeris = ephemeris or solar_ephemeris(when)
    normal = _surface_normal(latitude, longitude)
    mu = _clamp(_dot(normal, ephemeris["sun_vector_lunar"]))
    elevation = asin(mu)
    incidence = degrees(acos(mu))
    incident_flux = ephemeris["solar_irradiance_w_m2"] * max(0.0, mu)
    return {
        "mu": round(mu, 10),
        "sun_elevation_deg": round(degrees(elevation), 4),
        "incidence_angle_deg": round(incidence, 4),
        "state": "En sombra" if mu <= 0 else ("Iluminación rasante" if mu < 0.05 else "Iluminado"),
        "sunlit": mu > 0,
        "incident_irradiance_w_m2": round(incident_flux, 3),
        "reflected_flux_w_m2": round(incident_flux * albedo, 3),
        "albedo": albedo,
        "topographic_shadow": None,
        "topographic_shadow_status": "No evaluada: no se incluye un DEM validado",
    }


def sun_elevation(latitude, longitude, when):
    """Solar elevation in radians from the analytic lunar-frame Sun vector."""
    result = surface_illumination(latitude, longitude, when)
    return radians(result["sun_elevation_deg"])


def earth_elevation(latitude, longitude, when, ephemeris=None):
    """Geometric horizon estimate using the date-dependent synchronous Earth vector."""
    ephemeris = ephemeris or solar_ephemeris(when)
    cosine_separation = _clamp(_dot(_surface_normal(latitude, longitude), ephemeris["earth_vector_lunar"]))
    return asin(cosine_separation)


def thermal_balance(
    sun_altitude,
    albedo=0.12,
    emissivity=0.95,
    solar_irradiance_w_m2=SOLAR_CONSTANT,
    incidence_cosine=None,
):
    incidence = sin(sun_altitude) if incidence_cosine is None else incidence_cosine
    incident = solar_irradiance_w_m2 * max(0.0, incidence)
    absorbed = incident * (1.0 - albedo)
    equilibrium_k = (absorbed / (emissivity * STEFAN_BOLTZMANN)) ** 0.25 if absorbed > 0 else 35.0
    # Demonstration floor only; no subsurface or environmental heat sources are modeled.
    equilibrium_k = max(35.0, equilibrium_k)
    return {
        "incident_w_m2": round(incident, 2),
        "absorbed_w_m2": round(absorbed, 2),
        "emitted_w_m2": round(emissivity * STEFAN_BOLTZMANN * equilibrium_k**4, 2),
        "equilibrium_k": round(equilibrium_k, 2),
        "equilibrium_c": round(equilibrium_k - 273.15, 2),
        "temperature_k": round(equilibrium_k, 2),
        "temperature_c": round(equilibrium_k - 273.15, 2),
        "albedo": albedo,
        "emissivity": emissivity,
        "solar_irradiance_w_m2": round(solar_irradiance_w_m2, 3),
        "model": "Equilibrio radiativo instantáneo con distancia solar; piso nocturno 35 K",
    }


def illumination_summary(site, when, ephemeris=None):
    ephemeris = ephemeris or solar_ephemeris(when)
    hourly = [
        surface_illumination(site["latitude"], site["longitude"], when + timedelta(hours=index))["sunlit"]
        for index in range(24 * 30)
    ]
    daylight_hours = sum(hourly)
    local = surface_illumination(
        site["latitude"],
        site["longitude"],
        when,
        ephemeris,
        float(site.get("terrain", {}).get("albedo", 0.12)),
    )
    return {
        **local,
        "sunlight_hours_30d": round(daylight_hours, 1),
        "darkness_hours_30d": round(720 - daylight_hours, 1),
        "sample_hours": 720,
        "global_illuminated_surface_percent": ephemeris["global_illuminated_surface_percent"],
        "global_dark_surface_percent": ephemeris["global_dark_surface_percent"],
        "visible_disk_illuminated_percent": ephemeris["visible_disk_illuminated_percent"],
        "model": "N·S esférico con efemérides keplerianas analíticas; muestreo horario de 30 días",
    }


def evaluate_verdict(thermal, illumination, communication, terrain):
    favorable, risks = [], []
    if illumination["mu"] > 0:
        favorable.append("El sitio recibe luz solar en la hora seleccionada según la incidencia N·S.")
    else:
        risks.append("El punto está en oscuridad geométrica; revisar energía y supervivencia térmica.")
    if thermal["temperature_c"] < -220:
        risks.append("Temperatura de equilibrio extremadamente baja; se requiere diseño térmico específico.")
    elif thermal["temperature_c"] > 80:
        risks.append("Temperatura de equilibrio elevada; revisar carga térmica del módulo.")
    else:
        favorable.append("La temperatura instantánea estimada está dentro del intervalo de cribado (-220 a 80 °C).")
    if communication["earth_visible"]:
        favorable.append("La Tierra es geométricamente visible en la aproximación actual.")
    else:
        risks.append("La Tierra queda bajo el horizonte geométrico aproximado; considerar un relé.")
    slope = terrain["slope_deg"]
    if slope is None:
        risks.append("Pendiente y sombras del relieve no evaluables sin un DEM validado del punto.")
    elif slope <= 10:
        favorable.append("La pendiente de referencia del catálogo/demo es menor o igual a 10°.")
    else:
        risks.append("La pendiente de referencia supera 10°; los datos deben confirmarse con topografía de resolución adecuada.")
    score = len(favorable) - len(risks)
    label = "Favorable" if score >= 3 else ("Desfavorable" if score <= -2 else "Precaución")
    return {
        "label": label,
        "score": score,
        "summary": {
            "Favorable": "Los indicadores simplificados son favorables, sujetos a validación con datos de misión.",
            "Precaución": "Hay condiciones que requieren verificación científica o de ingeniería adicional.",
            "Desfavorable": "Se detectan varios factores de riesgo en este cribado preliminar.",
        }[label],
        "favorable": favorable,
        "risks": risks,
        "missing": [
            "DEM validado, pendiente orientada y horizonte topográfico",
            "mediciones Diviner coincidentes",
            "validación independiente de efemérides, marcos y kernels",
            "presupuesto de enlace y diseño térmico de misión",
        ],
    }


def analyze_site(site, when, ephemeris=None):
    ephemeris = ephemeris or solar_ephemeris(when)
    terrain_info = site.get("terrain", {})
    albedo = float(terrain_info.get("albedo", 0.12))
    illumination = illumination_summary(site, when, ephemeris)
    thermal = thermal_balance(
        radians(illumination["sun_elevation_deg"]),
        albedo=albedo,
        emissivity=float(terrain_info.get("emissivity", 0.95)),
        solar_irradiance_w_m2=ephemeris["solar_irradiance_w_m2"],
        incidence_cosine=illumination["mu"],
    )
    earth_alt = earth_elevation(site["latitude"], site["longitude"], when, ephemeris)
    communication = {
        "earth_elevation_deg": round(degrees(earth_alt), 2),
        "earth_visible": earth_alt > 0,
        "assessment": "Visibilidad geométrica aproximada" if earth_alt > 0 else "Tierra bajo el horizonte geométrico aproximado",
        "relay_recommended": earth_alt <= 0,
    }
    slope = terrain_info.get("slope_deg")
    terrain = {
        "slope_deg": float(slope) if slope is not None else None,
        "roughness": terrain_info.get("roughness", "Sin datos locales"),
        "craters": terrain_info.get("craters", "Sin análisis topográfico local"),
        "data_quality": terrain_info.get("quality", "Sin DEM validado"),
        "dem_available": False,
        "slope_aspect_available": False,
        "topographic_shadow_available": False,
    }
    return {
        "site": {"id": site["id"], "name": site["name"], "latitude": site["latitude"], "longitude": site["longitude"], "kind": site["kind"]},
        "mission_time_utc": when.astimezone(timezone.utc).isoformat(),
        "solar": ephemeris,
        "thermal": thermal,
        "illumination": illumination,
        "communication": communication,
        "terrain": terrain,
        "science": site.get("science", ""),
        "sources": {
            "model": ephemeris["ephemeris_model"],
            "diviner": "Referencia externa solamente; sin mediciones Diviner incluidas",
            "spice": (
                "Se usaron kernels NASA SPICE locales en el marco IAU_MOON."
                if "SPICE" in ephemeris["ephemeris_model"]
                else "Sin kernels NASA SPICE activos; la orientación lunar no es de precisión SPICE."
            ),
            "terrain": "No se incluye un DEM; no se calculan sombras topográficas",
        },
        "limitations": LIMITATIONS,
        "verdict": evaluate_verdict(thermal, illumination, communication, terrain),
    }


def compare_sites(sites, when, ephemeris=None):
    results = [analyze_site(site, when, ephemeris) for site in sites]
    return {
        "sites": [
            {
                "name": item["site"]["name"],
                "id": item["site"]["id"],
                "temperature_c": item["thermal"]["temperature_c"],
                "sun_elevation_deg": item["illumination"]["sun_elevation_deg"],
                "sunlight_hours_30d": item["illumination"]["sunlight_hours_30d"],
                "incident_irradiance_w_m2": item["illumination"]["incident_irradiance_w_m2"],
                "earth_visible": item["communication"]["earth_visible"],
                "slope_deg": item["terrain"]["slope_deg"],
                "verdict": item["verdict"]["label"],
            }
            for item in results
        ]
    }


def timeline(site, when, hours=72, step=2):
    points = []
    terrain_info = site.get("terrain", {})
    albedo = float(terrain_info.get("albedo", 0.12))
    emissivity = float(terrain_info.get("emissivity", 0.95))
    for offset in range(0, hours + 1, step):
        instant = when + timedelta(hours=offset)
        solar = solar_ephemeris(instant)
        illumination = surface_illumination(
            site["latitude"], site["longitude"], instant, solar, albedo
        )
        thermal = thermal_balance(
            radians(illumination["sun_elevation_deg"]),
            albedo=albedo,
            emissivity=emissivity,
            solar_irradiance_w_m2=solar["solar_irradiance_w_m2"],
            incidence_cosine=illumination["mu"],
        )
        earth_alt = earth_elevation(site["latitude"], site["longitude"], instant)
        points.append(
            {
                "time": instant.isoformat(),
                "temperature_c": thermal["temperature_c"],
                "sun_elevation_deg": illumination["sun_elevation_deg"],
                "sunlit": illumination["sunlit"],
                "mu": illumination["mu"],
                "incidence_angle_deg": illumination["incidence_angle_deg"],
                "incident_irradiance_w_m2": illumination["incident_irradiance_w_m2"],
                "reflected_flux_w_m2": illumination["reflected_flux_w_m2"],
                "absorbed_w_m2": thermal["absorbed_w_m2"],
                "emitted_w_m2": thermal["emitted_w_m2"],
                "equilibrium_k": thermal["equilibrium_k"],
                "earth_visible": earth_alt > 0,
                "solar": solar,
            }
        )
    return {"points": points, "model": "Muestreo de 2 h; efemérides analíticas y balance radiativo aproximado"}


def find_windows(site, when, days=30):
    points = []
    terrain = site.get("terrain", {})
    slope_value = terrain.get("slope_deg")
    slope = float(slope_value) if slope_value is not None else None
    albedo = float(terrain.get("albedo", 0.12))
    emissivity = float(terrain.get("emissivity", 0.95))
    for offset in range(0, days * 24, 6):
        instant = when + timedelta(hours=offset)
        solar = solar_ephemeris(instant)
        illumination = surface_illumination(
            site["latitude"], site["longitude"], instant, solar, albedo
        )
        earth_alt = earth_elevation(site["latitude"], site["longitude"], instant)
        thermal = thermal_balance(
            radians(illumination["sun_elevation_deg"]),
            albedo=albedo,
            emissivity=emissivity,
            solar_irradiance_w_m2=solar["solar_irradiance_w_m2"],
            incidence_cosine=illumination["mu"],
        )
        score = (
            (35 if illumination["sunlit"] else 0)
            + (25 if earth_alt > 0 else 0)
            + (25 if -220 <= thermal["temperature_c"] <= 80 else 0)
            + (15 if slope is not None and slope <= 10 else 0)
        )
        points.append(
            {
                "time": instant.isoformat(),
                "score": score,
                "sunlit": illumination["sunlit"],
                "earth_visible": earth_alt > 0,
            }
        )
    return {"points": points, "model": "Cribado cada 6 h; sin puntuación de pendiente si no hay dato y no es una ventana orbital de lanzamiento"}

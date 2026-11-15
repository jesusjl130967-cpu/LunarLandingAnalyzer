from __future__ import annotations

import csv
import io
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from math import isfinite
from pathlib import Path

from flask import Flask, abort, jsonify, make_response, render_template, request, send_file
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.graphics.shapes import Drawing, Line, PolyLine, Rect, String
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from lunar_analyzer.integrations import integration_status, resolve_ephemeris, search_lro_products
from lunar_analyzer.science import analyze_site, compare_sites, find_windows, timeline

BASE_DIR = Path(__file__).resolve().parent


def configured_database_path():
    configured_path = os.environ.get("LUNAR_DATABASE_PATH")
    return Path(configured_path) if configured_path else BASE_DIR / "data" / "lunar_analyzer.sqlite3"


DATABASE = configured_database_path()
SITES_PATH = BASE_DIR / "data" / "sites.json"
SCHEMA_PATH = BASE_DIR / "data" / "schema.sql"
app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False


def load_sites():
    with SITES_PATH.open(encoding="utf-8") as file:
        return json.load(file)


@contextmanager
def connect_db():
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def initialize_database():
    DATABASE.parent.mkdir(parents=True, exist_ok=True)
    with connect_db() as connection:
        connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))


def get_site(latitude, longitude, name="Coordenadas personalizadas"):
    return {
        "id": "custom",
        "name": name,
        "latitude": latitude,
        "longitude": longitude,
        "kind": "custom",
        "terrain": {"slope_deg": None, "roughness": "Sin datos locales", "quality": "Sin DEM validado"},
        "science": "Coordenadas introducidas por el usuario; sin atribución geológica específica.",
        "source": "Modelo local de demostración",
    }


def validated_request(data):
    try:
        latitude = float(data["latitude"])
        longitude = float(data["longitude"])
        mission_time = datetime.fromisoformat(str(data["mission_time"]).replace("Z", "+00:00"))
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("Indica latitud, longitud y una fecha/hora ISO válidas.") from error
    if not isfinite(latitude) or not isfinite(longitude) or not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise ValueError("La latitud debe estar entre -90 y 90 y la longitud entre -180 y 180.")
    if mission_time.tzinfo is None:
        mission_time = mission_time.replace(tzinfo=timezone.utc)
    mission_time = mission_time.astimezone(timezone.utc)
    return latitude, longitude, mission_time


@app.get("/")
def home():
    return render_template("index.html", reference_time="2026-11-14T12:00")


@app.get("/health")
def health():
    with connect_db() as connection:
        connection.execute("SELECT 1 FROM evaluations LIMIT 1")
    return jsonify({"status": "ok", "database": DATABASE.name})


@app.get("/api/sites")
def sites():
    return jsonify(load_sites())


@app.get("/api/integrations")
def integrations():
    return jsonify(integration_status())


@app.post("/api/data-products")
def data_products():
    data = request.get_json(silent=True) or {}
    try:
        latitude = float(data["latitude"])
        longitude = float(data["longitude"])
        if not isfinite(latitude) or not isfinite(longitude) or not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
            raise ValueError("La latitud debe estar entre -90 y 90 y la longitud entre -180 y 180.")
    except (KeyError, TypeError):
        return jsonify({"error": "Indica latitud y longitud válidas."}), 400
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    return jsonify(search_lro_products(latitude, longitude))


def prepare_analysis(data):
    latitude, longitude, mission_time = validated_request(data)
    catalog = load_sites()
    site = next((item for item in catalog if item["id"] == data.get("site_id")), None)
    if site is None or data.get("site_id") == "custom":
        site = get_site(latitude, longitude)
    else:
        latitude = float(data.get("latitude", site["latitude"]))
        longitude = float(data.get("longitude", site["longitude"]))
        site = {**site, "latitude": latitude, "longitude": longitude}
    mission_name = str(data.get("mission_name", "Misión de demostración")).strip()[:100] or "Misión de demostración"
    ephemeris, integrations = resolve_ephemeris(mission_time)
    result = analyze_site(site, mission_time, ephemeris)
    result["mission_name"] = mission_name
    result["integrations"] = integrations
    return latitude, longitude, mission_time, site, mission_name, result


@app.post("/api/preview")
def preview():
    data = request.get_json(silent=True) or {}
    try:
        *_, result = prepare_analysis(data)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    return jsonify(result)


@app.post("/api/analyze")
def evaluate():
    data = request.get_json(silent=True) or {}
    try:
        latitude, longitude, mission_time, site, mission_name, result = prepare_analysis(data)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    with connect_db() as connection:
        cursor = connection.execute(
            """INSERT INTO evaluations
               (mission_name, latitude, longitude, mission_time, site_name, result_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                mission_name,
                latitude,
                longitude,
                mission_time.isoformat(),
                site["name"],
                json.dumps(result, ensure_ascii=False),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        result["evaluation_id"] = cursor.lastrowid
        connection.execute(
            "UPDATE evaluations SET result_json = ? WHERE id = ?",
            (json.dumps(result, ensure_ascii=False), cursor.lastrowid),
        )
    return jsonify(result)


@app.post("/api/compare")
def compare():
    data = request.get_json(silent=True) or {}
    try:
        _, _, mission_time = validated_request(data)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    ids = data.get("site_ids", [])
    catalog = load_sites()
    selected = [site for site in catalog if site["id"] in ids][:5]
    ephemeris, _ = resolve_ephemeris(mission_time)
    return jsonify(compare_sites(selected, mission_time, ephemeris))


@app.post("/api/timeline")
def get_timeline():
    data = request.get_json(silent=True) or {}
    try:
        latitude, longitude, mission_time = validated_request(data)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    site = get_site(latitude, longitude)
    site_id = data.get("site_id")
    site = next((item for item in load_sites() if item["id"] == site_id), site)
    site = {**site, "latitude": latitude, "longitude": longitude}
    return jsonify(timeline(site, mission_time))


@app.post("/api/windows")
def windows():
    data = request.get_json(silent=True) or {}
    try:
        latitude, longitude, mission_time = validated_request(data)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    site = get_site(latitude, longitude)
    site = next((item for item in load_sites() if item["id"] == data.get("site_id")), site)
    site = {**site, "latitude": latitude, "longitude": longitude}
    return jsonify(find_windows(site, mission_time))


@app.get("/api/history")
def history():
    with connect_db() as connection:
        rows = connection.execute(
            "SELECT id, mission_name, site_name, latitude, longitude, mission_time, created_at FROM evaluations ORDER BY id DESC LIMIT 50"
        ).fetchall()
    return jsonify([dict(row) for row in rows])


def evaluation_by_id(evaluation_id):
    with connect_db() as connection:
        row = connection.execute("SELECT * FROM evaluations WHERE id = ?", (evaluation_id,)).fetchone()
    if row is None:
        abort(404)
    result = json.loads(row["result_json"])
    result.update(
        {
            "evaluation_id": row["id"],
            "mission_name": row["mission_name"],
            "site_name": row["site_name"],
            "latitude": row["latitude"],
            "longitude": row["longitude"],
            "mission_time": row["mission_time"],
        }
    )
    return result


@app.get("/report/<int:evaluation_id>.csv")
def csv_report(evaluation_id):
    result = evaluation_by_id(evaluation_id)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Campo", "Valor", "Tipo de dato"])
    writer.writerow(["Misión", result["mission_name"], "Entrada"])
    writer.writerow(["Sitio", result["site_name"], "Catálogo local"])
    writer.writerow(["Latitud lunar", result["latitude"], "grados"])
    writer.writerow(["Longitud lunar", result["longitude"], "grados"])
    writer.writerow(["Fecha/hora de misión", result["mission_time"], "UTC"])
    writer.writerow(["Viabilidad", result["verdict"]["label"], "Evaluación orientativa, no certificación"])
    writer.writerow(["Temperatura estimada", result["thermal"]["temperature_c"], "°C; modelo"])
    writer.writerow(["Temperatura de equilibrio radiativo", result["thermal"]["equilibrium_c"], "°C; modelo"])
    writer.writerow(["Energía solar absorbida", result["thermal"]["absorbed_w_m2"], "W/m²; modelo"])
    writer.writerow(["Radiación térmica emitida", result["thermal"]["emitted_w_m2"], "W/m²; modelo"])
    writer.writerow(["Fuente de efemérides", result["solar"]["ephemeris_model"], "Horizons/SPICE opcionales; fallback analítico"])
    writer.writerow(["Elevación solar", result["illumination"]["sun_elevation_deg"], "grados; N·S sin relieve"])
    writer.writerow(["Iluminación", result["illumination"]["state"], "estimación"])
    writer.writerow(["Coeficiente de incidencia μ = N·S", result["illumination"]["mu"], "superficie esférica sin relieve"])
    writer.writerow(["Ángulo de incidencia solar", result["illumination"]["incidence_angle_deg"], "grados"])
    writer.writerow(["Irradiancia solar normal E₀", result["solar"]["solar_irradiance_w_m2"], "W/m²; distancia de la fuente de efemérides"])
    writer.writerow(["Irradiancia incidente local", result["illumination"]["incident_irradiance_w_m2"], "W/m²; E₀ max(μ, 0)"])
    writer.writerow(["Flujo solar reflejado estimado", result["illumination"]["reflected_flux_w_m2"], "W/m²; albedo por flujo incidente"])
    writer.writerow(["Distancia Sol-Luna", result["solar"]["sun_moon_distance_km"], "km; fuente indicada arriba"])
    writer.writerow(["Superficie lunar iluminada global", result["solar"]["global_illuminated_surface_percent"], "%; esfera sin sombras topográficas"])
    writer.writerow(["Disco visible iluminado", result["solar"]["visible_disk_illuminated_percent"], "%; fase geométrica aproximada"])
    writer.writerow(["Punto subsolar", f'{result["solar"]["subsolar_latitude_deg"]}°, {result["solar"]["subsolar_longitude_deg"]}°', "coordenadas lunares; marco síncrono aproximado"])
    writer.writerow(["Sombra topográfica", result["illumination"]["topographic_shadow_status"], "sin DEM validado"])
    writer.writerow(["Luz solar estimada (próximos 30 días)", result["illumination"]["sunlight_hours_30d"], "horas"])
    writer.writerow(["Visibilidad geométrica de la Tierra", result["communication"]["earth_visible"], "estimación; no disponibilidad de enlace"])
    writer.writerow(["Pendiente de referencia", result["terrain"]["slope_deg"] if result["terrain"]["slope_deg"] is not None else "No disponible", "grados; catálogo/demostración, no DEM"])
    writer.writerow(["Riesgos", "; ".join(result["verdict"]["risks"]), "Análisis orientativo"])
    writer.writerow(["Fuentes/limitaciones", "Ver README.md y el campo limitations del JSON de análisis", "Metodología"])
    response = make_response("\ufeff" + output.getvalue())
    response.headers["Content-Type"] = "text/csv; charset=utf-8"
    response.headers["Content-Disposition"] = f'attachment; filename="evaluacion-lunar-{evaluation_id}.csv"'
    return response


@app.get("/report/<int:evaluation_id>.pdf")
def pdf_report(evaluation_id):
    result = evaluation_by_id(evaluation_id)
    output = io.BytesIO()
    document = SimpleDocTemplate(output, pagesize=letter, title="Informe Lunar Landing Analyzer")
    styles = getSampleStyleSheet()
    elements = [
        Paragraph("Lunar Landing Analyzer", styles["Title"]),
        Paragraph("Informe orientativo de evaluación de sitio lunar", styles["Heading2"]),
        Spacer(1, 10),
    ]
    rows = [
        ["Campo", "Resultado"],
        ["Misión / sitio", f'{result["mission_name"]} / {result["site_name"]}'],
        ["Coordenadas lunares", f'{result["latitude"]:.4f}°, {result["longitude"]:.4f}°'],
        ["Fecha/hora", result["mission_time"]],
        ["Fuente de efemérides", result["solar"]["ephemeris_model"]],
        ["Viabilidad orientativa", result["verdict"]["label"]],
        ["Temperatura estimada", f'{result["thermal"]["temperature_c"]:.1f} °C'],
        ["Equilibrio radiativo instantáneo", f'{result["thermal"]["equilibrium_c"]:.1f} °C'],
        ["Radiación absorbida / emitida", f'{result["thermal"]["absorbed_w_m2"]:.1f} / {result["thermal"]["emitted_w_m2"]:.1f} W/m²'],
        ["Elevación solar / estado", f'{result["illumination"]["sun_elevation_deg"]:.2f}° / {result["illumination"]["state"]}'],
        ["Incidencia local / irradiancia", f'{result["illumination"]["mu"]:.4f} / {result["illumination"]["incident_irradiance_w_m2"]:.1f} W/m²'],
        ["Irradiancia solar E₀ / distancia", f'{result["solar"]["solar_irradiance_w_m2"]:.1f} W/m² / {result["solar"]["sun_moon_distance_km"]:,.0f} km'],
        ["Superficie global / disco visible iluminado", f'{result["solar"]["global_illuminated_surface_percent"]:.1f}% / {result["solar"]["visible_disk_illuminated_percent"]:.1f}%'],
        ["Punto subsolar", f'{result["solar"]["subsolar_latitude_deg"]:.2f}°, {result["solar"]["subsolar_longitude_deg"]:.2f}°'],
        ["Sombra topográfica", result["illumination"]["topographic_shadow_status"]],
        ["Sol estimado en 30 días", f'{result["illumination"]["sunlight_hours_30d"]:.1f} h'],
        ["Visibilidad geométrica de la Tierra", "Visible" if result["communication"]["earth_visible"] else "Oculta"],
        ["Pendiente de referencia", f'{result["terrain"]["slope_deg"]:.1f}°' if result["terrain"]["slope_deg"] is not None else "No disponible; sin DEM"],
    ]
    table = Table(rows, colWidths=[190, 330])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#14314a")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#b7c8d8")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f1f6fa")]),
                ("PADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    site = next((item for item in load_sites() if item["id"] == result.get("site", {}).get("id")), None)
    if site is None:
        site = get_site(result["latitude"], result["longitude"], result["site_name"])
    site = {**site, "latitude": result["latitude"], "longitude": result["longitude"]}
    mission_time = datetime.fromisoformat(result["mission_time"].replace("Z", "+00:00"))
    profile = timeline(site, mission_time)["points"]
    profile_chart = Drawing(520, 160)
    x0, y0, chart_w, chart_h = 40, 28, 455, 106
    for tick in range(5):
        y = y0 + chart_h * tick / 4
        profile_chart.add(Line(x0, y, x0 + chart_w, y, strokeColor=colors.HexColor("#dce5eb"), strokeWidth=0.5))
        profile_chart.add(String(2, y - 3, f"{-250 + tick * 70} C", fontSize=7, fillColor=colors.HexColor("#556b7c")))
    profile_chart.add(String(x0, 5, "T + 0 h", fontSize=7, fillColor=colors.HexColor("#556b7c")))
    profile_chart.add(String(x0 + chart_w - 28, 5, "72 h", fontSize=7, fillColor=colors.HexColor("#556b7c")))
    coords = []
    for index, point in enumerate(profile):
        x = x0 + chart_w * index / max(1, len(profile) - 1)
        y = y0 + max(0, min(1, (point["temperature_c"] + 250) / 280)) * chart_h
        coords.extend([x, y])
    profile_chart.add(PolyLine(coords, strokeColor=colors.HexColor("#158da6"), strokeWidth=1.8))
    profile_chart.add(String(x0, 143, "Perfil térmico estimado · equilibrio instantáneo · próximos 72 h", fontSize=8, fillColor=colors.HexColor("#334d60")))

    energy_chart = Drawing(520, 98)
    energy_chart.add(String(2, 80, "Flujos térmicos del instante seleccionado (W/m²)", fontSize=8, fillColor=colors.HexColor("#334d60")))
    for index, (label, value, color) in enumerate(
        [
            ("Incidente", result["thermal"]["incident_w_m2"], colors.HexColor("#409dbb")),
            ("Absorbida", result["thermal"]["absorbed_w_m2"], colors.HexColor("#158da6")),
            ("Emitida", result["thermal"]["emitted_w_m2"], colors.HexColor("#d49a49")),
        ]
    ):
        y = 55 - index * 22
        energy_chart.add(String(2, y + 3, label, fontSize=7, fillColor=colors.HexColor("#556b7c")))
        bar_width = min(390, max(1, float(value) / max(1, result["thermal"]["incident_w_m2"]) * 390))
        energy_chart.add(Rect(80, y, bar_width, 11, fillColor=color, strokeColor=None))
        energy_chart.add(String(477, y + 2, f"{value:.1f}", fontSize=7, fillColor=colors.HexColor("#334d60")))
    elements.extend([table, Spacer(1, 12), Paragraph("Gráficas del modelo", styles["Heading2"]), profile_chart, energy_chart, Paragraph("Diagnóstico", styles["Heading2"])])
    elements.append(Paragraph(result["verdict"]["summary"], styles["BodyText"]))
    for item in result["verdict"]["favorable"]:
        elements.append(Paragraph(f"Favorable: {item}", styles["BodyText"]))
    for item in result["verdict"]["risks"]:
        elements.append(Paragraph(f"Riesgo: {item}", styles["BodyText"]))
    elements.extend([Spacer(1, 10), Paragraph("Limitaciones científicas", styles["Heading2"])])
    for item in result["limitations"]:
        elements.append(Paragraph(item, styles["BodyText"]))
    elements.extend(
        [
            Spacer(1, 10),
            Paragraph("Fuentes de referencia", styles["Heading2"]),
            Paragraph("PDS Geosciences ODE: la búsqueda muestra metadatos y enlaces; no descarga ni procesa productos Diviner/LOLA.", styles["BodyText"]),
            Paragraph(result["sources"]["spice"], styles["BodyText"]),
        ]
    )
    document.build(elements)
    output.seek(0)
    return send_file(output, mimetype="application/pdf", as_attachment=True, download_name=f"evaluacion-lunar-{evaluation_id}.pdf")


initialize_database()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8080, debug=False)

"""
FastAPI - Calculate Chart endpoint para sistema ANCORADA
=========================================================
Endpoint POST /calculate-chart retorna carta astral REAL
calculada via Swiss Ephemeris (pyswisseph).

Para rodar:
    uvicorn main:app --reload --port 8000
"""

from datetime import datetime, timezone
from typing import Optional

import swisseph as swe
import pytz
from geopy.geocoders import Nominatim
from timezonefinder import TimezoneFinder

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Swiss Ephemeris setup
# ---------------------------------------------------------------------------
import os as _os
_EPHE_PATH = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "ephe")
if _os.path.isdir(_EPHE_PATH):
    swe.set_ephe_path(_EPHE_PATH)
else:
    swe.set_ephe_path(".")

app = FastAPI(
    title="ANCORADA Chart API",
    description="API de calculo astrologico real para sistema ANCORADA",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================================================================
# Schemas de entrada
# =============================================================================
class BirthData(BaseModel):
    birth_date: str = Field(..., description="Data de nascimento YYYY-MM-DD")
    birth_time: Optional[str] = Field(None, description="Hora de nascimento HH:MM")
    birth_city: str
    birth_state: Optional[str] = None
    birth_country: str
    birth_time_unknown: bool = False


# =============================================================================
# Constantes astrologicas
# =============================================================================
SIGNS = [
    "Aries", "Touro", "Gemeos", "Cancer", "Leao", "Virgem",
    "Libra", "Escorpiao", "Sagitario", "Capricornio", "Aquario", "Peixes",
]

SIGN_ELEMENTS = {
    "Aries": "fogo", "Leao": "fogo", "Sagitario": "fogo",
    "Touro": "terra", "Virgem": "terra", "Capricornio": "terra",
    "Gemeos": "ar", "Libra": "ar", "Aquario": "ar",
    "Cancer": "agua", "Escorpiao": "agua", "Peixes": "agua",
}

SIGN_MODALITIES = {
    "Aries": "cardinal", "Cancer": "cardinal", "Libra": "cardinal", "Capricornio": "cardinal",
    "Touro": "fixo", "Leao": "fixo", "Escorpiao": "fixo", "Aquario": "fixo",
    "Gemeos": "mutavel", "Virgem": "mutavel", "Sagitario": "mutavel", "Peixes": "mutavel",
}

PLANET_RULERS = {
    "Aries": "Marte", "Touro": "Venus", "Gemeos": "Mercurio", "Cancer": "Lua",
    "Leao": "Sol", "Virgem": "Mercurio", "Libra": "Venus", "Escorpiao": "Plutao",
    "Sagitario": "Jupiter", "Capricornio": "Saturno", "Aquario": "Urano", "Peixes": "Netuno",
}

# Mapeamento nome -> id do Swiss Ephemeris
PLANET_IDS = {
    "sun": swe.SUN,
    "moon": swe.MOON,
    "mercury": swe.MERCURY,
    "venus": swe.VENUS,
    "mars": swe.MARS,
    "jupiter": swe.JUPITER,
    "saturn": swe.SATURN,
    "uranus": swe.URANUS,
    "neptune": swe.NEPTUNE,
    "pluto": swe.PLUTO,
    "chiron": swe.CHIRON,
}

PLANET_NAMES_PT = {
    "sun": "Sol", "moon": "Lua", "mercury": "Mercurio", "venus": "Venus",
    "mars": "Marte", "jupiter": "Jupiter", "saturn": "Saturno",
    "uranus": "Urano", "neptune": "Netuno", "pluto": "Plutao", "chiron": "Quiron",
    "ascendant": "Ascendente", "midheaven": "Meio do Ceu",
}

HOUSE_THEMES = [
    "Identidade e expressao pessoal",
    "Recursos, valores e seguranca material",
    "Comunicacao, irmaos e ambiente proximo",
    "Lar, raizes e mundo emocional",
    "Criatividade, prazer e filhos",
    "Trabalho, rotina e saude",
    "Relacionamentos e parcerias",
    "Transformacao, sexualidade e recursos compartilhados",
    "Filosofia, viagens e expansao",
    "Carreira, vocacao e imagem publica",
    "Amizades, grupos e visao de futuro",
    "Inconsciente, espiritualidade e dissolucao",
]


# =============================================================================
# Helpers
# =============================================================================
def longitude_to_sign(longitude: float) -> dict:
    """Converte longitude ecliptica (0-360) em signo + grau."""
    longitude = longitude % 360
    sign_index = int(longitude // 30)
    degree_in_sign = longitude % 30
    deg = int(degree_in_sign)
    minutes = int((degree_in_sign - deg) * 60)
    sign = SIGNS[sign_index]
    return {
        "sign": sign,
        "degree": round(degree_in_sign, 4),
        "degree_formatted": f"{deg}\u00b0{minutes:02d}'",
        "absolute_longitude": round(longitude, 4),
        "element": SIGN_ELEMENTS[sign],
        "modality": SIGN_MODALITIES[sign],
        "ruler": PLANET_RULERS[sign],
    }


def calc_aspect(lon1: float, lon2: float) -> Optional[dict]:
    """Calcula aspecto entre duas longitudes eclipticas."""
    diff = abs(lon1 - lon2) % 360
    if diff > 180:
        diff = 360 - diff

    aspects_def = [
        ("conjuncao", 0, 8),
        ("oposicao", 180, 8),
        ("trigono", 120, 7),
        ("quadratura", 90, 7),
        ("sextil", 60, 5),
    ]
    for name, angle, max_orb in aspects_def:
        orb = abs(diff - angle)
        if orb <= max_orb:
            return {
                "aspect": name,
                "exact_angle": angle,
                "orb": round(orb, 2),
                "applying": lon1 < lon2,
                "strength": "forte" if orb <= max_orb / 2 else "moderado",
            }
    return None


def determine_house(longitude: float, cusps: list[float]) -> int:
    """Determina em qual casa (1-12) uma longitude cai, dadas as 12 cuspides."""
    lon = longitude % 360
    for i in range(12):
        cusp_start = cusps[i] % 360
        cusp_end = cusps[(i + 1) % 12] % 360
        if cusp_start < cusp_end:
            if cusp_start <= lon < cusp_end:
                return i + 1
        else:  # cruza 0 graus
            if lon >= cusp_start or lon < cusp_end:
                return i + 1
    return 1


def geocode_city(city: str, state: Optional[str], country: str) -> dict:
    """Geocodifica cidade usando Nominatim (OpenStreetMap)."""
    geolocator = Nominatim(user_agent="ancorada-chart-api/1.0")
    parts = [city]
    if state:
        parts.append(state)
    parts.append(country)
    query = ", ".join(parts)

    location = geolocator.geocode(query, language="pt")
    if not location:
        raise HTTPException(
            status_code=404,
            detail=f"Nao foi possivel geocodificar a cidade: {query}",
        )
    return {
        "latitude": location.latitude,
        "longitude": location.longitude,
        "display_name": location.address,
    }


def get_timezone_info(lat: float, lon: float, dt_utc: datetime) -> dict:
    """Encontra timezone a partir de coordenadas."""
    tf = TimezoneFinder()
    tz_name = tf.timezone_at(lat=lat, lng=lon)
    if not tz_name:
        raise HTTPException(
            status_code=422,
            detail=f"Nao foi possivel determinar o timezone para lat={lat}, lon={lon}",
        )
    tz = pytz.timezone(tz_name)
    utc_offset = tz.localize(dt_utc.replace(tzinfo=None)).strftime("%z")
    utc_offset_formatted = f"{utc_offset[:3]}:{utc_offset[3:]}"
    return {"timezone": tz_name, "utc_offset": utc_offset_formatted}


def local_to_julian_day(date_str: str, time_str: Optional[str], tz_name: str) -> float:
    """Converte data/hora local para Julian Day UT."""
    parts = date_str.split("-")
    year, month, day = int(parts[0]), int(parts[1]), int(parts[2])

    if time_str:
        tparts = time_str.split(":")
        hour, minute = int(tparts[0]), int(tparts[1])
    else:
        hour, minute = 12, 0  # meio-dia solar se hora desconhecida

    tz = pytz.timezone(tz_name)
    local_dt = tz.localize(datetime(year, month, day, hour, minute, 0))
    utc_dt = local_dt.astimezone(pytz.utc)

    # Julian Day a partir de UTC
    decimal_hour = utc_dt.hour + utc_dt.minute / 60.0 + utc_dt.second / 3600.0
    jd = swe.julday(utc_dt.year, utc_dt.month, utc_dt.day, decimal_hour)
    return jd


def calculate_planets(jd: float) -> dict:
    """Calcula posicoes de todos os planetas para um Julian Day."""
    results = {}
    for name, pid in PLANET_IDS.items():
        flags = swe.FLG_MOSEPH | swe.FLG_SPEED
        try:
            result, retflag = swe.calc_ut(jd, pid, flags)
        except Exception as e:
            print(f"[WARN] Falha ao calcular {name} (id={pid}): {e}")
            continue
        lon, lat, dist, speed_lon, speed_lat, speed_dist = result
        results[name] = {
            "longitude": lon,
            "latitude": lat,
            "distance": dist,
            "speed": speed_lon,
            "retrograde": speed_lon < 0,
        }
    return results


def calculate_houses_and_angles(jd: float, lat: float, lon: float) -> dict:
    """Calcula casas (Placidus) e angulos (ASC, MC)."""
    cusps, ascmc = swe.houses(jd, lat, lon, b'P')
    # cusps: tuple de 12 cuspides (indice 0 = casa 1)
    # ascmc: [0]=ASC, [1]=MC, [2]=ARMC, [3]=Vertex, ...
    return {
        "cusps": list(cusps),  # 12 elementos, casa 1 a 12
        "ascendant": ascmc[0],
        "midheaven": ascmc[1],
    }


# =============================================================================
# Montagem do retorno
# =============================================================================
def build_planet_entry(planet_data: dict, house: int) -> dict:
    """Monta entrada completa de um planeta."""
    sign_data = longitude_to_sign(planet_data["longitude"])
    return {
        **sign_data,
        "house": house,
        "retrograde": planet_data["retrograde"],
        "speed": round(planet_data["speed"], 6),
        "declination": round(planet_data.get("latitude", 0), 4),
    }


def build_natal_chart(planets: dict, houses_data: dict) -> dict:
    """Monta natal_chart com todos os planetas + ASC + MC."""
    cusps = houses_data["cusps"]
    chart = {}

    for name, pdata in planets.items():
        house = determine_house(pdata["longitude"], cusps)
        chart[name] = build_planet_entry(pdata, house)

    # Ascendente
    asc_lon = houses_data["ascendant"]
    asc_sign = longitude_to_sign(asc_lon)
    chart["ascendant"] = {
        **asc_sign,
        "house": 1,
        "retrograde": False,
        "speed": 0.0,
        "declination": 0.0,
    }

    # Meio do Ceu
    mc_lon = houses_data["midheaven"]
    mc_sign = longitude_to_sign(mc_lon)
    chart["midheaven"] = {
        **mc_sign,
        "house": 10,
        "retrograde": False,
        "speed": 0.0,
        "declination": 0.0,
    }

    return chart


def build_houses(houses_data: dict) -> list:
    """Monta lista das 12 casas com cuspides reais (Placidus)."""
    cusps = houses_data["cusps"]
    houses = []
    for i in range(12):
        sign_data = longitude_to_sign(cusps[i])
        houses.append({
            "number": i + 1,
            "cusp_longitude": round(cusps[i], 4),
            "cusp_sign": sign_data["sign"],
            "cusp_degree": sign_data["degree"],
            "cusp_formatted": f"{sign_data['degree_formatted']} {sign_data['sign']}",
            "ruler": sign_data["ruler"],
            "theme": HOUSE_THEMES[i],
        })
    return houses


def build_natal_aspects(planets: dict, houses_data: dict) -> list:
    """Calcula aspectos entre todos os planetas natais."""
    aspect_planets = [
        "sun", "moon", "mercury", "venus", "mars",
        "jupiter", "saturn", "uranus", "neptune", "pluto", "chiron",
    ]
    # Inclui ASC e MC nos aspectos (filtra planetas ausentes)
    longitudes = {name: planets[name]["longitude"] for name in aspect_planets if name in planets}
    longitudes["ascendant"] = houses_data["ascendant"]
    longitudes["midheaven"] = houses_data["midheaven"]

    all_points = list(longitudes.keys())
    aspects = []
    for i, p1 in enumerate(all_points):
        for p2 in all_points[i + 1:]:
            aspect = calc_aspect(longitudes[p1], longitudes[p2])
            if aspect:
                aspects.append({
                    "planet1": p1,
                    "planet2": p2,
                    **aspect,
                })
    return aspects


def build_current_transits(natal_planets: dict, natal_houses_data: dict) -> list:
    """Calcula transitos atuais reais sobre planetas natais."""
    now_utc = datetime.now(timezone.utc)
    decimal_hour = now_utc.hour + now_utc.minute / 60.0 + now_utc.second / 3600.0
    jd_now = swe.julday(now_utc.year, now_utc.month, now_utc.day, decimal_hour)

    transit_planets_ids = {
        "jupiter": swe.JUPITER,
        "saturn": swe.SATURN,
        "uranus": swe.URANUS,
        "neptune": swe.NEPTUNE,
        "pluto": swe.PLUTO,
    }
    natal_targets = ["sun", "moon", "venus", "mars", "saturn", "chiron"]

    transits = []
    for tname, tid in transit_planets_ids.items():
        flags = swe.FLG_MOSEPH | swe.FLG_SPEED
        result, _ = swe.calc_ut(jd_now, tid, flags)
        tlon = result[0]
        sign_data = longitude_to_sign(tlon)

        for target in natal_targets:
            if target not in natal_planets:
                continue
            natal_lon = natal_planets[target]["longitude"]
            aspect = calc_aspect(tlon, natal_lon)
            if aspect and aspect["orb"] <= 3.0:
                transits.append({
                    "transit_planet": tname,
                    "transit_position": {
                        "sign": sign_data["sign"],
                        "degree_formatted": sign_data["degree_formatted"],
                        "longitude": round(tlon, 4),
                    },
                    "natal_target": target,
                    "aspect": aspect["aspect"],
                    "orb": aspect["orb"],
                    "applying": aspect["applying"],
                    "strength": aspect["strength"],
                })
    return transits


def build_ancorada_extraction(natal_chart: dict, aspects: list) -> dict:
    """Extrai os 4 pilares ANCORADA + ancora central a partir da carta real."""
    saturn = natal_chart.get("saturn", {})
    venus = natal_chart.get("venus", {})
    mars = natal_chart.get("mars", {})
    chiron = natal_chart.get("chiron", {})
    pluto = natal_chart.get("pluto", {})

    saturn_hard_aspects = [
        a for a in aspects
        if (a["planet1"] == "saturn" or a["planet2"] == "saturn")
        and a["aspect"] in ("quadratura", "oposicao", "conjuncao")
    ]

    venus_hard_aspects = [
        a for a in aspects
        if (a["planet1"] == "venus" or a["planet2"] == "venus")
        and a["aspect"] in ("quadratura", "oposicao", "conjuncao")
    ]

    mars_hard_aspects = [
        a for a in aspects
        if (a["planet1"] == "mars" or a["planet2"] == "mars")
        and a["aspect"] in ("quadratura", "oposicao", "conjuncao")
    ]

    chiron_hard_aspects = [
        a for a in aspects
        if (a["planet1"] == "chiron" or a["planet2"] == "chiron")
        and a["aspect"] in ("quadratura", "oposicao", "conjuncao")
    ]

    pluto_aspects = [
        a for a in aspects
        if a["planet1"] == "pluto" or a["planet2"] == "pluto"
    ]

    def intensity(hard_aspects_count: int, is_retrograde: bool) -> str:
        score = hard_aspects_count
        if is_retrograde:
            score += 1
        if score >= 3:
            return "alta"
        if score >= 1:
            return "moderada"
        return "baixa"

    def fmt_aspects(asp_list: list) -> list:
        return [f"{a['planet1']} {a['aspect']} {a['planet2']} (orb {a['orb']})" for a in asp_list[:5]]

    return {
        "saturno_desorientado": {
            "detected": len(saturn_hard_aspects) > 0 or saturn.get("retrograde", False),
            "intensity": intensity(len(saturn_hard_aspects), saturn.get("retrograde", False)),
            "signature": f"Saturno em {saturn.get('sign', '?')} casa {saturn.get('house', '?')}",
            "indicators": [
                f"Saturno em {saturn.get('sign', '?')} (elemento {saturn.get('element', '?')}, modalidade {saturn.get('modality', '?')})",
                f"Casa {saturn.get('house', '?')}",
                f"Retrogrado: {'sim' if saturn.get('retrograde') else 'nao'}",
                f"{len(saturn_hard_aspects)} aspecto(s) tenso(s) detectado(s)",
            ],
            "related_aspects": fmt_aspects(saturn_hard_aspects),
        },
        "venus_negociada": {
            "detected": len(venus_hard_aspects) > 0 or venus.get("retrograde", False),
            "intensity": intensity(len(venus_hard_aspects), venus.get("retrograde", False)),
            "signature": f"Venus em {venus.get('sign', '?')} casa {venus.get('house', '?')}",
            "indicators": [
                f"Venus em {venus.get('sign', '?')} (elemento {venus.get('element', '?')}, modalidade {venus.get('modality', '?')})",
                f"Casa {venus.get('house', '?')}",
                f"Retrogrado: {'sim' if venus.get('retrograde') else 'nao'}",
                f"{len(venus_hard_aspects)} aspecto(s) tenso(s) detectado(s)",
            ],
            "related_aspects": fmt_aspects(venus_hard_aspects),
        },
        "marte_apagado": {
            "detected": len(mars_hard_aspects) > 0 or mars.get("retrograde", False),
            "intensity": intensity(len(mars_hard_aspects), mars.get("retrograde", False)),
            "signature": f"Marte em {mars.get('sign', '?')} casa {mars.get('house', '?')}",
            "indicators": [
                f"Marte em {mars.get('sign', '?')} (elemento {mars.get('element', '?')}, modalidade {mars.get('modality', '?')})",
                f"Casa {mars.get('house', '?')}",
                f"Retrogrado: {'sim' if mars.get('retrograde') else 'nao'}",
                f"{len(mars_hard_aspects)} aspecto(s) tenso(s) detectado(s)",
            ],
            "related_aspects": fmt_aspects(mars_hard_aspects),
        },
        "quiron_nao_integrado": {
            "detected": len(chiron_hard_aspects) > 0 or chiron.get("retrograde", False),
            "intensity": intensity(len(chiron_hard_aspects), chiron.get("retrograde", False)),
            "signature": f"Quiron em {chiron.get('sign', '?')} casa {chiron.get('house', '?')}",
            "indicators": [
                f"Quiron em {chiron.get('sign', '?')} (elemento {chiron.get('element', '?')}, modalidade {chiron.get('modality', '?')})",
                f"Casa {chiron.get('house', '?')}",
                f"Retrogrado: {'sim' if chiron.get('retrograde') else 'nao'}",
                f"{len(chiron_hard_aspects)} aspecto(s) tenso(s) detectado(s)",
            ],
            "related_aspects": fmt_aspects(chiron_hard_aspects),
        },
        "central_anchor": {
            "anchor_planet": "pluto",
            "anchor_position": f"Plutao em {pluto.get('sign', '?')} casa {pluto.get('house', '?')}",
            "anchor_signature": f"{pluto.get('degree_formatted', '?')} {pluto.get('sign', '?')}",
            "total_pluto_aspects": len(pluto_aspects),
            "related_aspects": fmt_aspects(pluto_aspects),
            "diagnostic_priority_order": [
                "saturno_desorientado",
                "marte_apagado",
                "quiron_nao_integrado",
                "venus_negociada",
            ],
        },
    }


# =============================================================================
# Endpoints
# =============================================================================
@app.post("/calculate-chart")
def calculate_chart(data: BirthData):
    # 1. Geocoding
    geo = geocode_city(data.birth_city, data.birth_state, data.birth_country)
    lat = geo["latitude"]
    lon = geo["longitude"]

    # 2. Timezone
    date_parts = data.birth_date.split("-")
    naive_dt = datetime(int(date_parts[0]), int(date_parts[1]), int(date_parts[2]))
    tz_info = get_timezone_info(lat, lon, naive_dt)

    resolved_location = {
        "city": data.birth_city,
        "state": data.birth_state,
        "country": data.birth_country,
        "latitude": round(lat, 6),
        "longitude": round(lon, 6),
        "timezone": tz_info["timezone"],
        "utc_offset": tz_info["utc_offset"],
        "resolved_at": datetime.now(timezone.utc).isoformat(),
        "source": "nominatim_openstreetmap",
        "display_name": geo["display_name"],
    }

    # 3. Julian Day
    if data.birth_time_unknown and not data.birth_time:
        birth_time = None
    else:
        birth_time = data.birth_time

    jd = local_to_julian_day(data.birth_date, birth_time, tz_info["timezone"])

    # 4. Planetas
    planets = calculate_planets(jd)

    # 5. Casas e angulos
    houses_data = calculate_houses_and_angles(jd, lat, lon)

    # 6. Montar retorno
    natal_chart = build_natal_chart(planets, houses_data)
    houses = build_houses(houses_data)
    natal_aspects = build_natal_aspects(planets, houses_data)
    current_transits = build_current_transits(planets, houses_data)
    ancorada_extraction = build_ancorada_extraction(natal_chart, natal_aspects)

    chart_json = {
        "mode": "real",
        "is_mock": False,
        "engine": "pyswisseph (Swiss Ephemeris)",
        "house_system": "Placidus",
        "calculated_at": datetime.now(timezone.utc).isoformat(),
        "input_echo": {
            "birth_date": data.birth_date,
            "birth_time": data.birth_time,
            "birth_time_unknown": data.birth_time_unknown,
            "birth_time_used": birth_time if birth_time else "12:00 (meio-dia solar)",
        },
        "natal_chart": natal_chart,
        "houses": houses,
        "natal_aspects": natal_aspects,
        "current_transits": current_transits,
        "ancorada_extraction": ancorada_extraction,
    }

    return {
        "resolved_location": resolved_location,
        "chart_json": chart_json,
    }


@app.get("/")
def root():
    return {
        "service": "ANCORADA Chart API",
        "version": "1.1.0-chiron-fix",
        "engine": "pyswisseph (Swiss Ephemeris)",
        "endpoints": ["POST /calculate-chart"],
    }


@app.get("/health")
def health():
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}

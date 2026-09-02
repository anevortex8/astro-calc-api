"""
FastAPI - Calculate Chart endpoint para sistema ANCORADA
=========================================================
Endpoint POST /calculate-chart retorna carta astral REAL
calculada via Swiss Ephemeris (pyswisseph).

Para rodar:
    uvicorn main:app --reload --port 8000
"""

import re
import time
from datetime import datetime, timezone
from typing import Optional

import swisseph as swe
import pytz
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderServiceError
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


class EclipseSeasonRequest(BirthData):
    """Mesmos campos de BirthData — endpoint autocontido, resolve geocoding/timezone/JD internamente."""
    pass


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


_GEOCODE_TIMEOUT_S = 10
_GEOCODE_MAX_ATTEMPTS = 3
_GEOCODE_RETRY_DELAY_S = 2


def geocode_city(city: str, state: Optional[str], country: str) -> dict:
    """Geocodifica cidade usando Nominatim (OpenStreetMap)."""
    geolocator = Nominatim(user_agent="ancorada-chart-api/1.0", timeout=_GEOCODE_TIMEOUT_S)
    parts = [city]
    if state:
        parts.append(state)
    parts.append(country)
    query = ", ".join(parts)

    # Nominatim e um servico publico compartilhado sujeito a timeout/indisponibilidade
    # transitoria. Sem retry, qualquer soluco de rede virava excecao nao tratada e o
    # FastAPI respondia 500 generico pro caller (process-generation-queue).
    location = None
    last_error: Optional[GeocoderServiceError] = None
    for attempt in range(_GEOCODE_MAX_ATTEMPTS):
        try:
            location = geolocator.geocode(query, language="pt")
            break
        except GeocoderServiceError as e:
            last_error = e
            if attempt < _GEOCODE_MAX_ATTEMPTS - 1:
                time.sleep(_GEOCODE_RETRY_DELAY_S)

    if location is None:
        if last_error is not None:
            raise HTTPException(
                status_code=503,
                detail=(
                    f"Servico de geocodificacao (Nominatim) indisponivel apos "
                    f"{_GEOCODE_MAX_ATTEMPTS} tentativas: {last_error}"
                ),
            )
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
    swe.set_ephe_path(_EPHE_PATH)
    results = {}
    for name, pid in PLANET_IDS.items():
        try:
            flags = swe.FLG_SWIEPH | swe.FLG_SPEED
            result, retflag = swe.calc_ut(jd, pid, flags)
        except Exception:
            try:
                flags = swe.FLG_MOSEPH | swe.FLG_SPEED
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
    """Calcula transitos atuais reais sobre planetas natais.

    Orbes máximos por planeta transitante:
    - Plutão, Netuno, Urano, Saturno: 5°
    - Quíron: 4°
    - Júpiter: 3°
    - Marte: 2° (descartado por ser rápido demais para diagnóstico ANCORADA)

    Alvos natais: todos os planetas + ASC + MC.
    """
    now_utc = datetime.now(timezone.utc)
    decimal_hour = now_utc.hour + now_utc.minute / 60.0 + now_utc.second / 3600.0
    jd_now = swe.julday(now_utc.year, now_utc.month, now_utc.day, decimal_hour)

    # Planetas transitantes com seus orbes máximos
    transit_planets = {
        "jupiter":  (swe.JUPITER, 3.0),
        "saturn":   (swe.SATURN, 5.0),
        "uranus":   (swe.URANUS, 5.0),
        "neptune":  (swe.NEPTUNE, 5.0),
        "pluto":    (swe.PLUTO, 5.0),
    }

    # Quíron transitante (ID especial no swisseph)
    try:
        chiron_tid = swe.CHIRON
        transit_planets["chiron_tr"] = (chiron_tid, 4.0)
    except AttributeError:
        pass  # swisseph sem suporte a Quíron

    # Alvos natais expandidos: todos os planetas + ASC + MC
    natal_targets = [
        "sun", "moon", "mercury", "venus", "mars", "jupiter",
        "saturn", "uranus", "neptune", "pluto", "chiron",
        "ascendant", "midheaven",
    ]

    transits = []
    for tname, (tid, max_orb) in transit_planets.items():
        flags = swe.FLG_MOSEPH | swe.FLG_SPEED
        try:
            result, _ = swe.calc_ut(jd_now, tid, flags)
        except Exception:
            continue
        tlon = result[0]
        sign_data = longitude_to_sign(tlon)

        for target in natal_targets:
            if target not in natal_planets:
                continue
            # Evitar trânsito de planeta sobre si mesmo (ex: Júpiter tr. sobre Júpiter natal)
            # Permitir pois retornos planetários são significativos (ex: retorno de Saturno)
            natal_lon = natal_planets[target]["longitude"]
            aspect = calc_aspect(tlon, natal_lon)
            if aspect and aspect["orb"] <= max_orb:
                # Nomear chiron transitante sem conflito com chiron natal
                display_name = "chiron" if tname == "chiron_tr" else tname
                transits.append({
                    "transit_planet": display_name,
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

    # Ordenar por força: menor orbe primeiro
    transits.sort(key=lambda t: t["orb"])
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
# Eclipse Season - motor (porte 1:1 de calcula_mapa.py, norte-vivo-produtos)
# =============================================================================
FLG = swe.FLG_SWIEPH | swe.FLG_SPEED

SIGNOS = ["Áries", "Touro", "Gêmeos", "Câncer", "Leão", "Virgem", "Libra", "Escorpião",
          "Sagitário", "Capricórnio", "Aquário", "Peixes"]
PLANETAS = {'Sol': swe.SUN, 'Lua': swe.MOON, 'Mercúrio': swe.MERCURY, 'Vênus': swe.VENUS,
 'Marte': swe.MARS, 'Júpiter': swe.JUPITER, 'Saturno': swe.SATURN, 'Urano': swe.URANUS,
 'Netuno': swe.NEPTUNE, 'Plutão': swe.PLUTO, 'Nodo Norte': swe.MEAN_NODE, 'Quíron': swe.CHIRON,
 'Lilith': swe.MEAN_APOG}
# regências do Método Bússola (tradicionais + Quíron rege Virgem)
REGENTES = {"Áries": ["Marte"], "Touro": ["Vênus"], "Gêmeos": ["Mercúrio"],
 "Câncer": ["Lua"], "Leão": ["Sol"], "Virgem": ["Mercúrio", "Quíron"],
 "Libra": ["Vênus"], "Escorpião": ["Plutão", "Marte"], "Sagitário": ["Júpiter"],
 "Capricórnio": ["Saturno"], "Aquário": ["Urano", "Saturno"], "Peixes": ["Netuno", "Júpiter"]}
DOMICILIO = {"Marte": ["Áries", "Escorpião"], "Vênus": ["Touro", "Libra"],
 "Mercúrio": ["Gêmeos", "Virgem"], "Lua": ["Câncer"], "Sol": ["Leão"],
 "Júpiter": ["Sagitário", "Peixes"], "Saturno": ["Capricórnio", "Aquário"]}
EXALTACAO = {"Sol": "Áries", "Lua": "Touro", "Mercúrio": "Virgem", "Vênus": "Peixes",
 "Marte": "Capricórnio", "Júpiter": "Câncer", "Saturno": "Libra"}

ECLIPSE_SOLAR = 120 + 20 + 2 / 60      # 20°02' Leão · 12/08/2026
ECLIPSE_LUNAR = 330 + 4 + 54 / 60      # 4°54' Peixes · 28/08/2026
SAROS_126 = [("22/07/1990", 1990.55), ("01/08/2008", 2008.58),
             ("12/08/2026", 2026.61), ("23/08/2044", 2044.64)]
ASPECTOS = [("conjunção", 0), ("sextil", 60), ("quadratura", 90), ("trígono", 120), ("oposição", 180)]


def fmt(lon):
    s = int(lon // 30); g = lon % 30; m = int(round((g - int(g)) * 60))
    d = int(g)
    if m == 60: d += 1; m = 0
    return f"{d}°{m:02d}' {SIGNOS[s]}"


def grau_sabiano(lon):
    """Convenção do método: truncamento. 22°47' Virgem = Virgem 22."""
    return f"{SIGNOS[int(lon // 30)]} {int(lon % 30)}"


def calc(jd, p): return swe.calc_ut(jd, p, FLG)[0]


def house_of(lon_pt, cusps):
    for i in range(12):
        a = cusps[i]; b = cusps[(i + 1) % 12]
        if a <= b:
            if a <= lon_pt < b: return i + 1
        else:
            if lon_pt >= a or lon_pt < b: return i + 1


def diff(a, b): return abs(((a - b) + 180) % 360 - 180)


def aspectos_para(edeg, pts, orbe=3.0):
    out = []
    for n, (L, retro) in pts.items():
        d = diff(edeg, L)
        for nome, ang in ASPECTOS:
            o = abs(d - ang)
            if o <= orbe:
                out.append(dict(aspecto=nome, ponto=n, posicao=fmt(L),
                                orbe=f"{int(o)}°{int(round((o - int(o)) * 60)):02d}'", orbe_dec=round(o, 2)))
    return sorted(out, key=lambda x: x["orbe_dec"])


def cruzamentos(planeta, target, jd0, jd1, passo=1.0):
    hits = []; prev = None; jd = jd0
    while jd < jd1:
        d = ((calc(jd, planeta)[0] - target) + 180) % 360 - 180
        if prev is not None and prev * d <= 0 and abs(d) < 6:
            lo, hi = jd - passo, jd
            for _ in range(40):
                mid = (lo + hi) / 2
                dm = ((calc(mid, planeta)[0] - target) + 180) % 360 - 180
                dl = ((calc(lo, planeta)[0] - target) + 180) % 360 - 180
                if dl * dm <= 0: hi = mid
                else: lo = mid
            y, m, dd, h = swe.revjul((lo + hi) / 2); hits.append(f"{int(dd):02d}/{int(m):02d}/{y}")
        prev = d; jd += passo
    return hits


def motor(nome, ano, mes, dia, hora_ut, lat, lon):
    jd = swe.julday(ano, mes, dia, hora_ut)
    pts = {}
    for n, p in PLANETAS.items():
        r = calc(jd, p); pts[n] = (r[0], r[3] < 0)
    ns = ((pts['Nodo Norte'][0] + 180) % 360, pts['Nodo Norte'][1])
    pts['Nodo Sul'] = ns
    cusps, ascmc = swe.houses(jd, lat, lon, b'P')
    pts['Ascendente'] = (ascmc[0], False); pts['Meio do Céu'] = (ascmc[1], False)
    fundo = (ascmc[1] + 180) % 360

    def porta(L):
        for i in range(12):
            d = ((cusps[i] - L) % 360)
            if 0 < d <= 2.0: return i + 1
        return None
    natal = {n: dict(posicao=fmt(L), casa=house_of(L, cusps), retro=bool(r),
                  sabiano=grau_sabiano(L),
                  na_porta_da_casa=porta(L)) for n, (L, r) in pts.items()}
    natal['Fundo do Céu'] = dict(posicao=fmt(fundo), casa=4, retro=False, sabiano=grau_sabiano(fundo))

    # dignidades dos pontos-chave
    dign = {}
    for n, (L, _) in pts.items():
        if n in DOMICILIO or n in EXALTACAO:
            sg = SIGNOS[int(L // 30)]; d = []
            if sg in DOMICILIO.get(n, []): d.append("domicílio")
            if EXALTACAO.get(n) == sg: d.append("exaltação")
            if d: dign[n] = d
    # recepções mútuas (planetas pessoais)
    recep = []
    pess = ['Sol', 'Lua', 'Mercúrio', 'Vênus', 'Marte', 'Júpiter', 'Saturno']
    for i, p1 in enumerate(pess):
        for p2 in pess[i + 1:]:
            s1 = SIGNOS[int(pts[p1][0] // 30)]; s2 = SIGNOS[int(pts[p2][0] // 30)]
            if p2 in REGENTES.get(s1, []) and p1 in REGENTES.get(s2, []):
                recep.append(f"{p1} em {s1} / {p2} em {s2}")

    # cadeias de regência do método
    def cadeia_de(rotulo, lon_ponto):
        sg = SIGNOS[int(lon_ponto // 30)]
        return dict(ponto=rotulo, signo=sg,
            regentes=[dict(nome=r, posicao=natal[r]['posicao'], casa=natal[r]['casa'],
                           sabiano=natal[r]['sabiano'],
                           dignidade=dign.get(r, []), retro=natal[r]['retro'])
                      for r in REGENTES[sg] if r in natal])
    cadeias = dict(
        casa1=cadeia_de("Casa 1 (Ascendente)", ascmc[0]),
        casa7=cadeia_de("Casa 7", cusps[6]),
        nodo_sul=cadeia_de("Nodo Sul", ns[0]),
        nodo_norte=cadeia_de("Nodo Norte", pts['Nodo Norte'][0]),
        lua=cadeia_de("Lua", pts['Lua'][0]),
        casa_eclipse_solar=cadeia_de("Casa do eclipse solar", cusps[house_of(ECLIPSE_SOLAR, cusps) - 1]),
    )

    # eclipses no mapa
    # "data" é o único campo que registra o dia real do evento (12/08 e 28/08 de 2026) no
    # JSON serializado — antes só existia como comentário Python ao lado de ECLIPSE_SOLAR/
    # ECLIPSE_LUNAR (nunca chegava no eclipse_season_json), o que deixava o Claude do
    # norte-vivo-produtos-api sem a data real e o levava a alucinar ano/dia errado na prosa
    # gerada (achado da revisão da Aferidor, fatia PDF do Mapa dos Eclipses).
    ecl_solar = dict(grau="20°02' Leão", data="12/08/2026",
        sabiano="Leão 20 · índios Zuni realizam um ritual ao Sol",
        casa=house_of(ECLIPSE_SOLAR, cusps), na_porta_da_casa=None,
        aspectos=aspectos_para(ECLIPSE_SOLAR, pts),
        conj_ampla=[dict(ponto=n, posicao=fmt(L), orbe=round(diff(ECLIPSE_SOLAR, L), 2))
                    for n, (L, _) in pts.items() if 3.0 < diff(ECLIPSE_SOLAR, L) <= 4.5
                    and int(L // 30) == 4])
    ecl_lunar = dict(grau="4°54' Peixes", data="28/08/2026",
        sabiano="Peixes 4 · tráfego intenso num istmo estreito que liga dois balneários",
        casa=house_of(ECLIPSE_LUNAR, cusps), aspectos=aspectos_para(ECLIPSE_LUNAR, pts))

    # eclipse de 2022 (assinatura do buraco negro): 2°00' Escorpião
    e22 = 210 + 2.0
    ecl_2022 = dict(grau="2°00' Escorpião", casa=house_of(e22, cusps),
                  aspectos=aspectos_para(e22, pts, orbe=3.0))

    # calendário de Júpiter sobre o Sol natal e sobre o Nodo Sul natal (se em signos alcançáveis 2026-27: Leão/Virgem)
    jd0 = swe.julday(2026, 8, 1); jd1 = swe.julday(2027, 12, 31)
    jup = dict()
    jup['sobre_o_Sol'] = cruzamentos(swe.JUPITER, pts['Sol'][0], jd0, jd1)
    jup['sobre_o_Nodo_Sul'] = cruzamentos(swe.JUPITER, ns[0], jd0, jd1)
    jup['estacoes'] = "Rx 13/12/2026 a 27° Leão · direta 13/04/2027 a 17°00' Leão"

    # retorno de Vênus na janela (jul-out 2026)
    vret = cruzamentos(swe.VENUS, pts['Vênus'][0], swe.julday(2026, 7, 1), swe.julday(2026, 10, 31), passo=0.25)

    # trânsitos de contexto no dia do eclipse (lentos + Saturno/Quíron/Marte) a natal, orbe 2.5
    jde = swe.julday(2026, 8, 12, 17.77)
    ctx = []
    for tn, tp in [('Plutão', swe.PLUTO), ('Netuno', swe.NEPTUNE), ('Urano', swe.URANUS),
                  ('Saturno', swe.SATURN), ('Quíron', swe.CHIRON), ('Júpiter', swe.JUPITER), ('Marte', swe.MARS)]:
        L = calc(jde, tp)[0]
        for n, (Ln, _) in pts.items():
            d = diff(L, Ln)
            for nome_asp, ang in ASPECTOS:
                o = abs(d - ang)
                if o <= 2.5:
                    ctx.append(dict(transito=f"{tn} a {fmt(L)}", aspecto=nome_asp, natal=f"{n} {fmt(Ln)}",
                                    casa_transitada=house_of(L, cusps), orbe=round(o, 2)))
    ctx = sorted(ctx, key=lambda x: x['orbe'])

    # idades de Saros
    ano_dec = ano + (mes - 1) / 12 + dia / 365
    saros = [dict(data=d, idade=round(y - ano_dec, 1)) for d, y in SAROS_126]

    return dict(nome=nome,
        nascimento=f"{dia:02d}/{mes:02d}/{ano} {int(hora_ut):02d}:{int((hora_ut % 1) * 60):02d} UT · lat {lat} lon {lon}",
        natal=natal, cuspides=[fmt(c) for c in cusps],
        dignidades=dign, recepcoes_mutuas=recep, cadeias=cadeias,
        eclipse_solar=ecl_solar, eclipse_lunar=ecl_lunar, eclipse_2022=ecl_2022,
        jupiter=jup, retorno_de_venus=vret, contexto_transitos=ctx[:14], saros=saros)


# --- pós-processamento determinístico (achados não computados por motor() hoje) ---
_POSICAO_RE = re.compile(r"(\d+)°(\d+)'\s*(.+)")
_ANGULOS_EXCLUIDOS_REDE_DE_GRAU = {"Ascendente", "Meio do Céu", "Fundo do Céu"}
_JUPITER_ESTACOES_FIXAS = [
    {"estacao": "27°00' Leão retrógrada", "longitude": 4 * 30 + 27},
    {"estacao": "17°00' Leão direta", "longitude": 4 * 30 + 17},
]
_PONTOS_ACHADO_DE_CAPA = ["Sol", "Ascendente", "Meio do Céu", "Nodo Norte", "Nodo Sul"]


def _posicao_para_grau_signo(posicao: str):
    """Reconstroi (grau_truncado, grau_decimal, longitude_absoluta) a partir da string formatada por fmt()."""
    m = _POSICAO_RE.match(posicao.strip())
    deg, minutos, signo = int(m.group(1)), int(m.group(2)), m.group(3).strip()
    grau_decimal = deg + minutos / 60.0
    longitude_absoluta = SIGNOS.index(signo) * 30 + grau_decimal
    return deg, grau_decimal, longitude_absoluta


def _calcular_rede_de_grau(natal: dict) -> list:
    """Regra de ouro (arquitetura-mapa.md, seção 5): 3+ pontos no mesmo grau, tolerância 1°.

    "Tolerância 1°" é lida como diâmetro do grupo, não cadeia transitiva: todos os membros
    precisam estar mutuamente a até 1° de distância entre si (grau truncado). Uma janela de
    3 graus truncados consecutivos (ex.: 8, 9, 10) tem diâmetro 2 e NÃO forma uma rede — só
    duas casas de grau adjacentes (ex.: 22 e 23) podem se combinar num único grupo.
    """
    nomes = [n for n in natal if n not in _ANGULOS_EXCLUIDOS_REDE_DE_GRAU]
    graus = {n: _posicao_para_grau_signo(natal[n]["posicao"])[:2] for n in nomes}

    candidatos = []
    for g in range(30):
        janela = {g, (g + 1) % 30}
        membros = frozenset(n for n in nomes if graus[n][0] in janela)
        if len(membros) >= 3:
            candidatos.append(membros)

    # mantém só grupos maximais (descarta quem é subconjunto de outro candidato)
    maximais = [c for c in candidatos if not any(c < outro for outro in candidatos)]
    grupos_unicos = {frozenset(m) for m in maximais}

    rede = []
    for membros in grupos_unicos:
        membros_ordenados = sorted(membros, key=lambda n: graus[n][1])
        valores = [graus[n][0] for n in membros_ordenados]
        moda = max(set(valores), key=lambda v: (valores.count(v), -v))
        rede.append({"grau": str(moda), "pontos": membros_ordenados})
    rede.sort(key=lambda g: g["grau"])
    return rede


def _calcular_achados_de_capa(natal: dict) -> list:
    """Regra do achado de capa (arquitetura-mapa.md): estação a menos de 1° de Sol/Ascendente/Meio do Céu/Nodos natais."""
    achados = []
    for estacao in _JUPITER_ESTACOES_FIXAS:
        for ponto in _PONTOS_ACHADO_DE_CAPA:
            if ponto not in natal:
                continue
            _, _, lon_natal = _posicao_para_grau_signo(natal[ponto]["posicao"])
            orbe = diff(estacao["longitude"], lon_natal)
            if orbe < 1.0:
                achados.append({"estacao": estacao["estacao"], "ponto_natal": ponto, "orbe": round(orbe, 2)})
    return achados


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


@app.post("/calculate-eclipse-season")
def calculate_eclipse_season(data: EclipseSeasonRequest):
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
    ano, mes, dia, hora_ut = swe.revjul(jd)

    # 4. Motor do Mapa dos Eclipses (porte de calcula_mapa.py)
    eclipse_season_json = motor("", ano, mes, int(dia), hora_ut, lat, lon)

    # 5. Pós-processamento determinístico (achados que motor() não computa hoje)
    eclipse_season_json["rede_de_grau"] = _calcular_rede_de_grau(eclipse_season_json["natal"])
    eclipse_season_json["jupiter"]["achados_de_capa"] = _calcular_achados_de_capa(eclipse_season_json["natal"])

    return {
        "resolved_location": resolved_location,
        "eclipse_season_json": eclipse_season_json,
    }


@app.get("/")
def root():
    return {
        "service": "ANCORADA Chart API",
        "version": "1.3.0-eclipse-season",
        "engine": "pyswisseph (Swiss Ephemeris)",
        "endpoints": ["POST /calculate-chart", "POST /calculate-eclipse-season"],
    }


@app.get("/health")
def health():
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


@app.get("/debug-chiron")
def debug_chiron():
    """Debug endpoint to diagnose Chiron calculation issues."""
    swe.set_ephe_path(_EPHE_PATH)
    info = {
        "ephe_path": _EPHE_PATH,
        "ephe_exists": _os.path.isdir(_EPHE_PATH),
        "ephe_files": _os.listdir(_EPHE_PATH) if _os.path.isdir(_EPHE_PATH) else [],
        "pyswisseph_version": getattr(swe, "__version__", "unknown"),
        "chiron_id": swe.CHIRON,
    }
    jd = swe.julday(1990, 1, 15, 14.0)
    for method_name, flag in [("SWIEPH", swe.FLG_SWIEPH), ("MOSEPH", swe.FLG_MOSEPH)]:
        try:
            result, retflag = swe.calc_ut(jd, swe.CHIRON, flag | swe.FLG_SPEED)
            info[f"chiron_{method_name}"] = {"ok": True, "longitude": result[0]}
        except Exception as e:
            info[f"chiron_{method_name}"] = {"ok": False, "error": str(e)}
    return info

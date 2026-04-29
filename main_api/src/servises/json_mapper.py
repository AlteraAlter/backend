from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any
from urllib.parse import urlparse


def _merge_value(current: Any, value: str) -> Any:
    if current in (None, ""):
        return value
    if isinstance(current, list):
        if value not in current:
            current.append(value)
        return current
    if current == value:
        return current
    return [current, value]


def _parse_custom_item_specifics(value: Any) -> dict:
    if value is None:
        return {}

    text = str(value).strip()
    if not text or "<NameValueList" not in text:
        return {}

    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return _parse_custom_item_specifics_with_regex(text)

    specifics: dict[str, Any] = {}
    for node in root.findall(".//NameValueList"):
        name = (node.findtext("Name") or "").strip()
        if not name:
            continue
        for value_node in node.findall("Value"):
            item_value = (value_node.text or "").strip()
            if item_value:
                specifics[name] = _merge_value(specifics.get(name), item_value)
    return specifics


def _parse_custom_item_specifics_with_regex(text: str) -> dict:
    specifics: dict[str, Any] = {}
    for block in re.findall(
        r"<NameValueList\b[^>]*>(.*?)</NameValueList>",
        text,
        flags=re.DOTALL | re.IGNORECASE,
    ):
        name_match = re.search(
            r"<Name\b[^>]*>\s*(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?\s*</Name>",
            block,
            flags=re.DOTALL | re.IGNORECASE,
        )
        if not name_match:
            continue

        name = name_match.group(1).strip()
        if not name:
            continue

        for value_match in re.finditer(
            r"<Value\b[^>]*>\s*(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?\s*</Value>",
            block,
            flags=re.DOTALL | re.IGNORECASE,
        ):
            item_value = value_match.group(1).strip()
            if item_value:
                specifics[name] = _merge_value(specifics.get(name), item_value)
    return specifics


def _parse_price(value: Any) -> float | int:
    if value is None or isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        return value

    text = str(value).strip().replace("\u00a0", "").replace(" ", "")
    if not text:
        return 0
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    else:
        text = text.replace(",", ".")

    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return 0
    try:
        parsed = float(match.group(0))
    except ValueError:
        return 0
    return int(parsed) if parsed.is_integer() else parsed


def _normalize_ean(value: Any) -> str:
    if isinstance(value, list):
        value = value[0] if value else ""
    if value is None:
        return ""

    text = str(value).strip()
    if text.endswith(".0"):
        try:
            text = str(int(float(text)))
        except ValueError:
            pass

    digits = re.sub(r"\D", "", text)
    return digits if len(digits) >= 8 else ""


def _first_specific(specifics: dict, *keys: str) -> Any:
    for key in keys:
        value = specifics.get(key)
        if value not in (None, ""):
            return value
    return ""


def _first_measurement(specifics: dict) -> Any:
    direct = specifics.get("Maße")
    if direct not in (None, ""):
        return direct

    for key, value in specifics.items():
        if key.startswith("Maße") and value not in (None, ""):
            return value
    return ""


def _guess_fabric(elem: dict) -> str:
    raw_url = elem.get("GalleryURL") or elem.get("PictureURL") or ""
    if not raw_url:
        return ""

    path_parts = [part for part in urlparse(str(raw_url)).path.split("/") if part]
    try:
        service_index = path_parts.index("AfterbuyUploadService")
    except ValueError:
        service_index = -1

    if service_index >= 0 and len(path_parts) > service_index + 2:
        return path_parts[service_index + 2]
    if service_index >= 0 and len(path_parts) > service_index + 1:
        return path_parts[service_index + 1]
    return path_parts[-2] if len(path_parts) >= 2 else ""


def normalize_json_item(elem: dict) -> dict:
    normalized = dict(elem)
    specifics = _parse_custom_item_specifics(elem.get("CustomItemSpecifics"))

    for key, value in specifics.items():
        normalized.setdefault(key, value)

    if "Startpreis" in normalized:
        normalized["Startpreis"] = _parse_price(normalized.get("Startpreis"))

    if "Farbe" in normalized:
        normalized["Farbe"] = str(normalized.get("Farbe")).strip()    
        
    ean = _normalize_ean(normalized.get("EAN"))
    if not ean:
        ean = _normalize_ean(
            str(normalized.get("Herstellernummer", "")).replace("JVM", "")
        )
    normalized["EAN"] = ean

    if not normalized.get("Maße"):
        measurement = _first_measurement(specifics)
        if measurement:
            normalized["Maße"] = measurement
            
    if "I_stammartikel" in normalized:
        normalized["I_stammartikel"] = str(normalized.get("I_stammartikel")).strip()

    if not normalized.get("Fabric"):
        normalized["Fabric"] = _guess_fabric(normalized)

    for target_key, source_keys in {
        "Farbe": ("Farbe",),
        "Höhe": ("Höhe",),
        "Länge": ("Länge",),
        "Breite": ("Breite",),
        "Anzahl der Teile": ("Anzahl der Teile",),
        "Material": ("Material", "Polsterstoff", "Gestellmaterial", "Füllmaterial"),
    }.items():
        if not normalized.get(target_key):
            value = _first_specific(specifics, *source_keys)
            if value:
                normalized[target_key] = value

    return normalized


def map_json_item(elem: dict) -> dict:
    if elem.get("CustomItemSpecifics"):
        elem = normalize_json_item(elem)
    return {
        "article": elem.get("Artikelbeschreibung", ""),
        "price": elem.get("Startpreis", 0),
        "I_stammartikel": elem.get("I_stammartikel", ""),
        "pic_main": elem.get("GalleryURL", elem.get("PictureURL")),
        "pics": (
            elem.get("pictureurls", "").split(";")
            if isinstance(elem.get("pictureurls", ""), str)
            else elem.get("pictureurls", [])
        ),
        "ean": elem.get("EAN", elem.get("Herstellernummer", "").replace("JVM", "")),
        "fabric": elem.get("Fabric", ""),
        "size": elem.get("Maße", ""),
        "color": elem.get("Farbe", ""),
        "height": elem.get("Höhe", ""),
        "length": elem.get("Länge", ""),
        "width": elem.get("Breite", ""),
        "material": elem.get(
            "Material",
            elem.get(
                "Polsterstoff",
                elem.get("Gestellmaterial", elem.get("Füllmaterial", None)),
            ),
        ),
        "number_of_units": elem.get("Anzahl der Teile", ""),
    }

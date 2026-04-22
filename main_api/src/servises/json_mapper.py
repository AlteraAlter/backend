def map_json_item(elem: dict) -> dict:
    return {
        "article": elem.get("Artikelbeschreibung", ""),
        "price": elem.get("Startpreis", 0),
        "pic_main": elem.get("GalleryURL", elem.get("PictureURL")),
        "pics": (
            elem.get("pictureurls", "").split(";")
            if isinstance(elem.get("pictureurls", ""), str)
            else elem.get("pictureurls", [])
        ),
        "ean": elem.get("EAN", elem.get("Herstellernummer", "").replace("JVM", "")),
        "fabric": elem.get("Fabric"),
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

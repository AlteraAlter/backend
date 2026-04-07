import asyncio

from openai import OpenAI
from config import GPT_API_KEY


client = OpenAI(api_key=GPT_API_KEY)


async def generate_description(article, size, color, material):
    """
    функция для генерации короткого описания для продукта
    """

    prompt = f"""
    Erstelle eine verkaufsstarke Produktbeschreibung auf Deutsch mit maximal 750 Zeichen. 
    Der Stil soll luxuriös, elegant und überzeugend sein und anspruchsvolle Kunden ansprechen. 
    Der Text soll sich ausschließlich auf das Produkt konzentrieren und ohne unnötige Floskeln auskommen.

    Produktdaten:
    - Produktname: {article}
    - Größe: {size}
    - Farbe und Material: {color} {material}

    Zusätzliche Hinweise:
    - Die Marke bietet seit 20 Jahren luxuriöse Möbel für höchste Ansprüche.
    - Es gibt eine große Auswahl an hochwertigen Designs für ein exklusives Wohnambiente.
    - Der Text soll verdeutlichen, warum dieses Möbelstück die perfekte Wahl ist und einen exklusiven Lebensstil 
    unterstreicht.

    WICHTIG: Antworte ausschließlich mit dem fertigen Beschreibungstext, ohne Titel, Erklärungen oder Zusätze.
    """

    def _do_request():
        return client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "Du bist ein professioneller Werbetexter für luxuriöse Möbelmarken. Du verfasst exklusive, "
                    "verkaufsstarke Produktbeschreibungen auf Deutsch für eine anspruchsvolle Kundschaft im "
                    "Premiumsegment. Dein Schreibstil ist elegant, selbstbewusst und überzeugt durch Exklusivität. "
                    "Du verwendest keine Emojis und keine überflüssigen Floskeln. Du betonst die Hochwertigkeit, "
                    "den luxuriösen Charakter, die handwerkliche Qualität und die Einzigartigkeit jedes Produkts. "
                    "Antworte ausschließlich mit dem fertigen Beschreibungstext, ohne Überschriften, Einleitungen, "
                    "Erklärungen oder Zusatztexte.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.7,
        )

    response = await asyncio.to_thread(_do_request)

    description = response.choices[0].message.content.strip()
    return description


async def generate_seo(article, size=None, color=None, material=None):
    """
    Генерация SEO short_description для продукта (7 ключевых слов).
    Пример формата результата:
    ["Schminktisch", "Luxus", "Kommode", "Design", "Modern", "Weiß", "Holz"]
    """
    # Формируем промпт для модели
    prompt = f"""
    Erstelle 7 kurze, prägnante SEO-Schlüsselwörter (nur EIN Wort pro Schlüsselwort) 
    für ein luxuriöses Möbelprodukt auf Deutsch.

    Produktdaten:
    - Artikel: {article}
    - Größe: {size or "Nicht angegeben"}
    - Farbe: {color or "Nicht angegeben"}
    - Material: {material or "Nicht angegeben"}

    Anforderungen:
    - Gib GENAU 7 Wörter zurück.
    - Jedes Wort soll ein aussagekräftiges Schlüsselwort sein (z.B. Produkttyp, Stilrichtung, Farbe, Material, Zielgruppe).
    - Verwende KEINE Satzzeichen, keine Zahlen, keine Emojis.
    - KEINE Sätze, nur einzelne Wörter.
    - Gib die Wörter in einer JSON-Liste zurück, z.B.: ["Wort1", "Wort2", ...]
    """

    def _do_request():
        return client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "Du bist ein professioneller SEO-Texter für luxuriöse Möbel. "
                    "Du erstellst exklusive, prägnante und hochwertige SEO-Schlüsselwörter auf Deutsch. "
                    "Du verwendest keine Emojis, keine Satzzeichen und keine Erklärungen.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.6,
        )

    response = await asyncio.to_thread(_do_request)

    seo_text = response.choices[0].message.content.strip()

    # Попытка безопасно распарсить JSON-список
    try:
        import json

        seo_keywords = json.loads(seo_text)
        if isinstance(seo_keywords, list) and len(seo_keywords) == 7:
            return seo_keywords
        else:
            print(f"[SEO WARNING] Неверный формат ответа: {seo_text}")
            return []
    except json.JSONDecodeError:
        print(f"[SEO ERROR] Не удалось распарсить JSON: {seo_text}")
        return []


if __name__ == "__main__":

    async def main():
        seo_list = await generate_seo(
            article="Luxuriöser Schminktisch",
            size="120x80 cm",
            color="Weiß",
            material="Massivholz",
        )
        print(seo_list)
        # ➡ ["Schminktisch", "Luxus", "Weiß", "Massivholz", "Design", "Modern", "Elegant"]

    asyncio.run(main())

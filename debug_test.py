import json

body = {
            "item": {
                "title": "Some article",
                "description": "Some desc",
                "manufacturer": "AEA GmbH & Co. KG",
            },
            "price": 2000_000,
        }

cat = json.dumps(body, separators=(",", ":"))
print(body)
print(cat)


from rest_framework.test import APITestCase
from django.urls import reverse
from django.contrib.auth.models import User

class PatchProductViewTest(APITestCase):
    
    def test_patch_product(self):
        url = reverse("patch_product")
        
        payload = {
            "ean": "4343434343434",
            "storefront": "de",
            "controller": "jv",
            "price": 1999.2,
            "unit_id": "11111111",
            "description": "Some kind of description",
        }
                
        response = self.client.patch(url, data=payload, format="json")

        assert response.status_code == 200
        assert response.data["received_data"]["ean"] == "4343434343434"
import io
import json
from django.shortcuts import render
import aiohttp
from adrf.views import APIView
from django.http import HttpResponse
from main_api.src.logger import log
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
import pandas as pd
from main_api.serializers import FileUploadSerializer, CombinedUploadSerializer
from main_api.src.controller.kaufland_controller import KauflandController


# Create your views here.

class MainOperationsView(APIView):
    """
        Класс который делает основные операции удаляет или изменяет цены
    """
    permission_classes = [IsAuthenticated]
    serializer_class = FileUploadSerializer

    async def get(self, request):
        return Response({"message": "ok"}, status=status.HTTP_200_OK)

    async def post(self, request):
        serializer = FileUploadSerializer(data=request.data)

        if serializer.is_valid():
            file = serializer.validated_data['file']
            mode = serializer.data["mode"]
            controller = serializer.data["controller"]
            # Проверяем расширение
            filename = file.name.lower()
            if filename.endswith(".csv"):
                df = pd.read_csv(file)
            elif filename.endswith(".xlsx"):
                df = pd.read_excel(file)
            else:
                return Response(
                    {"error": "Неподдерживаемый формат файла"},
                    status=status.HTTP_400_BAD_REQUEST
                )

            try:
                async with aiohttp.ClientSession() as session:
                    kaufland_controller = KauflandController(session, controller)

                    if set(df.columns) == {"ean"}:
                        # Только колонка ean -> список
                        df = df.astype({"ean": str})
                        eans_list = list(set(df["ean"].tolist()))

                        if mode == "delete":
                            log(f"Сработало условие удаления для {len(eans_list)} товаров", save=True)
                            result = await kaufland_controller.delete_all_products(eans_list)
                            if result:
                                return Response({"message": f"Все продукты с ean: "
                                                            f"{json.dumps(eans_list, indent=2)} были удалены"},
                                                status=status.HTTP_200_OK)
                            else:
                                return Response({"message": f"Где-то была ошибка и продукты не удалились"},
                                                status=status.HTTP_400_BAD_REQUEST)
                        elif mode == "checker":
                            log(f"Сработало условие чекера для {len(eans_list)} товаров", save=True)
                            result = await kaufland_controller.products_checker(eans_list)

                            # Преобразуем список словарей в DataFrame
                            df = pd.DataFrame(result)
                            buffer = io.BytesIO()
                            with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
                                df.to_excel(writer, index=False, sheet_name="Products")

                            buffer.seek(0)

                            response = HttpResponse(
                                buffer,
                                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                            )
                            response["Content-Disposition"] = 'attachment; filename="result.xlsx"'
                            return response

                        return Response({"info": "Ты не можешь использовать изменение цен передав только EAN"},
                                        status=status.HTTP_400_BAD_REQUEST)
                    elif set(df.columns) >= {"ean", "price"}:
                        # Есть ean + price -> словарь
                        log('Сработало условие')
                        df = df.astype({"ean": str, "price": float})
                        eans_prices = dict(zip(df["ean"], df["price"]))
                        if mode == "delete":
                            log(f"Запущено удаление для {len(eans_prices)} товаров", save=True)
                            result = await kaufland_controller.delete_all_products(list(eans_prices.keys()))
                            if result:
                                return Response({"message": f"Все продукты с ean: "
                                                            f"{json.dumps(eans_prices, indent=2)} были удалены"},
                                                status=status.HTTP_200_OK)
                            else:
                                return Response({"message": f"Где-то была ошибка и продукты не удалились"},
                                                status=status.HTTP_200_OK)
                        elif mode == "change_price":
                            log(f"Запущено изменение цен для {len(eans_prices)} товаров", save=True)
                            result = await kaufland_controller.update_price(eans_prices)
                            if result:
                                return Response("Все прошло успешны цены измененены", status=status.HTTP_200_OK)
                            return Response("Где-то что-то сломалось", status=status.HTTP_500_INTERNAL_SERVER_ERROR)
                        else:
                            "Вызываем функцию изменения цен"
                    else:
                        return Response(
                            {"error": "Файл должен содержать колонку 'ean' (и опционально 'price')"},
                            status=status.HTTP_400_BAD_REQUEST
                        )
            except Exception as e:
                return Response(
                    {"error": f"Ошибка обработки файла: {str(e)}"},
                    status=status.HTTP_400_BAD_REQUEST
                )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class UploadCollectionsViaJsonView(APIView):
    """
        Класс для загрузки товаров на Kaufland через JSON
    """
    permission_classes = [IsAuthenticated]
    serializer_class = CombinedUploadSerializer

    async def get(self, request):
        return Response({"info": "Kaufland uploader via json"}, status=status.HTTP_200_OK)

    async def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)


        controller = serializer.validated_data['controller']
        json_content = serializer.validated_data['json_content']

        async with aiohttp.ClientSession() as session:
            kauf_controller = KauflandController(session, controller)
            json_content = [{"article": elem.get("Artikelbeschreibung", ""),
                            "price": elem.get("Startpreis", 0),
                            "pic_main": elem.get("GalleryURL", elem.get("PictureURL")),
                            "pics": elem.get("pictureurls", '').split(";") if isinstance(elem.get("pictureurls", ''), str) else elem.get("pictureurls", []),
                            "ean": elem.get("EAN", elem.get("Herstellernummer", "").replace("JVM", "")),
                            "fabric": elem["Fabric"],
                            "size": elem.get("Maße", ""),
                            "color": elem.get('Farbe', ""),
                            "height": elem.get("Höhe", ""),
                            "length": elem.get("Länge", ""),
                            "width": elem.get('Breite', ""),
                            "material": elem.get("Polsterstoff", elem.get('Gestellmaterial'))}
                          for elem in json_content]
            log(f"Начинаем загрузку {len(json_content)} товаров через json", save=True)
            result = await kauf_controller.upload_via_json(json_content)
            if result is True:  # Все успешно
                return Response({"message": "success"}, status=status.HTTP_200_OK)
            elif result is False:  # Частично успешно
                return Response({"message": f"not all products were uploaded: result: {result}"},
                                status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            elif result is None:  # Все неуспешно
                return Response({"message": f"no products were uploaded: result: {result}"},
                                status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class ProtectedView(APIView):
    permission_classes = [IsAuthenticated]

    async def get(self, request):
        return Response({"message": "ok"}, status=status.HTTP_200_OK)

def main_view(request):
    return render(request, 'main.html')

def index(request):
    if request.path == '/api/delete_real/':
        return render(request, 'delete_real.html')
    elif request.path == '/api/change_price/':
        return render(request, "price_update.html")
    return render(request, 'index.html')

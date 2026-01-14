import json
import os


from rest_framework import serializers


class FileUploadSerializer(serializers.Serializer):
    controller = serializers.ChoiceField(choices=["jv", "xl"])
    file = serializers.FileField()
    mode = serializers.ChoiceField(choices=["delete", "change_price", "checker", "invalid_items"])

    def validate_file(self, value):
        """
        Проверка расширения файла
        """
        valid_extensions = ['.xlsx', '.csv']
        ext = os.path.splitext(value.name)[1].lower()
        if ext not in valid_extensions:
            raise serializers.ValidationError(
                f"Неподдерживаемый формат файла. Разрешены только: {', '.join(valid_extensions)}"
            )
        return value

class ControllerSerializer(serializers.Serializer):
    controller = serializers.ChoiceField(choices=["jv", "xl"])


class JsonFileSerializer(serializers.Serializer):
    file = serializers.FileField()

    # Настройки: допустимые MIME-типы и расширения
    ALLOWED_MIME_PREFIXES = ("application/json", "text/json")
    ALLOWED_EXTENSIONS = (".json",)

    def validate_file(self, uploaded_file):
        """
        Проверяет:
         - MIME-type (если доступен)
         - расширение файла
         - содержит ли файл корректный JSON (пытаемся json.load)
        """
        # 1) Проверяем MIME-type (если есть)
        content_type = getattr(uploaded_file, "content_type", None)
        if content_type:
            # allow when prefix matches (например "application/json; charset=utf-8")
            if not any(content_type.startswith(pref) for pref in self.ALLOWED_MIME_PREFIXES):
                raise serializers.ValidationError("Неверный MIME-type: ожидается JSON файл.")

        # 2) Проверяем расширение (если имя присутствует)
        filename = getattr(uploaded_file, "name", "")
        _, ext = os.path.splitext(filename.lower())
        if ext and ext not in self.ALLOWED_EXTENSIONS:
            raise serializers.ValidationError("Неверное расширение файла: ожидается .json")

        # 3) Проверяем что содержимое — корректный JSON
        # uploaded_file может быть InMemoryUploadedFile или TemporaryUploadedFile
        # поэтому читаем байты/строку аккуратно и восстанавливаем позицию
        try:
            # сохраняем текущую позицию
            pos = uploaded_file.tell()
        except (AttributeError, OSError):
            pos = None

        try:
            # прочитаем всё и попытаемся распарсить
            raw = uploaded_file.read()
            # raw может быть bytes или str
            if isinstance(raw, bytes):
                text = raw.decode('utf-8')
            else:
                text = raw

            # Попытка парсинга
            json.loads(text)
        except (ValueError, json.JSONDecodeError):
            raise serializers.ValidationError("Файл не является валидным JSON.")
        except Exception as exc:
            raise serializers.ValidationError(f"Ошибка при чтении файла: {exc}")
        finally:
            # вернём указатель в начало, чтобы view/дальнейшая логика могли снова читать файл
            try:
                if pos is not None:
                    uploaded_file.seek(pos)
                else:
                    uploaded_file.seek(0)
            except Exception:
                pass

        return uploaded_file

    def to_internal_value(self, data):
        """
        Обычная обработка, но можно дополнительно добавить распарсенный JSON в validated_data,
        чтобы view мог получить уже Python-объект.
        """
        validated = super().to_internal_value(data)
        uploaded_file = validated.get("file")

        # распарсим и положим в поле json_content (не обязательно сохранять в модель)
        try:
            raw = uploaded_file.read()
            if isinstance(raw, bytes):
                text = raw.decode('utf-8')
            else:
                text = raw
            parsed = json.loads(text)
            # вернём указатель назад
            uploaded_file.seek(0)
        except Exception:
            parsed = None

        validated["json_content"] = parsed
        return validated


class CombinedUploadSerializer(serializers.Serializer):
    """
        Сериализатор который используется для валидации и контроллера
        и передаваемого json
    """
    controller = serializers.CharField()
    file = serializers.FileField()

    def to_internal_value(self, data):
        # 1️⃣ Валидируем controller через ControllerSerializer
        controller_serializer = ControllerSerializer(data={"controller": data.get("controller")})
        controller_serializer.is_valid(raise_exception=True)

        # 2️⃣ Валидируем file через JsonFileSerializer
        file_serializer = JsonFileSerializer(data={"file": data.get("file")})
        file_serializer.is_valid(raise_exception=True)

        return {
            "controller": controller_serializer.validated_data["controller"],
            "file": file_serializer.validated_data["file"],
            "json_content": file_serializer.validated_data["json_content"],
        }
